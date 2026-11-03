"""fix-cost-redaction: case cost = ledger, wrong-line masks, repeated cites.

1. Case cost and call count tie to the per-call ledger: the replay sample
   runs through a live-mode MetaClient whose transport serves the recorded
   fixtures, so every call writes a real reserved+completed ledger pair.
   Reruns and failures keep their billed spend and calls.
2. A PII box the reader put on the wrong line of a dense right-aligned
   receipt is needs_review (never a silent mask on another line), and the
   leak check spots the reading's number still visible.
3. An immediately repeated identical citation renders once.
No live calls.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.agents import case_state as case_state_mod
from app.agents import coordinator as coord
from app.agents import demo_inputs
from app.agents import deps
from app.agents import privacy_guard as privacy_mod
from app.agents.base import AgentSchemaError
from app.main import app
from app.meta import client as client_mod
from app.services import pdf_compiler as pdf_compiler_mod
from app.services import redaction as redact_mod

from test_case_contract import (  # noqa: F401  (shared fakes)
    fake_drafter,
    fake_organizer,
    fake_reader,
)

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / "backend" / "app" / "templates" / "fonts" / "NanumGothic-Regular.ttf"


def board_calls(view: dict) -> int:
    """Python twin of frontend/case.js countModelCalls."""
    total = 0
    for step in view.get("steps", []):
        if not step.get("model"):
            continue
        subs = step.get("substeps") or []
        if step["key"] in ("reading", "vision") and subs:
            for sub in subs:
                calls = int(sub.get("calls") or 0)
                if calls > 0:
                    total += calls
                elif sub.get("status") == "done":
                    total += 1
        else:
            total += int(step.get("attempts") or 0)
    return total


# --- 1. case cost = ledger ------------------------------------------------------
class _FixtureResponses:
    """Live-transport stand-in that answers from the recorded fixtures."""

    def create(self, **kwargs):
        params = {"store": bool(kwargs.get("store", False))}
        if "max_output_tokens" in kwargs:
            params["max_output_tokens"] = int(kwargs["max_output_tokens"])
        if "text" in kwargs:
            params["text_format"] = kwargs["text"]["format"]
        if "reasoning" in kwargs:
            params["reasoning"] = kwargs["reasoning"]
        for key, value in kwargs.items():
            if key not in ("model", "input", "store", "max_output_tokens",
                           "text", "reasoning"):
                params[key] = value
        digest = client_mod.request_hash(
            kwargs["model"], "responses", params, kwargs["input"])
        path = client_mod.DEFAULT_FIXTURE_DIR / f"{digest}.json"
        return json.loads(path.read_text(encoding="utf-8"))["response"]


class _FixtureTransport:
    responses = _FixtureResponses()


@pytest.fixture()
def ledger_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "replay")
    for name in ("reader", "organizer", "drafter"):
        monkeypatch.setitem(coord.AGENTS, name, None)
    ledger = tmp_path / "ledger.jsonl"
    real = client_mod.MetaClient

    def _ledger_client(mode=None, run_id=None, **kwargs):
        return real(mode="live", run_id=run_id, ledger_path=ledger,
                    transport=_FixtureTransport())

    monkeypatch.setattr(deps, "MetaClient", _ledger_client)
    return TestClient(app), ledger


def _ledger_for(ledger: Path, case_id: str):
    rows = [json.loads(line) for line in
            ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = client_mod.ledger_summary(run_id_prefix=case_id,
                                        ledger_path=ledger)
    completed = sum(1 for row in rows if row.get("run_id") == case_id
                    and row.get("status") == "completed")
    reserved = sum(1 for row in rows if row.get("run_id") == case_id
                   and row.get("status") == "reserved")
    return summary["by_run_id"].get(case_id, 0.0), completed, reserved


def test_case_cost_and_calls_equal_ledger_on_recorded_sample(ledger_env):
    client, ledger = ledger_env
    case_id = client.post("/api/cases/sample", json={"set": "kr"}).json()["case_id"]
    view = client.post(f"/api/cases/{case_id}/run", json={}).json()
    assert view["state"] == "CHECKPOINT_1", view
    cost, completed, reserved = _ledger_for(ledger, case_id)
    # Each call writes a reservation and its final line; the reservation is
    # offset (ledger_summary), so a raw row sum double counts.
    assert reserved == completed == 33
    assert view["run_cost_usd"] == coord.fmt_cost(cost)
    assert board_calls(view) == completed

    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    assert client.put(f"/api/cases/{case_id}/facts", json=facts).status_code == 200
    view = client.post(f"/api/cases/{case_id}/run", json={}).json()
    assert view["state"] == "DRAFT_APPROVAL", view
    cost, completed, _ = _ledger_for(ledger, case_id)
    assert completed == 34
    assert view["run_cost_usd"] == coord.fmt_cost(cost)
    assert board_calls(view) == completed
    # The total is the ledger sum rounded once, not a sum of rounded steps.
    steps_sum = sum(float(step["cost_usd"]) for step in view["steps"])
    assert abs(steps_sum - cost) < 0.0005
    # Internal accounting fields stay out of the API view.
    assert all(set(step) & case_state_mod.STEP_INTERNAL_FIELDS == set()
               for step in view["steps"])


@pytest.fixture()
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setitem(coord.AGENTS, "reader", fake_reader)
    monkeypatch.setitem(coord.AGENTS, "organizer", fake_organizer)
    monkeypatch.setitem(coord.AGENTS, "drafter", fake_drafter)
    return TestClient(app)


def _step(view, key):
    return next(step for step in view["steps"] if step["key"] == key)


def test_rerun_after_hold_keeps_billed_spend_and_calls(fake_env, monkeypatch):
    """A redraft after a revision HOLD adds to, never overwrites, the spend."""
    drafter_calls = []

    def _priced_drafter(case_id, draft_inputs, findings, meta_mode, run_id,
                        **kwargs):
        drafter_calls.append(1)
        if len(drafter_calls) <= 3:  # initial + 2 revisions, all failing
            out = {"sentences": [{"sentence_id": "s1", "type": "fact",
                                  "text_with_slots": "500만 원을 보냈습니다.",
                                  "ex_refs": []}], "model": "fake-bad"}
        else:
            out = fake_drafter(case_id, draft_inputs, findings, meta_mode,
                               run_id, **kwargs)
        out.update({"attempts": 1, "latency_ms": 1, "cost_usd": 0.01})
        return out

    monkeypatch.setitem(coord.AGENTS, "drafter", _priced_drafter)
    client = fake_env
    case_id = client.post("/api/cases/sample", json={"set": "kr"}).json()["case_id"]
    view = client.post(f"/api/cases/{case_id}/run", json={}).json()
    assert view["state"] == "CHECKPOINT_1"
    base_cost = float(view["run_cost_usd"])  # replayed SAM calls
    base_calls = board_calls(view)
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    client.put(f"/api/cases/{case_id}/facts", json=facts)
    view = client.post(f"/api/cases/{case_id}/run", json={}).json()
    assert view["state"] == "HOLD"
    assert _step(view, "drafting")["cost_usd"] == "0.0300"
    assert _step(view, "drafting")["attempts"] == 3
    # The drafter spend sits on drafting only (it was counted twice).
    assert _step(view, "verifying")["cost_usd"] == "0"
    assert float(view["run_cost_usd"]) == pytest.approx(base_cost + 0.03)
    assert board_calls(view) == base_calls + 3

    assert client.put(f"/api/cases/{case_id}/facts", json=facts).status_code == 200
    view = client.post(f"/api/cases/{case_id}/run", json={}).json()
    assert view["state"] == "DRAFT_APPROVAL", view
    assert len(drafter_calls) == 4
    assert _step(view, "drafting")["cost_usd"] == "0.0400"
    assert _step(view, "drafting")["attempts"] == 4
    assert float(view["run_cost_usd"]) == pytest.approx(base_cost + 0.04)
    assert board_calls(view) == base_calls + 4


def test_failed_reading_calls_stay_on_board(fake_env, monkeypatch):
    def _one_fails(case_id, evidence, evidence_path, preview_size, meta_mode,
                   run_id, **kwargs):
        if evidence["ex_id"] == "EX2":
            exc = AgentSchemaError("cut twice")
            exc._spark_partial = {"cost_usd": 0.02, "latency_ms": 5,
                                  "attempts": 2}
            raise exc
        out = fake_reader(case_id, evidence, evidence_path, preview_size,
                          meta_mode, run_id, **kwargs)
        out["cost_usd"] = 0.01
        return out

    monkeypatch.setitem(coord.AGENTS, "reader", _one_fails)
    client = fake_env
    case_id = client.post("/api/cases/sample", json={"set": "kr"}).json()["case_id"]
    view = client.post(f"/api/cases/{case_id}/run", json={}).json()
    reading = _step(view, "reading")
    held = next(sub for sub in reading["substeps"] if sub["ex_id"] == "EX2")
    assert held["status"] == "hold"
    assert held["calls"] == 2
    # 4 good images at $0.01 + the failed evidence's two calls at $0.02.
    assert reading["cost_usd"] == "0.0600"


def test_step_rerun_folds_prior_substep_calls():
    step = case_state_mod.StepState(key="reading", model="m")
    step.substeps = [case_state_mod.SubStep(ex_id="EX1", status="hold", calls=2)]
    prior = coord._substep_calls(step)
    fresh = [case_state_mod.SubStep(ex_id="EX1", status="done", calls=1)]
    coord._fold_calls(fresh, prior)
    assert fresh[0].calls == 3


# --- 2. wrong-line masks on a dense receipt -----------------------------------------
ROWS = [
    ("Deposit date", "2026-05-01"), ("Time", "14:13 KST"),
    ("Sender", "Alex Kim (SAMPLE)"), ("Sender bank", "SAMPLE Bank"),
    ("Sender account", "000-034-791246"),
    ("Recipient", "Jordan Lee (SAMPLE)"),
    ("Recipient account", "000-012-480135"), ("Memo", "Repayment (part)"),
]
ACCOUNTS = ("000-034-791246", "000-012-480135")
PITCH = 64
WIDTH, HEIGHT = 1080, 1000


def _dense_receipt(tmp_path: Path):
    """Right-aligned values, one line every 64px (the failing layout)."""
    font = ImageFont.truetype(str(FONT), 30)
    image = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    boxes = {}
    for row, (label, value) in enumerate(ROWS):
        top = 300 + row * PITCH
        draw.text((56, top), label, font=font, fill=(100, 106, 120))
        bbox = draw.textbbox((0, 0), value, font=font)
        left = 1024 - (bbox[2] - bbox[0]) - bbox[0]
        draw.text((left, top), value, font=font, fill=(17, 24, 39))
        boxes[value] = [int(v) for v in draw.textbbox((left, top), value, font=font)]
    path = tmp_path / "receipt.png"
    image.save(path)
    return path, image, boxes


def _account_readings(boxes, offset):
    items = []
    for number, value in enumerate(ACCOUNTS, start=1):
        x1, y1, x2, y2 = boxes[value]
        items.append({
            "item_id": f"item{number}", "kind": "account_number",
            "text_verbatim": value,
            "box": {"x1": x1 - 30, "y1": y1 - 4 + offset, "x2": x2,
                    "y2": y2 + 4 + offset, "system": "pixel",
                    "ref_w": WIDTH, "ref_h": HEIGHT}})
    return [{"ex_id": "EX4", "items": items}]


def _run_privacy(tmp_path, path, readings):
    record = SimpleNamespace(ex_id="EX4", label="갑 제4호증", kind="image",
                             status="ok", sha256="", stored_name="")
    segments = [{"ex_id": "EX4", "objects": [], "status": "not_found"}]
    return privacy_mod.run_privacy(
        "case_000000000000", [record], readings, segments, {"EX4": path},
        {"EX4": (WIDTH, HEIGHT)}, tmp_path)


def test_glyph_signature_tells_number_from_text_line(tmp_path):
    _, image, boxes = _dense_receipt(tmp_path)
    ink = redact_mod.build_ink_mask(image)
    want = redact_mod.text_signature("000-034-791246")
    assert want == "DDDSDDDSDDDDDD"
    for value in ACCOUNTS:
        assert redact_mod.pii_line_matches(ink, boxes[value], "000-034-791246")
    for value in ("SAMPLE Bank", "Jordan Lee (SAMPLE)", "2026-05-01",
                  "14:13 KST"):
        assert not redact_mod.pii_line_matches(
            ink, boxes[value], "000-034-791246"), value
    # Too few digits to confirm anything.
    assert not redact_mod.signature_matches("DDD", "DDD")
    # One merged digit pair is tolerated; a wrong group shape is not.
    assert redact_mod.signature_matches("DDSDDDSDDDDDD", want)
    assert not redact_mod.signature_matches("DDDDDDDXXD", want)


def test_aligned_reader_boxes_mask_without_review(tmp_path):
    path, _, boxes = _dense_receipt(tmp_path)
    out = _run_privacy(tmp_path, path, _account_readings(boxes, 0))
    assert [entry["needs_review"] for entry in out["plan"]] == [False, False]
    for entry, value in zip(out["plan"], ACCOUNTS):
        mask = entry["mask_box"]
        assert mask["y1"] <= boxes[value][1] and mask["y2"] >= boxes[value][3]
    assert out["leak_check"] == {"status": "pass", "findings": []}
    assert out["previews"][0]["needs_review"] is False


def test_reader_box_one_line_up_is_needs_review(tmp_path):
    """The live failure: the snap stays on the line above the number."""
    path, _, boxes = _dense_receipt(tmp_path)
    readings = _account_readings(boxes, -PITCH)
    plan = privacy_mod.build_plan(
        readings, [], {"EX4": (WIDTH, HEIGHT)},
        {"EX4": Image.open(path).convert("RGB")})
    for entry, value in zip(plan, ACCOUNTS):
        # The mask sits on another line ...
        assert entry["mask_box"]["y2"] < boxes[value][1]
        # ... so it is never a silent pass.
        assert entry["needs_review"] is True
        assert redact_mod.LINE_MATCH_REVIEW_REASON in entry["reason"]
    out = _run_privacy(tmp_path, path, readings)
    preview = out["previews"][0]
    assert preview["status"] == "redacted"
    assert preview["needs_review"] is True
    # Stronger leak check: the real numbers are still visible.
    unmasked = [f for f in out["leak_check"]["findings"]
                if f["message"] == redact_mod.UNMASKED_LINE_REASON]
    assert {f["item_id"] for f in unmasked} == {"item1", "item2"}
    assert all(f.get("warning") for f in unmasked)


def test_reader_box_one_line_down_is_needs_review(tmp_path):
    path, _, boxes = _dense_receipt(tmp_path)
    out = _run_privacy(tmp_path, path, _account_readings(boxes, PITCH))
    assert all(entry["needs_review"] for entry in out["plan"])
    assert out["previews"][0]["needs_review"] is True


@pytest.mark.parametrize("offset", [-PITCH // 2, -20])
def test_snap_of_half_a_line_is_needs_review(tmp_path, offset):
    path, _, boxes = _dense_receipt(tmp_path)
    out = _run_privacy(tmp_path, path, _account_readings(boxes, offset))
    for entry in out["plan"]:
        assert entry["needs_review"] is True
        assert redact_mod.LINE_SHIFT_REVIEW_REASON in entry["reason"]
    assert out["previews"][0]["needs_review"] is True


def test_line_shift_rule():
    assert not redact_mod.line_shift_too_far([0, 100, 10, 132], [0, 105, 10, 129])
    assert redact_mod.line_shift_too_far([0, 100, 10, 132], [0, 120, 10, 144])


def test_leak_check_finds_visible_number_off_the_mask(tmp_path):
    path, image, boxes = _dense_receipt(tmp_path)
    value = ACCOUNTS[0]
    item = {"ex_id": "EX4", "item_id": "item1", "box": boxes[value],
            "text": value}
    wrong = boxes["SAMPLE Bank"]
    right = boxes[value]
    # The other account (128px below, inside the search window) is masked
    # in both cases; an unmasked one would be flagged too.
    other = boxes[ACCOUNTS[1]]
    for mask_box, flagged in ((wrong, True), (right, False)):
        red = image.copy()
        plan = []
        for number, box in enumerate((mask_box, other), start=1):
            ImageDraw.Draw(red).rectangle(
                [box[0], box[1], box[2] - 1, box[3] - 1], fill=(0, 0, 0))
            plan.append({"ex_id": "EX4", "item_id": f"item{number}",
                         "kind": "account_number",
                         "mask_box": {"x1": box[0], "y1": box[1],
                                      "x2": box[2], "y2": box[3]}})
        red_path = tmp_path / "red.png"
        red.save(red_path)
        checked = redact_mod.check_leak(path, red_path, plan,
                                        pii_items=[item])
        assert checked["status"] == "pass"
        hit = any(f["message"] == redact_mod.UNMASKED_LINE_REASON
                  for f in checked["findings"])
        assert hit is flagged


# --- 3. repeated citations ------------------------------------------------------
def test_render_sentence_collapses_repeated_cite():
    out = deps.render_sentence("돈을 보냈습니다[[EX:1]][[EX:1]]", {}, {})
    assert out == "돈을 보냈습니다 [갑 제1호증]."
    out = deps.render_sentence("돈을 보냈습니다. [[EX:1]] [[EX:1]] [[EX:4]]", {}, {})
    assert out == "돈을 보냈습니다 [갑 제1호증] [갑 제4호증]."
    # Different exhibits, or one cited apart, stay as written.
    out = deps.render_sentence("A [[EX:1]] B[[EX:1]]", {}, {})
    assert out.count("[갑 제1호증]") == 2


def test_collapse_repeated_cites_both_forms():
    collapse = pdf_compiler_mod.collapse_repeated_cites
    assert collapse("했습니다(갑 제1호증)(갑 제1호증).") == "했습니다(갑 제1호증)."
    assert collapse("[갑 제2호증] [갑 제2호증]") == "[갑 제2호증]"
    assert collapse("(갑 제1호증)(갑 제6호증)") == "(갑 제1호증)(갑 제6호증)"


def test_ecourt_fact_cites_an_exhibit_once():
    """The live sentence: quote cited mid-sentence and at the end."""
    rendered = deps.render_sentence(
        "{{debtor_name}}은 [[EX:1]] {{quote:EX1:item1}}라고 했습니다[[EX:1]]",
        {"debtor_name": "탁나루(SAMPLE)"},
        {"quote:EX1:item1": '"갚을게요."'})
    out = pdf_compiler_mod.format_ecourt_fact(f"다. {rendered}")
    assert out.endswith('라고 했습니다(갑 제1호증).'), out
    assert out.count("(갑 제1호증)") == 1
    two = pdf_compiler_mod.format_ecourt_fact(
        "나. 했습니다. [갑 제1호증] [갑 제6호증] [갑 제1호증]")
    assert two.endswith("(갑 제1호증)(갑 제6호증).")
