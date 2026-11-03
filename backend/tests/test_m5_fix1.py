"""M5-fix1 tests: K1-K11 (no live calls)."""

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
    TransactionKindEnum,
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
    case_id, package, _state = _run_to_package(case_env)
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
    amounts = final_check_mod.build_expected_amounts(SAMPLE_FIELDS, calc_json)
    dates = final_check_mod.build_expected_dates(SAMPLE_FIELDS, calc_json, "2026-06-01")
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


# --- K1: 14 single-doc manipulations (all fail) --------------------------------


def _tamper_14():
    """(doc, old, new, appended_extra) x 14; exactly one doc changes."""
    extra = "\n금 9,999,999원"
    return [
        ("content_proof.pdf", "4,014,383", "4,014,388", None),
        ("ecourt", "4,014,383", "4,014,388", None),
        ("evidence_list.pdf", "5,000,000", "5,000,001", None),
        ("exhibits.pdf", None, None, extra),
        ("content_proof.pdf", "2026. 3. 10.", "2026. 3. 11.", None),
        ("ecourt", "2026. 4. 10.", "2026. 4. 11.", None),
        ("evidence_list.pdf", "2026. 5. 1.", "2026. 5. 2.", None),
        ("content_proof.pdf", "서가온(SAMPLE)", "서가은(SAMPLE)", None),
        ("evidence_list.pdf", "탁나루(SAMPLE)", "탁나래(SAMPLE)", None),
        ("ecourt", None, None, extra),
        ("content_proof.pdf", None, None, extra),
        ("evidence_list.pdf", None, None, extra),
        ("content_proof.pdf", "2026. 4. 11.", "2026. 4. 12.", None),
        ("ecourt", "2026. 5. 2.", "2026. 5. 3.", None),
    ]


def test_k1_single_doc_tampers_all_fail(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    # Sanity: untampered per-doc check passes.
    gate = final_check_mod.check_g1b(amounts, dates, names, docs)
    assert gate.status == "pass", [f.message for f in gate.findings]
    cases = _tamper_14()
    assert len(cases) == 14
    for doc, old, new, appended in cases:
        tampered = dict(docs)
        if appended is not None:
            tampered[doc] = tampered[doc] + appended
        else:
            assert old in tampered[doc], (doc, old)
            tampered[doc] = tampered[doc].replace(old, new)
        gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
        assert gate.status == "fail", (doc, old, new)


# --- K2: multi-repayment flow passes -------------------------------------------


def test_k2_two_repayments_pass(case_env):
    reps = [
        {"date": "2026-05-01", "amount": "600000"},
        {"date": "2026-05-20", "amount": "400000"},
    ]
    case_id, package, _state = _run_to_package(
        case_env, with_redacted=True,
        facts_override={"repayments": reps},
        roles_override={"EX6": "repayment"},
    )
    gates = {entry["gate"]: entry for entry in package["gate_results"]}
    assert gates["G1b"]["status"] == "pass", gates["G1b"]["findings"]
    cause = package["ecourt"]["claim_cause_payment_order"]
    assert "2026. 5. 1." in cause and "2026. 5. 20." in cause
    assert "600,000원" in cause and "400,000원" in cause
    files = case_state_mod.files_dir(case_id)
    evidence_text = _norm(_pdf_text(files / "evidence_list.pdf"))
    assert "2026. 5. 1. 600,000원" in evidence_text
    assert "2026. 5. 20. 400,000원" in evidence_text


def test_k2_expected_uses_last_remaining_only():
    fields = dict(SAMPLE_FIELDS)
    fields["repayments"] = [
        {"date": "2026-05-01", "amount": "600000"},
        {"date": "2026-05-20", "amount": "400000"},
    ]
    loan_fact = deps.build_loan_fact(fields, SAMPLE_ROLES, [])
    calc_json = deps.calculation_to_json(deps.calculate_kr(loan_fact, date(2026, 6, 1)))
    amounts = final_check_mod.build_expected_amounts(fields, calc_json)
    assert "allocations[1].remaining_principal_after" in amounts
    assert "allocations[0].remaining_principal_after" not in amounts


# --- K3: redacted copies only --------------------------------------------------


def test_k3_discover_ignores_evidence_dir_user_files(case_env, tmp_path):
    _case_id, _package, state = _run_to_package(case_env)
    evidence_base = case_state_mod.evidence_dir(state.case_id)
    # User upload named redacted.png lands as EX1_redacted.png (must be ignored).
    decoy = evidence_base / "EX1_redacted.png"
    decoy.write_bytes(b"not-a-redacted-copy")
    found = packager_mod.discover_redacted_paths(state)
    assert "EX1" not in found
    files_base = case_state_mod.files_dir(state.case_id)
    real = files_base / "redacted_EX1.png"
    PILImage.new("RGB", (8, 8), (1, 2, 3)).save(real)
    found = packager_mod.discover_redacted_paths(state)
    assert found.get("EX1") == str(real)


def test_k3_missing_redacted_line_and_g1b_findings(case_env):
    case_id, package, state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    exhibits = files / "exhibits.pdf"
    reader = PdfReader(str(exhibits))
    for record in sorted(state.evidence, key=lambda r: deps.ex_num(r.ex_id)):
        if record.kind not in ("image", "pdf"):
            continue
        position = deps.ex_num(record.ex_id)
        text = _norm(reader.pages[position].extract_text() or "")
        assert exhibit_bundle_mod.MISSING_REDACTED_LINE in text
        assert len(reader.pages[position].images) == 0
    gates = {entry["gate"]: entry for entry in package["gate_results"]}
    assert gates["G1b"]["status"] == "fail"
    joined = " ".join(
        f"{entry.get('field', '')} {entry.get('message', '')}"
        for entry in gates["G1b"]["findings"]
    )
    for ex_id in ("EX1", "EX2", "EX4", "EX5", "EX6"):
        assert ex_id in joined


def test_k3_original_bytes_never_enter_bundle(case_env):
    case_id, _package, state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    blob = (files / "exhibits.pdf").read_bytes()
    evidence_base = case_state_mod.evidence_dir(case_id)
    for record in state.evidence:
        if record.kind not in ("image", "pdf"):
            continue
        stored = evidence_base / record.stored_name
        if stored.exists():
            assert blob.count(stored.read_bytes()) == 0, record.ex_id


# --- K4: leak scan -----------------------------------------------------------------


def test_k4_sensitive_patterns():
    assert final_check_mod.find_sensitive_numbers("계좌 123-456789-01234") != []
    assert final_check_mod.find_sensitive_numbers("주민 900101-1234567") != []
    assert final_check_mod.find_sensitive_numbers("계좌 1234567890") != []
    assert final_check_mod.find_sensitive_numbers("계좌 1234 5678 9012") != []
    assert final_check_mod.find_sensitive_numbers("계좌 123–456789–01234") != []
    assert final_check_mod.find_sensitive_numbers("계좌 123-\n456789-01234") != []
    assert final_check_mod.find_sensitive_numbers("1234\n56789012") != []
    assert final_check_mod.find_sensitive_numbers("D:20261103150344+09'00'") == []
    assert final_check_mod.find_sensitive_numbers(
        "연락처 010-0000-0000", exclude=["010-0000-0000"]) == []


def test_k4_packaging_blocks_leak(case_env):
    _case_id, package, _state = _run_to_package(
        case_env, with_redacted=True,
        facts_override={"creditor_address": "서울시 계좌 123-456789-01234"},
    )
    gates = {entry["gate"]: entry for entry in package["gate_results"]}
    assert gates["G1b"]["status"] == "fail"
    assert any("계좌/주민번호" in entry.get("message", "")
               for entry in gates["G1b"]["findings"])


# --- K5: pre-write naming screen ------------------------------------------------------


def _build_state_with_facts(case_env, facts_patch):
    res = case_env.post("/api/cases/sample", json={"set": "kr"})
    case_id = res.json()["case_id"]
    case_env.post(f"/api/cases/{case_id}/run", json={})
    review = case_env.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    facts["fields"].update(facts_patch)
    case_env.put(f"/api/cases/{case_id}/facts", json=facts)
    case_env.post(f"/api/cases/{case_id}/run", json={})
    drafts = case_env.get(f"/api/cases/{case_id}/drafts").json()
    case_env.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": s["sentence_id"], "approved": True}
        for s in drafts["sentences"]]})
    return coord.get_case(case_id)


def test_k5_name_address_phone_block_before_writing(case_env):
    for patch in (
        {"creditor_name": "홍변호사"},
        {"creditor_address": "서울시 승소로 1"},
        {"creditor_phone": "변호사"},
    ):
        state = _build_state_with_facts(case_env, patch)
        with pytest.raises(packager_mod.NamingViolation):
            packager_mod.build_package(state)
        target = case_state_mod.files_dir(state.case_id)
        assert not (target / "content_proof.pdf").exists()
        assert not (target / "exhibits.pdf").exists()
        assert not (target / "evidence_list.pdf").exists()


# --- K6: shared wording, no copies -------------------------------------------------------


def test_k6_same_functions_and_no_copies():
    assert not hasattr(packager_mod, "generate_content_proof_pdf_fixed")
    assert not hasattr(packager_mod, "patch_repayment_sentence")
    assert packager_mod.kana_label(1) == pdf_compiler_mod.kana_label(1) == "가."
    assert packager_mod.kana_label(15) == pdf_compiler_mod.kana_label(15) == "(15)"


def test_k6_both_docs_share_repayment_numbers(case_env):
    case_id, package, _state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    proof = _norm(_pdf_text(files / "content_proof.pdf"))
    cause = package["ecourt"]["claim_cause_payment_order"]
    needle = "지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%) 14,383원"
    assert needle in proof
    assert needle in cause


# --- K7: repayment wording branches -------------------------------------------------


def test_k7_single_matches_brief_example():
    loan = _base_loan(repayments=[
        RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("1000000")),
    ])
    calc = calculate_kr(loan, date(2026, 6, 1))
    sentence = pdf_compiler_mod.build_repayment_sentence(loan, calc, style="ecourt")
    assert sentence == (
        "채권자는 2026. 5. 1. 채무자로부터 받은 1,000,000원을 그때까지의 "
        "지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%) 14,383원에 먼저 충당하고, "
        "나머지 985,617원을 원금에 충당하여 남은 원금은 4,014,383원입니다"
    )


def test_k7_multiple_joined_with_chungdanghago():
    loan = _base_loan(repayments=[
        RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("600000")),
        RepaymentRecord(payment_date=date(2026, 5, 20), amount=Decimal("400000")),
    ])
    calc = calculate_kr(loan, date(2026, 6, 1))
    sentence = pdf_compiler_mod.build_repayment_sentence(loan, calc, style="ecourt")
    # M5-fix2: later clauses drop the repeated subject.
    assert "충당하고, 채권자는" not in sentence
    assert "충당하고, 2026. 5. 20." in sentence
    assert sentence.count("채권자는") == 1
    assert "2026. 5. 1." in sentence and "2026. 5. 20." in sentence
    assert "600,000원" in sentence and "400,000원" in sentence


def test_k7_overpayment_states_remainder_only():
    loan = _base_loan(
        principal_amount=Decimal("1000000"),
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 2, 1),
        repayments=[RepaymentRecord(payment_date=date(2026, 2, 2), amount=Decimal("2000000"))],
    )
    calc = calculate_kr(loan, date(2026, 3, 1))
    assert calc.remaining_principal == Decimal("0")
    assert calc.overpayment_amount > 0
    sentence = pdf_compiler_mod.build_repayment_sentence(loan, calc, style="ecourt")
    # M5-fix2: overpayment is stated as a fact (no "원금을 모두 갚고").
    assert "받은 돈이 원금과 지연손해금을 넘어" in sentence
    assert "이 더 들어왔습니다" in sentence
    assert "남은 원금은" not in sentence
    assert "원금을 모두 갚고" not in sentence


def test_k7_less_than_interest_partial_charge():
    loan = _base_loan(repayments=[
        RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("10000")),
    ])
    calc = calculate_kr(loan, date(2026, 6, 1))
    sentence = pdf_compiler_mod.build_repayment_sentence(loan, calc, style="ecourt")
    assert "14,383원 중 10,000원" in sentence
    assert "남은 원금은 5,000,000원" in sentence


def test_k7_agreed_labels_split_by_due_date():
    pre = _base_loan(
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 6, 30),
        agreed_interest_rate=Decimal("12"),
        repayments=[RepaymentRecord(payment_date=date(2026, 3, 1), amount=Decimal("500000"))],
    )
    pre_sentence = pdf_compiler_mod.build_repayment_sentence(
        pre, calculate_kr(pre, date(2026, 10, 31)), style="ecourt")
    assert "약정이자(" in pre_sentence
    assert "지연손해금" not in pre_sentence
    post = _base_loan(
        agreed_interest_rate=Decimal("12"),
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("1000000"))],
    )
    post_sentence = pdf_compiler_mod.build_repayment_sentence(
        post, calculate_kr(post, date(2026, 6, 1)), style="ecourt")
    assert "약정이자" in post_sentence and "지연손해금" in post_sentence


def test_k7_sentence_placed_after_facts(case_env):
    _case_id, package, _state = _run_to_package(case_env)
    cause = package["ecourt"]["claim_cause_payment_order"]
    fact_pos = cause.find("다.")
    repay_pos = cause.find("채권자는 2026. 5. 1. 채무자로부터 받은")
    section3 = cause.find("3. 변제기 이후 상황")
    assert 0 <= fact_pos < repay_pos < section3


# --- K8: letter voice --------------------------------------------------------------------


def test_k8_content_proof_letter_style(case_env):
    case_id, _package, _state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    text = _pdf_text(files / "content_proof.pdf")
    normed = _norm(text)
    assert "[갑 제" not in text
    assert "(사용자 진술)" not in text
    assert "미기재" not in text
    assert "본인은 귀하에게" in normed
    assert "발신인은 귀하에게" not in normed


def test_k8_ecourt_citations_before_period(case_env):
    _case_id, package, _state = _run_to_package(case_env)
    cause = package["ecourt"]["claim_cause_payment_order"]
    assert "[갑 제" not in cause
    assert "(사용자 진술)" not in cause
    assert "(갑 제4호증)." in cause


# --- K9: evidence list --------------------------------------------------------------------


def test_k9_display_names_and_no_filenames(case_env):
    case_id, _package, _state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    text = _norm(_pdf_text(files / "evidence_list.pdf"))
    # M5-fix2: role/kind names only (sample has no loan_agreement role).
    for name in ("대화 화면 캡처", "대화 화면 녹화", "송금 기록 화면", "문서 사본"):
        assert name in text
    assert "송금확인증" not in text
    assert ".png" not in text and "chat_01" not in text
    for banned in ("사용자 지정", "발화", "입증"):
        assert banned not in text


def test_k9_created_only_confirmed_no_guessing():
    confirmed = {
        "fields": dict(SAMPLE_FIELDS),
        "evidence_roles": dict(SAMPLE_ROLES),
        "highlight": [],
    }
    readings = [{"ex_id": "EX1", "items": [{"normalized": "2026-03-09"}]}]
    ex1 = {"ex_id": "EX1", "kind": "image", "filename": "chat_01.png"}
    ex6 = {"ex_id": "EX6", "kind": "pdf", "filename": "iou.pdf"}
    assert exhibit_bundle_mod.evidence_created_label(ex1, confirmed, readings) == "-"
    assert exhibit_bundle_mod.evidence_created_label(ex6, confirmed, readings) == "-"
    assert exhibit_bundle_mod.evidence_summary(ex1, confirmed) == "대화 기록"
    # M5-fix2: role other + pdf is 문서 사본 (filename iou must not guess 차용증).
    assert exhibit_bundle_mod.evidence_summary(ex6, confirmed) == "문서 사본"
    assert exhibit_bundle_mod.evidence_display_name(ex6, confirmed) == "문서 사본"


def test_k9_repayment_rows_show_own_payment_only():
    confirmed = {
        "fields": {
            **SAMPLE_FIELDS,
            "repayments": [
                {"date": "2026-05-01", "amount": "600000"},
                {"date": "2026-05-20", "amount": "400000"},
            ],
        },
        "evidence_roles": {**SAMPLE_ROLES, "EX6": "repayment"},
    }
    ex5 = {"ex_id": "EX5", "kind": "image", "filename": "transfer_repay.png"}
    ex6 = {"ex_id": "EX6", "kind": "pdf", "filename": "iou.pdf"}
    first = exhibit_bundle_mod.evidence_summary(ex5, confirmed)
    second = exhibit_bundle_mod.evidence_summary(ex6, confirmed)
    assert "600,000원" in first and "400,000원" not in first
    assert "400,000원" in second and "600,000원" not in second


# --- K10: tall images -----------------------------------------------------------------------


def _tall_png(path: Path, width: int = 640, height: int = 2400) -> None:
    image = PILImage.new("RGB", (width, height), (255, 255, 255))
    image.save(path)


def test_k10_tall_image_splits_with_numbered_headers(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    tall = evidence_dir / "tall.png"
    _tall_png(tall)
    record = {
        "ex_id": "EX2", "label": "갑 제2호증", "filename": "chat_02_tall.png",
        "stored_name": tall.name, "sha256": "x" * 64, "kind": "image",
    }
    out = tmp_path / "exhibits.pdf"
    exhibit_bundle_mod.build_exhibits_pdf([record], evidence_dir, out, redacted={"EX2": tall})
    reader = PdfReader(str(out))
    assert len(reader.pages) == 1 + 3
    headers = [_norm(reader.pages[i].extract_text() or "") for i in (1, 2, 3)]
    assert "갑 제2호증 (1/3)" in headers[0]
    assert "갑 제2호증 (2/3)" in headers[1]
    assert "갑 제2호증 (3/3)" in headers[2]


# --- K11: polish -------------------------------------------------------------------------------


def test_k11_conclusion_names_remaining_and_no_gyeong(case_env):
    _case_id, package, _state = _run_to_package(case_env)
    cause = package["ecourt"]["claim_cause_payment_order"]
    assert "남은 원금 4,014,383원 및 지연손해금" in cause
    assert "위 대여원금" not in cause
    assert "2026. 3. 10.경" not in cause
    assert "채권자는 2026. 3. 10. 채무자에게" in cause


def test_k11_cover_carries_remove_guide(case_env):
    case_id, _package, _state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    cover = _norm(PdfReader(str(files / "exhibits.pdf")).pages[0].extract_text() or "")
    assert "법원에 낼 때는 이 쪽을 빼세요" in cover
