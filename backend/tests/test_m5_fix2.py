"""M5-fix2 tests: slot re-render, redacted check, names, G1b+, polish."""

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from PIL import Image as PILImage

from app.agents import case_state as case_state_mod
from app.agents import coordinator as coord
from app.agents import demo_inputs
from app.agents import deps
from app.agents import packager as packager_mod
from app.main import app
from app.schemas.loan_fact import (
    LoanFactSchema,
    PartyInfo,
    RepaymentRecord,
)
from app.services import exhibit_bundle as exhibit_bundle_mod
from app.services import final_check as final_check_mod
from app.services import pdf_compiler as pdf_compiler_mod
from app.services.verification_gate import calculate_kr

from test_case_contract import (  # noqa: F401
    fake_drafter,
    fake_organizer,
    fake_reader,
)
from test_m5_packaging import (
    SAMPLE_FIELDS,
    SAMPLE_ROLES,
    _make_redacted_dummies,
)


@pytest.fixture()
def case_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setenv("META_MODE", "replay")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setitem(coord.AGENTS, "reader", fake_reader)
    monkeypatch.setitem(coord.AGENTS, "organizer", fake_organizer)
    monkeypatch.setitem(coord.AGENTS, "drafter", fake_drafter)
    return TestClient(app)


def _run_to_package(client: TestClient, with_redacted: bool = False,
                    facts_override=None, roles_override=None):
    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    case_id = res.json()["case_id"]
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    if facts_override is not None:
        facts["fields"].update(facts_override)
    if roles_override is not None:
        facts["evidence_roles"].update(roles_override)
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.json()["state"] == "DRAFT_APPROVAL", res.text
    drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    approvals = {"sentences": [
        {"sentence_id": s["sentence_id"], "approved": True}
        for s in drafts["sentences"]]}
    res = client.put(f"/api/cases/{case_id}/drafts", json=approvals)
    assert all(s["approved"] for s in res.json()["sentences"]), res.text
    if with_redacted:
        _make_redacted_dummies(case_id)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.json()["state"] == "CHECKPOINT_2", res.text
    package = client.get(f"/api/cases/{case_id}/package").json()
    state = coord.get_case(case_id)
    return case_id, package, state


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _package_docs(case_env):
    case_id, package, _state = _run_to_package(case_env, with_redacted=True)
    files = case_state_mod.files_dir(case_id)
    return package, {
        "content_proof.pdf": _pdf_text(files / "content_proof.pdf"),
        "exhibits.pdf": _pdf_text(files / "exhibits.pdf"),
        "evidence_list.pdf": _pdf_text(files / "evidence_list.pdf"),
        "ecourt": (package["ecourt"]["claim_purpose"] + "\n"
                   + package["ecourt"]["claim_cause_payment_order"]),
    }


def _expected():
    loan_fact = deps.build_loan_fact(SAMPLE_FIELDS, SAMPLE_ROLES, [])
    calc = deps.calculate_kr(loan_fact, date(2026, 6, 1))
    calc_json = deps.calculation_to_json(calc)
    amounts = final_check_mod.build_expected_amounts(
        SAMPLE_FIELDS, calc_json, "2026-06-01")
    dates = final_check_mod.build_expected_dates(
        SAMPLE_FIELDS, calc_json, "2026-06-01")
    names = final_check_mod.build_expected_names(SAMPLE_FIELDS)
    return amounts, dates, names


def _base_loan(**kw):
    params = dict(
        creditor=PartyInfo(name="서가온(SAMPLE)"),
        debtor=PartyInfo(name="탁나루(SAMPLE)"),
        principal_amount=Decimal("5000000"),
        loan_date=date(2026, 3, 10),
        due_date=date(2026, 4, 10),
        repayments=[],
    )
    params.update(kw)
    return LoanFactSchema(**params)


# --- 1. slot re-render (josa + quote preservation) -------------------------------

_JOSA_SLOTS = (
    "{{creditor_name}}은 {{loan_date}} {{debtor_name}}에게 "
    "{{principal}}을 보냈습니다. [[EX:4]]"
)
_QUOTE_SLOTS = "{{debtor_name}}은 {{quote:EX1:item1}}라고 했습니다. [[EX:1]]"


def _josa_values(creditor: str, debtor: str):
    return {
        "creditor_name": creditor,
        "debtor_name": debtor,
        "principal": "5,000,000원",
        "loan_date": "2026. 3. 10.",
        "repaid_date": "2026. 5. 1.",
        "repaid_amount": "1,000,000원",
    }


def test_letter_render_josa_bonin_gwina():
    # 김하나(no 받침)/박민준(받침): letter must fit 본인/귀하, not the names.
    quotes = {"quote:EX1:item1": '"박민준이 김하나에게 빌려줘"'}
    letter_cred = packager_mod.render_sentence_for_style(
        _JOSA_SLOTS, _josa_values("김하나", "박민준"), quotes, "letter")
    assert letter_cred.startswith("본인은 2026. 3. 10. 귀하에게")
    assert "본인는" not in letter_cred and "귀하은" not in letter_cred
    letter_quote = packager_mod.render_sentence_for_style(
        _QUOTE_SLOTS, _josa_values("김하나", "박민준"), quotes, "letter")
    assert letter_quote.startswith('귀하는 "박민준이 김하나에게 빌려줘"')
    assert "귀하은" not in letter_quote
    # Quote original keeps both names verbatim.
    assert '"박민준이 김하나에게 빌려줘"' in letter_quote


def test_ecourt_render_josa_creditor_debtor():
    quotes = {"quote:EX1:item1": '"박민준이 김하나에게 빌려줘"'}
    ecourt = packager_mod.render_sentence_for_style(
        _JOSA_SLOTS, _josa_values("김하나", "박민준"), quotes, "ecourt")
    assert ecourt.startswith("채권자는 2026. 3. 10. 채무자에게")
    assert "채권자은" not in ecourt and "채무자은" not in ecourt
    ecourt_quote = packager_mod.render_sentence_for_style(
        _QUOTE_SLOTS, _josa_values("김하나", "박민준"), quotes, "ecourt")
    assert ecourt_quote.startswith('채무자는 "박민준이 김하나에게 빌려줘"')
    assert '"박민준이 김하나에게 빌려줘"' in ecourt_quote


def test_letter_format_does_not_touch_quotes():
    rendered = ('나. 귀하는 "박민준이 김하나에게 빌려줘"라고 했습니다. '
                '[갑 제1호증]')
    out = pdf_compiler_mod.format_letter_fact(rendered, "김하나", "박민준")
    assert '"박민준이 김하나에게 빌려줘"' in out
    assert "[갑 제" not in out
    assert out.endswith(".")


def test_replay_names_flow_to_docs(case_env):
    case_id, package, _state = _run_to_package(
        case_env,
        facts_override={"creditor_name": "김하나", "debtor_name": "박민준"},
    )
    files = case_state_mod.files_dir(case_id)
    proof = _norm(_pdf_text(files / "content_proof.pdf"))
    cause = package["ecourt"]["claim_cause_payment_order"]
    assert "본인은 2026. 3. 10. 귀하에게" in proof
    assert "귀하는 2026. 5. 1." in proof
    assert "본인는" not in proof and "귀하은" not in proof
    assert "채권자는 2026. 3. 10. 채무자에게" in cause
    assert "채무자는 2026. 5. 1." in cause
    # Quote original (sample reading) is untouched in both docs.
    assert "병원비로 500만 원이 필요해요" in proof
    assert "병원비로 500만 원이 필요해요" in cause


# --- 2. redacted verification ----------------------------------------------------

def test_identical_sha_excluded_as_not_redacted(case_env):
    case_id, _package, state = _run_to_package(case_env)
    evidence_base = case_state_mod.evidence_dir(case_id)
    files_base = case_state_mod.files_dir(case_id)
    record = next(r for r in state.evidence if r.ex_id == "EX1")
    original = (evidence_base / record.stored_name).read_bytes()
    (files_base / "redacted_EX1.png").write_bytes(original)
    valid, _needs, identical = packager_mod.get_redaction_status(
        coord.get_case(case_id))
    assert "EX1" not in valid
    assert "EX1" in identical
    # Bundle shows the missing line (no picture) for identical copies.
    out = files_base / "exhibits_identical.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        [r.model_dump() for r in state.evidence], evidence_base, out,
        redacted=valid, confirmed=state.confirmed_facts or {})
    reader = PdfReader(str(out))
    page1 = _norm(reader.pages[1].extract_text() or "")
    assert exhibit_bundle_mod.MISSING_REDACTED_LINE in page1
    assert len(reader.pages[1].images) == 0


def test_needs_review_blocked_until_confirmed(case_env):
    case_id, _package, state = _run_to_package(case_env)
    evidence_base = case_state_mod.evidence_dir(case_id)
    files_base = case_state_mod.files_dir(case_id)
    red = files_base / "redacted_EX4.png"
    PILImage.new("RGB", (16, 16), (9, 9, 9)).save(red)
    (files_base / "redactions.json").write_text(json.dumps({
        "plan": [],
        "previews": [{"ex_id": "EX4", "needs_review": True}],
        "leak_check": {"status": "pass", "findings": []},
    }), encoding="utf-8")
    valid, needs, _identical = packager_mod.get_redaction_status(
        coord.get_case(case_id))
    assert "EX4" not in valid and "EX4" in needs
    out = files_base / "exhibits_review.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        [r.model_dump() for r in state.evidence], evidence_base, out,
        redacted=valid, needs_review=needs,
        confirmed=state.confirmed_facts or {})
    reader = PdfReader(str(out))
    texts = [_norm(p.extract_text() or "") for p in reader.pages]
    assert any(exhibit_bundle_mod.NEEDS_REVIEW_LINE in t for t in texts)
    # User confirmation releases the same copy.
    confirmed = dict(coord.get_case(case_id).confirmed_facts or {})
    confirmed["redaction_confirmed"] = True
    st = coord.get_case(case_id)
    st.confirmed_facts = confirmed
    valid2, needs2, _ = packager_mod.get_redaction_status(st)
    assert valid2.get("EX4") == str(red)
    assert "EX4" not in needs2
    out2 = files_base / "exhibits_confirmed.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        [r.model_dump() for r in st.evidence], evidence_base, out2,
        redacted=valid2, needs_review=needs2, confirmed=confirmed)
    assert len(PdfReader(str(out2)).pages[4].images) == 1


def test_not_redacted_status_blocked(case_env):
    case_id, _package, _state = _run_to_package(case_env)
    files_base = case_state_mod.files_dir(case_id)
    red = files_base / "redacted_EX5.png"
    PILImage.new("RGB", (16, 16), (7, 8, 9)).save(red)
    (files_base / "redactions.json").write_text(json.dumps({
        "plan": [],
        "previews": [{"ex_id": "EX5", "status": "not_redacted"}],
        "leak_check": {"status": "pass", "findings": []},
    }), encoding="utf-8")
    valid, needs, _ = packager_mod.get_redaction_status(coord.get_case(case_id))
    assert "EX5" not in valid and "EX5" in needs


def test_needs_review_g1b_finding(case_env):
    case_id, _package, state = _run_to_package(case_env)
    files_base = case_state_mod.files_dir(case_id)
    for record in state.evidence:
        if record.kind in ("image", "pdf"):
            PILImage.new("RGB", (8, 8), (5, 5, 5)).save(
                files_base / f"redacted_{record.ex_id}.png")
    (files_base / "redactions.json").write_text(json.dumps({
        "plan": [],
        "previews": [{"ex_id": "EX1", "needs_review": True}],
        "leak_check": {"status": "pass", "findings": []},
    }), encoding="utf-8")
    package = packager_mod.build_package(coord.get_case(case_id))
    gates = {e["gate"]: e for e in package["gate_results"]}
    assert gates["G1b"]["status"] == "fail"
    joined = " ".join(e.get("message", "") for e in gates["G1b"]["findings"])
    assert "EX1" in joined and "가림 확인" in joined
    exhibits = _pdf_text(files_base / "exhibits.pdf")
    assert exhibit_bundle_mod.NEEDS_REVIEW_LINE in _norm(exhibits)


# --- 3. evidence names (role + kind only) ----------------------------------------

def test_display_names_ignore_filenames():
    cases = [
        ({"ex_id": "EX4", "kind": "image", "filename": "iou_loan.png"},
         {"EX4": "loan_transfer"}, "송금 기록 화면"),
        ({"ex_id": "EX5", "kind": "image", "filename": "transfer.png"},
         {"EX5": "repayment"}, "송금 기록 화면"),
        ({"ex_id": "EX1", "kind": "image", "filename": "iou_chat.png"},
         {"EX1": "other"}, "대화 화면 캡처"),
        ({"ex_id": "EX3", "kind": "video", "filename": "loan.mp4"},
         {"EX3": "repayment"}, "대화 화면 녹화"),
        ({"ex_id": "EX6", "kind": "pdf", "filename": "scan.pdf"},
         {"EX6": "loan_agreement"}, "차용증"),
        ({"ex_id": "EX6", "kind": "image", "filename": "scan.png"},
         {"EX6": "loan_agreement"}, "차용증"),
        ({"ex_id": "EX6", "kind": "pdf", "filename": "iou.pdf"},
         {"EX6": "other"}, "문서 사본"),
        ({"ex_id": "EX4", "kind": "pdf", "filename": "transfer.pdf"},
         {"EX4": "loan_transfer"}, "문서 사본"),
    ]
    for record, roles, want in cases:
        confirmed = {"fields": {}, "evidence_roles": dict(roles)}
        assert exhibit_bundle_mod.evidence_display_name(record, confirmed) == want
    # Summaries also stop guessing from filenames.
    other_pdf = {"ex_id": "EX6", "kind": "pdf", "filename": "iou.pdf"}
    assert exhibit_bundle_mod.evidence_summary(
        other_pdf, {"fields": dict(SAMPLE_FIELDS),
                    "evidence_roles": dict(SAMPLE_ROLES)}) == "문서 사본"
    agree = {"ex_id": "EX6", "kind": "pdf", "filename": "scan.pdf"}
    assert exhibit_bundle_mod.evidence_summary(
        agree, {"fields": dict(SAMPLE_FIELDS),
                "evidence_roles": {**SAMPLE_ROLES, "EX6": "loan_agreement"}}) == "차용증 사본"


def test_cover_uses_same_display_names(case_env):
    case_id, _package, _state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    cover = _norm(PdfReader(str(files / "exhibits.pdf")).pages[0].extract_text() or "")
    assert "송금 기록 화면" in cover
    assert "문서 사본" in cover
    assert "transfer_loan.png" not in cover
    assert "iou.pdf" not in cover


# --- 4. G1b reinforcement ----------------------------------------------------------

def test_ecourt_names_accept_role_terms(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    assert "서가온(SAMPLE)" not in docs["ecourt"]
    assert "채권자" in docs["ecourt"] and "채무자" in docs["ecourt"]
    gate = final_check_mod.check_g1b(amounts, dates, names, docs)
    assert gate.status == "pass", [f.message for f in gate.findings]
    tampered = dict(docs)
    tampered["ecourt"] = tampered["ecourt"].replace("채권자", "XXXX").replace(
        "채무자", "YYYY")
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any("creditor_name" in f.field or "debtor_name" in f.field
               for f in gate.findings)


def test_loan_due_swap_inside_one_doc_fails(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    loan_dot, due_dot = "2026. 3. 10.", "2026. 4. 10."
    for target in ("content_proof.pdf", "ecourt"):
        tampered = dict(docs)
        blob = tampered[target]
        assert loan_dot in blob and due_dot in blob
        blob = blob.replace(loan_dot, "@@LOAN@@")
        blob = blob.replace(due_dot, loan_dot)
        blob = blob.replace("@@LOAN@@", due_dot)
        tampered[target] = blob
        gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
        assert gate.status == "fail", target
        assert any("뒤바뀜" in f.message for f in gate.findings), target


def test_single_value_deletion_in_one_doc_fails(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    tampered = dict(docs)
    assert "2026. 3. 10." in tampered["content_proof.pdf"]
    tampered["content_proof.pdf"] = tampered["content_proof.pdf"].replace(
        "2026. 3. 10.", "")
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any(f.field == "loan_date" for f in gate.findings)


# --- 5. polish ---------------------------------------------------------------------

def test_ecourt_multi_cites_merge_without_leftover_dot():
    raw = ('나. 채무자는 "네, 갚을게요."라고 했습니다. '
           '[갑 제1호증] [갑 제6호증]')
    out = pdf_compiler_mod.format_ecourt_fact(raw)
    assert out.endswith("(갑 제1호증)(갑 제6호증).")
    assert ").(" not in out
    single = pdf_compiler_mod.format_ecourt_fact(
        "가. 채권자는 2026. 3. 10. 채무자에게 5,000,000원을 보냈습니다. [갑 제4호증]")
    assert single.endswith("(갑 제4호증).")


def test_user_sentence_keeps_final_period():
    letter = pdf_compiler_mod.format_letter_fact("라. 그 뒤로 남은 돈을 받지 못했습니다 [[USER]]")
    ecourt = pdf_compiler_mod.format_ecourt_fact("라. 그 뒤로 남은 돈을 받지 못했습니다 [[USER]]")
    assert letter.endswith(".")
    assert ecourt.endswith(".")
    assert "[[USER]]" not in letter and "(사용자 진술)" not in letter


def test_post_as_of_repayment_excluded_from_expected():
    fields = dict(SAMPLE_FIELDS)
    fields["repayments"] = [
        {"date": "2026-05-01", "amount": "1000000"},
        {"date": "2026-07-01", "amount": "500000"},
    ]
    loan_fact = deps.build_loan_fact(fields, SAMPLE_ROLES, [])
    calc_json = deps.calculation_to_json(
        deps.calculate_kr(loan_fact, date(2026, 6, 1)))
    assert len(calc_json["allocations"]) == 1
    amounts = final_check_mod.build_expected_amounts(fields, calc_json, "2026-06-01")
    dates = final_check_mod.build_expected_dates(fields, calc_json, "2026-06-01")
    assert "repayments[0].amount" in amounts
    assert "repayments[1].amount" not in amounts
    assert "repayments[0].date" in dates
    assert "repayments[1].date" not in dates
    assert 500000 not in set(amounts.values())
    assert "2026-07-01" not in set(dates.values())


def test_post_as_of_flow_still_passes(case_env):
    _case_id, package, _state = _run_to_package(
        case_env, with_redacted=True,
        facts_override={"repayments": [
            {"date": "2026-05-01", "amount": "1000000"},
            {"date": "2026-07-01", "amount": "500000"},
        ]},
    )
    gates = {e["gate"]: e for e in package["gate_results"]}
    assert gates["G1b"]["status"] == "pass", gates["G1b"]["findings"]
    assert "500,000원" not in package["ecourt"]["claim_cause_payment_order"]
