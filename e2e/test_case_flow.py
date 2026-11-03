"""M2b-fix1 case-flow E2E (pytest + Playwright, Chromium, 1920x1080).

Target is $E2E_BASE_URL when set (the real M2a backend); otherwise the stub
server in this folder is started on a free 127.0.0.1 port for the test.

The test never assumes model-chosen ids or counts: the confirmed-facts input
is computed from GET /review with the contract section 5 rule
(build_demo_confirmed_facts), sentences are found by [data-testid^=...]
locators, and the revision note is only checked when present. Visible values
(amounts, Korean state names, gate names) may change; assertions use
data-state / data-gate / data-status attributes.
"""

import json
import os
import re
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import expect

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

from stub_server import app as stub_app  # noqa: E402
from app.services.naming import check_text  # noqa: E402

ARTIFACTS = HERE / "artifacts"
CONFIRMED_EXAMPLE = ROOT / "specs" / "case-api-examples" / "confirmed_facts_kr.json"
KNOWN_ROLES = ("loan_transfer", "repayment", "other")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def base_url():
    env = os.environ.get("E2E_BASE_URL")
    if env:
        yield env.rstrip("/")
        return
    port = _free_port()
    config = uvicorn.Config(stub_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("stub server did not start")
    yield base
    server.should_exit = True
    thread.join(timeout=20)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
    }


def _ex_num(ex_id: str) -> int:
    return int(ex_id[2:])


def _item_num(item_id: str) -> int:
    m = re.search(r"\d+", item_id or "")
    return int(m.group()) if m else 0


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


def expected_confirmed_facts(review: dict, fallback: dict) -> dict:
    """Contract section 5 rule: review values, empty fields from fallback,
    roles from suggested_role, highlight = first repay_promise utterance in
    ex_id then item_id order, as_of 2026-06-01."""
    fields = {}
    for f in review["fields"]:
        name = f["field"]
        val = f["value"]
        if _is_empty(val) and name in fallback and not _is_empty(fallback[name]):
            fields[name] = fallback[name]
        else:
            fields[name] = val
    roles = {}
    for r in review["evidence_roles"]:
        suggested = r["suggested_role"]
        roles[r["ex_id"]] = suggested if suggested in KNOWN_ROLES else "other"
    promised = [u for u in review["utterances"] if "repay_promise" in (u["tags"] or [])]
    promised.sort(key=lambda u: (_ex_num(u["ex_id"]), _item_num(u["item_id"])))
    highlight = [f"{promised[0]['ex_id']}:{promised[0]['item_id']}"] if promised else []
    return {
        "fields": fields,
        "evidence_roles": roles,
        "highlight": highlight,
        "as_of": "2026-06-01",
    }


def settle_scroll(page) -> None:
    page.wait_for_function(
        """() => new Promise((resolve) => {
             let last = -1, stable = 0;
             const t = setInterval(() => {
               const y = window.scrollY;
               if (y === last) { stable += 1; if (stable >= 3) { clearInterval(t); resolve(true); } }
               else { stable = 0; last = y; }
             }, 100);
             setTimeout(() => { clearInterval(t); resolve(true); }, 3000);
           })"""
    )


class Steps:
    def __init__(self, page):
        self.page = page
        self.n = 0
        if os.environ.get("E2E_BASE_URL"):
            self.outdir = ARTIFACTS / "real"
        else:
            self.outdir = ARTIFACTS

    def shot(self, name: str) -> None:
        settle_scroll(self.page)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.n += 1
        self.page.screenshot(
            path=str(self.outdir / f"{self.n:02d}-{name}.png"), full_page=True
        )
        found = check_text(self.page.inner_text("body"))
        assert found == [], f"forbidden names at step {name}: {found}"


def expected_model_calls(case_view: dict) -> int:
    """M6 rule: reading counts non-skipped substeps, other model steps
    sum attempts."""
    total = 0
    for s in case_view.get("steps", []):
        if not s.get("model"):
            continue
        subs = s.get("substeps") or []
        if s["key"] == "reading" and subs:
            total += sum(1 for x in subs if x.get("status") != "skipped")
        else:
            total += int(s.get("attempts") or 0)
    return total


def test_case_flow(page, base_url):
    expect_stub = not os.environ.get("E2E_BASE_URL")
    steps = Steps(page)
    page.goto(base_url + "/", wait_until="networkidle")
    expect(page.get_by_test_id("offline-notice")).to_be_hidden()
    expect(page.locator("#app")).to_be_visible()

    # 1. sample load -> agent board -> CHECKPOINT_1
    page.get_by_test_id("load-sample").click()
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "CHECKPOINT_1", timeout=30000
    )
    if expect_stub:
        expect(page.get_by_test_id("stub-banner")).to_be_visible()
    else:
        expect(page.get_by_test_id("stub-banner")).to_be_hidden()
    expect(page.get_by_test_id("step-reading")).to_be_visible()
    expect(page.get_by_test_id("board-summary")).to_contain_text("Meta 모델 호출")
    if expect_stub:
        expect(page.get_by_test_id("replay-badge")).to_be_visible()
    # M6: board call count equals the rule computed from the case view.
    _case_id = page.get_by_test_id("case-id").inner_text().strip()
    _case_resp = page.request.get(f"{base_url}/api/cases/{_case_id}")
    assert _case_resp.ok
    _want_calls = expected_model_calls(_case_resp.json())
    _summary = page.get_by_test_id("board-summary").inner_text()
    _m = re.search(r"Meta 모델 호출 (\d+)회", _summary)
    assert _m, f"board summary shape changed: {_summary!r}"
    assert int(_m.group(1)) == _want_calls, (
        f"board shows {_m.group(1)} calls, case view gives {_want_calls}"
    )
    assert "(재생)" in _summary, f"replay marker missing: {_summary!r}"
    steps.shot("board")

    # 2. checkpoint 1: at least one reading box, then switch evidence
    page.locator(".reading-box").first.wait_for(state="visible", timeout=15000)
    assert page.locator(".reading-box").count() >= 1
    page.get_by_test_id("evidence-EX4").click()
    expect(page.get_by_test_id("viewer-title")).to_contain_text("갑 제4호증")
    expect(page.get_by_test_id("viewer-img")).to_be_visible()
    # M6: no raw null/JSON on screen; 6a cells hidden while endpoints 404.
    _body = page.inner_text("body")
    assert "null" not in _body, "raw null shown on screen"
    assert '{"' not in _body, "raw JSON shown on screen"
    expect(page.get_by_test_id("redaction-col")).to_be_hidden()
    expect(page.get_by_test_id("segment-legend")).to_be_hidden()
    steps.shot("checkpoint-evidence")

    # 3. fixed demo inputs computed from GET /review (contract section 5).
    case_id = page.get_by_test_id("case-id").inner_text().strip()
    resp = page.request.get(f"{base_url}/api/cases/{case_id}/review")
    assert resp.ok, f"GET /review failed: {resp.status}"
    review = resp.json()
    fallback = json.loads(CONFIRMED_EXAMPLE.read_text(encoding="utf-8"))[
        "fallback_fields"
    ]
    expected = expected_confirmed_facts(review, fallback)
    # M6: first repay_promise highlight is pre-checked (contract section 5).
    for h in expected["highlight"]:
        ex, item = h.split(":")
        expect(page.get_by_test_id(f"highlight-{ex}-{item}")).to_be_checked()
    # M6: conflicts render as label sentences, never raw JSON.
    _conf_text = page.get_by_test_id("conflict-list").inner_text()
    assert '{"' not in _conf_text
    _labels = {f["field"]: f["label"] for f in review["fields"]}
    for c in review.get("conflicts", []):
        if isinstance(c, dict):
            for fld in c.get("fields", []):
                assert _labels.get(fld, fld) in _conf_text, (
                    f"conflict label for {fld} missing: {_conf_text!r}"
                )
            assert (c.get("note") or "") in _conf_text
    # M6: null speakers render as bubble side or unknown, never "null".
    _utt_text = page.get_by_test_id("utterance-list").inner_text()
    assert "null" not in _utt_text
    if any(u.get("speaker") in (None, "null") for u in review.get("utterances", [])):
        assert ("화자 미상" in _utt_text) or ("말풍선" in _utt_text), _utt_text
    # M6: display hint only when it differs from the input value.
    if page.get_by_test_id("display-field-principal").count():
        expect(page.get_by_test_id("display-field-principal")).to_contain_text("5,000,000원")
    assert page.get_by_test_id("display-field-creditor_name").count() == 0
    for f in review["fields"]:
        name = f["field"]
        if name in ("repayments", "transaction_kind"):
            continue
        if _is_empty(f["value"]) and not _is_empty(expected["fields"][name]):
            page.get_by_test_id(f"field-{name}").fill(str(expected["fields"][name]))
    # M6: display-format amounts parse back to integers on confirm.
    page.get_by_test_id("field-principal").fill("5,000,000원")
    if isinstance(expected["fields"].get("repayments"), list):
        for i, row in enumerate(expected["fields"]["repayments"]):
            date_el = page.get_by_test_id(f"field-repayments-{i}-date")
            amount_el = page.get_by_test_id(f"field-repayments-{i}-amount")
            if date_el.count() and not (date_el.input_value() or "").strip():
                date_el.fill(row["date"])
            if amount_el.count() and not (amount_el.input_value() or "").strip():
                amount_el.fill(row["amount"])
    for ex, role in expected["evidence_roles"].items():
        expect(page.get_by_test_id(f"role-{ex}")).to_have_value(role)
    for h in expected["highlight"]:
        ex, item = h.split(":")
        page.get_by_test_id(f"highlight-{ex}-{item}").check()
    first_utt = page.locator("#utterance-list li").first
    assert first_utt.get_attribute("data-tags") is not None
    expect(page.get_by_test_id("asof")).to_have_value("2026-06-01")
    steps.shot("checkpoint-filled")

    # 4. confirm -> CALCULATING -> DRAFT_APPROVAL; PUT body must equal the
    # fixed input so replay matches.
    with page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith("/facts")
    ) as put_info:
        page.get_by_test_id("confirm-facts").click()
    put_body = json.loads(put_info.value.request.post_data)
    assert put_body == expected
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "DRAFT_APPROVAL", timeout=30000
    )
    expect(page.get_by_test_id("calc-section")).to_be_visible()
    expect(page.get_by_test_id("remaining-principal")).to_contain_text("4,014,383")
    expect(page.get_by_test_id("reference-total")).to_contain_text("4,031,430")
    steps.shot("calculation")

    # 5. drafts shown; slot source folded, edit box opens with "고치기".
    first_sentence = page.locator(".sentence").first
    expect(first_sentence).to_be_visible()
    rev = page.get_by_test_id("revision-rounds")
    if rev.is_visible():
        expect(rev).to_contain_text("문안 작성")
    fact = page.locator(".sentence[data-sentence-type='fact']").first
    if fact.count() == 0:
        fact = first_sentence
    sid = fact.get_attribute("data-testid").removeprefix("sentence-")
    expect(page.get_by_test_id(f"slots-{sid}")).to_be_hidden()
    expect(page.get_by_test_id(f"edit-{sid}")).to_be_hidden()
    page.get_by_test_id(f"edit-toggle-{sid}").click()
    expect(page.get_by_test_id(f"edit-{sid}")).to_be_visible()
    # M6: NAMING/DRAFT gates show Korean names when the backend returns them.
    _drafts_resp = page.request.get(f"{base_url}/api/cases/{case_id}/drafts")
    assert _drafts_resp.ok
    _gates = {g["gate"] for g in _drafts_resp.json().get("gate_results", [])}
    _gate_text = page.get_by_test_id("gate-summary").inner_text()
    if "NAMING" in _gates:
        assert "금지 표현 검사" in _gate_text, _gate_text
    if "DRAFT" in _gates:
        assert "문안 규칙 검사" in _gate_text, _gate_text
    steps.shot("drafts")

    # 6. G1a scene: digits outside slots are blocked.
    edit = page.get_by_test_id(f"edit-{sid}")
    original = edit.input_value()
    assert "{{" in original, "edit box should hold text_with_slots"
    edit.fill("500만 원을 보냈습니다.")
    with page.expect_response(
        lambda r: r.request.method == "PUT" and "/drafts" in r.url
    ):
        page.get_by_test_id(f"update-{sid}").click()
    findings = page.get_by_test_id(f"findings-{sid}")
    expect(findings.locator("[data-gate='G1a']")).to_be_visible(timeout=15000)
    expect(findings).to_have_attribute("data-status", "fail")
    expect(page.get_by_test_id(f"notice-{sid}")).to_be_visible()
    expect(page.get_by_test_id(f"approve-{sid}")).to_be_disabled()
    steps.shot("g1a-blocked")

    # 7. revert -> pass
    edit.fill(original)
    with page.expect_response(
        lambda r: r.request.method == "PUT" and "/drafts" in r.url
    ):
        page.get_by_test_id(f"update-{sid}").click()
    expect(findings).to_contain_text("지적 없음", timeout=15000)
    expect(findings).to_have_attribute("data-status", "pass")
    expect(page.get_by_test_id(f"approve-{sid}")).to_be_enabled()
    steps.shot("drafts-fixed")

    # 8. approve every sentence
    boxes = page.locator("input[data-testid^='approve-']")
    assert boxes.count() >= 1, "no sentence approve checkboxes"
    for i in range(boxes.count()):
        box = boxes.nth(i)
        if not box.is_checked():
            with page.expect_response(
                lambda r: r.request.method == "PUT" and "/drafts" in r.url
            ):
                box.check()
        expect(box).to_be_checked(timeout=15000)
    steps.shot("drafts-approved")

    # 9. continue -> package
    page.get_by_test_id("approve-continue").click()
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "CHECKPOINT_2", timeout=30000
    )
    expect(page.get_by_test_id("package-section")).to_be_visible()
    expect(page.get_by_test_id("file-content_proof.pdf")).to_be_visible()
    # M6: package gate line (G1b) shows when the backend returns gate_results.
    _pkg_resp = page.request.get(f"{base_url}/api/cases/{case_id}/package")
    assert _pkg_resp.ok
    if _pkg_resp.json().get("gate_results"):
        expect(page.get_by_test_id("pkg-gates")).to_be_visible()
        expect(page.get_by_test_id("pkg-gate-list")).to_contain_text("G1b")
    expect(page.get_by_test_id("claim-purpose")).to_contain_text("2026. 5. 2.")
    copy_btn = page.get_by_test_id("copy-claim-purpose")
    expect(copy_btn).to_be_visible()
    copy_btn.click()
    expect(copy_btn).to_contain_text("복사 완료", timeout=5000)
    steps.shot("package")

    # 10. delete case
    page.get_by_test_id("delete-case").click()
    expect(page.get_by_test_id("board-section")).to_be_hidden(timeout=15000)
    expect(page.get_by_test_id("status-line")).to_contain_text("사건을 삭제했습니다.")
    steps.shot("deleted")


def test_m6_redaction_segments_show(page, base_url):
    """M6 task 6 show-path: mocked 6a responses render next to the original,
    hide per evidence without data, and mocked exhibits/G1b render."""
    steps = Steps(page)

    def _redactions(route):
        m = re.search(r"/api/cases/([^/]+)/redactions", route.request.url)
        cid = m.group(1) if m else "case_x"
        body = {
            "plan": [],
            "previews": [
                {
                    "ex_id": "EX1",
                    "url": f"{base_url}/api/cases/{cid}/evidence/EX1/preview",
                }
            ],
            "leak_check": {"status": "pass", "findings": []},
        }
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        )

    def _segments(route):
        body = [
            {
                "ex_id": "EX1",
                "model": "sam-3.1",
                "objects": [
                    {
                        "target": "face",
                        "source": "box",
                        "box": {
                            "x1": 10,
                            "y1": 10,
                            "x2": 100,
                            "y2": 100,
                            "system": "pixel",
                            "ref_w": 640,
                            "ref_h": 960,
                        },
                        "score": 0.9,
                        "mask_url": None,
                    }
                ],
                "status": "ok",
            }
        ]
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        )

    def _package(route):
        body = {
            "files": [
                {
                    "name": "content_proof.pdf",
                    "label": "내용증명",
                    "url": "/fake/content_proof.pdf",
                },
                {"name": "exhibits.pdf", "label": "갑호증", "url": "/fake/exhibits.pdf"},
                {
                    "name": "evidence_list.pdf",
                    "label": "증거 목록",
                    "url": "/fake/evidence_list.pdf",
                },
            ],
            "ecourt": {
                "claim_purpose": "지급하라.",
                "claim_cause_payment_order": "1. 사실.",
            },
            "notices": {"notice_ko": "안내", "disclaimer_ko": "면책"},
            "gate_results": [{"gate": "G1b", "status": "pass", "findings": []}],
        }
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        )

    page.route("**/api/cases/*/redactions", _redactions)
    page.route("**/api/cases/*/segments", _segments)
    page.route("**/api/cases/*/package", _package)

    page.goto(base_url + "/", wait_until="networkidle")
    page.get_by_test_id("load-sample").click()
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "CHECKPOINT_1", timeout=30000
    )
    expect(page.get_by_test_id("redaction-col")).to_be_visible()
    expect(page.get_by_test_id("redaction-img")).to_be_visible()
    expect(page.get_by_test_id("segment-legend")).to_be_visible()
    assert page.locator(".segment-box").count() >= 1
    steps.shot("m6-6a-shown")
    page.get_by_test_id("evidence-EX4").click()
    expect(page.get_by_test_id("redaction-col")).to_be_hidden()
    expect(page.get_by_test_id("segment-legend")).to_be_hidden()
    page.get_by_test_id("evidence-EX1").click()
    expect(page.get_by_test_id("redaction-col")).to_be_visible()

    case_id = page.get_by_test_id("case-id").inner_text().strip()
    resp = page.request.get(f"{base_url}/api/cases/{case_id}/review")
    assert resp.ok
    review = resp.json()
    fallback = json.loads(CONFIRMED_EXAMPLE.read_text(encoding="utf-8"))[
        "fallback_fields"
    ]
    expected = expected_confirmed_facts(review, fallback)
    for f in review["fields"]:
        name = f["field"]
        if name in ("repayments", "transaction_kind"):
            continue
        if _is_empty(f["value"]) and not _is_empty(expected["fields"][name]):
            page.get_by_test_id(f"field-{name}").fill(str(expected["fields"][name]))
    if isinstance(expected["fields"].get("repayments"), list):
        for i, row in enumerate(expected["fields"]["repayments"]):
            date_el = page.get_by_test_id(f"field-repayments-{i}-date")
            amount_el = page.get_by_test_id(f"field-repayments-{i}-amount")
            if date_el.count() and not (date_el.input_value() or "").strip():
                date_el.fill(row["date"])
            if amount_el.count() and not (amount_el.input_value() or "").strip():
                amount_el.fill(row["amount"])
    for h in expected["highlight"]:
        ex, item = h.split(":")
        box = page.get_by_test_id(f"highlight-{ex}-{item}")
        if not box.is_checked():
            box.check()
    page.get_by_test_id("confirm-facts").click()
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "DRAFT_APPROVAL", timeout=30000
    )
    boxes = page.locator("input[data-testid^='approve-']")
    assert boxes.count() >= 1
    for i in range(boxes.count()):
        box = boxes.nth(i)
        if not box.is_checked():
            with page.expect_response(
                lambda r: r.request.method == "PUT" and "/drafts" in r.url
            ):
                box.check()
        expect(box).to_be_checked(timeout=15000)
    page.get_by_test_id("approve-continue").click()
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "CHECKPOINT_2", timeout=30000
    )
    expect(page.get_by_test_id("file-exhibits.pdf")).to_be_visible()
    expect(page.get_by_test_id("file-evidence_list.pdf")).to_be_visible()
    expect(page.get_by_test_id("pkg-gate-list")).to_contain_text("최종 서류 검사")
    steps.shot("m6-package-mocked")
    page.get_by_test_id("delete-case").click()
    expect(page.get_by_test_id("board-section")).to_be_hidden(timeout=15000)
