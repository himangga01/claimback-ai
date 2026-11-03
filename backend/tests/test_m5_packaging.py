"""M5 packaging tests: exhibits, evidence list, G1b (no live calls)."""

import hashlib
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
from app.services import exhibit_bundle as exhibit_bundle_mod
from app.services import final_check as final_check_mod
from app.services.naming import DISCLAIMER_KO, NOTICE_KO

from test_case_contract import (  # noqa: F401  (shared fakes)
    fake_drafter,
    fake_organizer,
    fake_reader,
)


SAMPLE_FIELDS = {
    "creditor_name": "서가온(SAMPLE)",
    "creditor_address": "서울특별시 샘플구 데모로 0",
    "creditor_phone": "010-0000-0000",
    "debtor_name": "탁나루(SAMPLE)",
    "debtor_address": "경기도 샘플시 데모동 0",
    "principal": "5000000",
    "loan_date": "2026-03-10",
    "due_date": "2026-04-10",
    "interest_rate": None,
    "transaction_kind": "civil",
    "repayments": [{"date": "2026-05-01", "amount": "1000000"}],
}
SAMPLE_ROLES = {
    "EX1": "other", "EX2": "other", "EX3": "other",
    "EX4": "loan_transfer", "EX5": "repayment", "EX6": "other",
}

LEAK_EXCLUDE_PHONES = ("010-0000-0000",)


@pytest.fixture()
def case_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setenv("META_MODE", "replay")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setitem(coord.AGENTS, "reader", fake_reader)
    monkeypatch.setitem(coord.AGENTS, "organizer", fake_organizer)
    monkeypatch.setitem(coord.AGENTS, "drafter", fake_drafter)
    return TestClient(app)


def _make_redacted_dummies(case_id: str) -> None:
    """Create files/redacted_EXn.png dummies (K3: only these count)."""
    target = case_state_mod.files_dir(case_id)
    target.mkdir(parents=True, exist_ok=True)
    state = coord.get_case(case_id)
    for record in state.evidence:
        if record.kind not in ("image", "pdf"):
            continue
        path = target / f"redacted_{record.ex_id}.png"
        if not path.exists():
            image = PILImage.new("RGB", (32, 32), (200, 200, 200))
            image.save(path)


def _run_to_package(client: TestClient, with_redacted: bool = False):
    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    case_id = res.json()["case_id"]
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
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


def _pdf_metadata_text(path: Path) -> str:
    reader = PdfReader(str(path))
    metadata = reader.metadata
    if not metadata:
        return ""
    return "\n".join(str(value) for value in metadata.values() if value is not None)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _calc_dict():
    loan_fact = deps.build_loan_fact(SAMPLE_FIELDS, SAMPLE_ROLES, [])
    calc = deps.calculate_kr(loan_fact, date(2026, 6, 1))
    return deps.calculation_to_json(calc), calc


# --- 4a wording -----------------------------------------------------------------


def test_repayment_sentence_uses_allocations_not_hardcoded():
    _, calc = _calc_dict()
    sentence = packager_mod.build_repayment_sentence(
        calc.allocations, calc.remaining_principal)
    assert "14,383원" in sentence
    assert "985,617원" in sentence
    assert "4,014,383원" in sentence
    assert "2026. 5. 1." in sentence
    assert "지연손해금" in sentence and "충당" in sentence
    # Different allocation values flow into the sentence (no literals).
    other = [dict(entry) for entry in deps.calculation_to_json(calc)["allocations"]]
    other[0]["applied_to_interest"] = "100"
    other[0]["applied_to_principal"] = "999900"
    other[0]["remaining_principal_after"] = "4000100"
    rewritten = packager_mod.build_repayment_sentence(other, Decimal("4000100"))
    assert "100원" in rewritten and "999,900원" in rewritten
    assert "4,000,100원" in rewritten
    assert "14,383" not in rewritten


def test_approval_sentences_use_kana_not_big_numbers():
    state = case_state_mod.CaseState(case_id="case_0123456789ab")
    state.drafts = {"sentences": [
        {"rendered_text": "첫 문장"},
        {"rendered_text": "둘째 문장"},
        {"rendered_text": "셋째 문장"},
        {"rendered_text": "넷째 문장"},
    ]}
    lines = packager_mod.approved_fact_sentences(state)
    assert [line.split(" ", 1)[0] for line in lines] == ["가.", "나.", "다.", "라."]
    for line in lines:
        assert not re.match(r"^[1-9]\.\s", line)


def test_package_texts_carry_allocation_sentence(case_env):
    _case_id, package, _state = _run_to_package(case_env)
    cause = package["ecourt"]["claim_cause_payment_order"]
    # M5-fix1 K7: detailed wording with period/rate (same source as content proof).
    assert "지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%) 14,383원" in cause
    assert "985,617원" in cause and "4,014,383원" in cause
    assert "채권자는 2026. 5. 1. 채무자로부터 받은 1,000,000원" in cause
    assert "그중 1,000,000원을 2026. 5. 1. 받았고 남은 원금은" not in cause
    assert re.search(r"^가\. ", cause, re.M) is not None
    assert re.search(r"^1\. 당사자 관계", cause, re.M) is not None
    assert re.search(r"^1\. 서가온", cause, re.M) is None


# --- exhibits + evidence list -----------------------------------------------------


def test_package_has_three_files_and_g1b_pass(case_env):
    # M5-fix1 K3: pass requires redacted copies; without them G1b names the gaps.
    _case_id, package, _state = _run_to_package(case_env, with_redacted=True)
    names = [entry["name"] for entry in package["files"]]
    assert names == ["content_proof.pdf", "exhibits.pdf", "evidence_list.pdf"]
    gates = {entry["gate"]: entry for entry in package["gate_results"]}
    assert gates["G1b"]["status"] == "pass"
    assert gates["G1b"]["findings"] == []


def test_exhibits_pages_cover_and_labels(case_env, tmp_path):
    case_id, _package, state = _run_to_package(case_env)
    files = case_state_mod.files_dir(case_id)
    exhibits = files / "exhibits.pdf"
    assert exhibits.exists()
    reader = PdfReader(str(exhibits))
    assert len(reader.pages) == len(state.evidence) + 1  # cover + evidence pages
    cover = reader.pages[0].extract_text() or ""
    assert "갑 호 증" in cover
    assert NOTICE_KO in _norm(cover) and DISCLAIMER_KO in _norm(cover)
    assert exhibit_bundle_mod.COVER_REMOVE_GUIDE in _norm(cover)
    for position, record in enumerate(
            sorted(state.evidence, key=lambda r: deps.ex_num(r.ex_id)), start=1):
        text = reader.pages[position].extract_text() or ""
        assert record.label in text
        assert record.filename in text
        assert record.sha256[:8] in text
        assert NOTICE_KO not in text
        assert DISCLAIMER_KO not in text
        if record.kind == "video":
            assert "영상 증거, 파일 별도 제출" in text
        if record.kind in ("image", "pdf"):
            # M5-fix1 K3: no originals; missing redacted copies show one line.
            assert exhibit_bundle_mod.MISSING_REDACTED_LINE in _norm(text)
            assert exhibit_bundle_mod.PRE_REDACTION_MARK not in text


def test_evidence_list_columns_and_facts_only(case_env):
    case_id, _package, _state = _run_to_package(case_env)
    path = case_state_mod.files_dir(case_id) / "evidence_list.pdf"
    text = _norm(_pdf_text(path))
    for header in ("호증 번호", "증거 이름", "작성일", "내용"):
        assert header in text
    assert "2026. 3. 10. 5,000,000원 이체 기록" in text
    assert "2026. 5. 1. 1,000,000원 이체 기록" in text
    assert "입증취지" not in text and "입증할" not in text
    assert "채무 승인" not in text and "채무 인정" not in text
    assert "승소" not in text
    assert NOTICE_KO not in text and DISCLAIMER_KO not in text


def _solid_png(path: Path, size: int, color: tuple) -> None:
    image = PILImage.new("RGB", (size, size), color)
    image.save(path)


def test_redacted_copy_replaces_original_in_pdf(tmp_path):
    # M5-fix1 K3: without a redacted copy no picture is embedded at all.
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    original = evidence_dir / "EX1_shot.png"
    redacted = evidence_dir / "EX1_redacted.png"
    _solid_png(original, 64, (30, 80, 200))
    _solid_png(redacted, 64, (210, 40, 40))
    record = {
        "ex_id": "EX1", "label": "갑 제1호증", "filename": "shot.png",
        "stored_name": original.name,
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "kind": "image",
    }
    out_red = tmp_path / "exhibits_red.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        [record], evidence_dir, out_red, redacted={"EX1": redacted})
    out_orig = tmp_path / "exhibits_orig.pdf"
    exhibit_bundle_mod.build_exhibits_pdf([record], evidence_dir, out_orig)
    images_red = PdfReader(str(out_red)).pages[1].images
    images_orig = PdfReader(str(out_orig)).pages[1].images
    assert len(images_red) == 1 and len(images_orig) == 0
    text_red = PdfReader(str(out_red)).pages[1].extract_text() or ""
    text_orig = PdfReader(str(out_orig)).pages[1].extract_text() or ""
    assert exhibit_bundle_mod.MISSING_REDACTED_LINE not in _norm(text_red)
    assert exhibit_bundle_mod.MISSING_REDACTED_LINE in _norm(text_orig)
    assert out_orig.read_bytes().count(original.read_bytes()) == 0


def test_no_full_account_or_resident_numbers_in_pdfs(case_env):
    case_id, _package, state = _run_to_package(case_env)
    fields = (state.confirmed_facts or {}).get("fields", {}) or {}
    phones = [fields.get("creditor_phone"), fields.get("debtor_phone"),
              *LEAK_EXCLUDE_PHONES]
    files = case_state_mod.files_dir(case_id)
    for name in ("content_proof.pdf", "exhibits.pdf", "evidence_list.pdf"):
        blob = _pdf_text(files / name) + "\n" + _pdf_metadata_text(files / name)
        hits = final_check_mod.find_sensitive_numbers(blob, exclude=phones)
        assert hits == [], (name, hits)
    # Regression proof: real patterns still hit, PDF timestamps do not.
    assert final_check_mod.find_sensitive_numbers("계좌 123-456789-01234") != []
    assert final_check_mod.find_sensitive_numbers("주민 900101-1234567") != []
    assert final_check_mod.find_sensitive_numbers("D:20261103150344+09'00'") == []
    assert final_check_mod.find_sensitive_numbers(
        "연락처 010-0000-0000", exclude=["010-0000-0000"]) == []


# --- G1b --------------------------------------------------------------------------


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
    calc_json, _calc = _calc_dict()
    amounts = final_check_mod.build_expected_amounts(SAMPLE_FIELDS, calc_json)
    dates = final_check_mod.build_expected_dates(SAMPLE_FIELDS, calc_json, "2026-06-01")
    names = final_check_mod.build_expected_names(SAMPLE_FIELDS)
    assert amounts["remaining_principal"] == 4014383
    assert amounts["allocations[0].applied_to_interest"] == 14383
    assert dates["accrual_start_date"] == "2026-05-02"
    return amounts, dates, names


def test_g1b_passes_normal_package(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    gate = final_check_mod.check_g1b(amounts, dates, names, docs)
    assert gate.status == "pass"
    assert gate.findings == []


def test_g1b_blocks_tampered_amount_date_name(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()

    tampered = {name: text.replace("4,014,383", "4,014,388")
                for name, text in docs.items()}
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any("4,014,383" in finding.message for finding in gate.findings)

    tampered = {name: text.replace("2026. 5. 2.", "2026. 5. 3.")
                for name, text in docs.items()}
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any("accrual_start_date" in finding.field for finding in gate.findings)

    tampered = {name: text.replace("서가온(SAMPLE)", "서가은(SAMPLE)")
                for name, text in docs.items()}
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any("creditor_name" in finding.field for finding in gate.findings)


def test_g1b_checks_allocation_sentence_numbers(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    # M5-fix1 K7: new wording carries the period/rate before the amount.
    tampered = {name: text.replace("14,383원", "14,388원")
                for name, text in docs.items()}
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any("applied_to_interest" in finding.field for finding in gate.findings)
    tampered = {name: text.replace("나머지 985,617원", "나머지 985,618원")
                for name, text in docs.items()}
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any("applied_to_principal" in finding.field for finding in gate.findings)


def test_g1b_reports_doc_set_and_naming(case_env):
    _package, docs = _package_docs(case_env)
    amounts, dates, names = _expected()
    tampered = dict(docs)
    tampered["evidence_list.pdf"] = tampered["evidence_list.pdf"] + "\n변호사 선임"
    gate = final_check_mod.check_g1b(amounts, dates, names, tampered)
    assert gate.status == "fail"
    assert any(finding.field == "evidence_list.pdf" for finding in gate.findings)
    missing = final_check_mod.check_g1b(amounts, dates, names, {
        name: text.replace("4,014,383", "4,014,388")
        for name, text in docs.items()})
    assert "content_proof.pdf" in missing.findings[0].message
    assert "exhibits.pdf" in missing.findings[0].message


def test_packager_holds_naming_before_writing(case_env, monkeypatch):
    from app.agents import packager as packager_check

    real_find = deps.find_forbidden_doc
    monkeypatch.setattr(deps, "find_forbidden_doc",
                        lambda text: ["변호사"] if "채권자" in text else real_find(text))
    client = case_env
    res = client.post("/api/cases/sample", json={"set": "kr"})
    case_id = res.json()["case_id"]
    client.post(f"/api/cases/{case_id}/run", json={})
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    client.put(f"/api/cases/{case_id}/facts", json=facts)
    client.post(f"/api/cases/{case_id}/run", json={})
    drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": s["sentence_id"], "approved": True}
        for s in drafts["sentences"]]})
    state = coord.get_case(case_id)
    with pytest.raises(packager_check.NamingViolation):
        packager_mod.build_package(state)
    assert not (case_state_mod.files_dir(case_id) / "content_proof.pdf").exists()
    assert not (case_state_mod.files_dir(case_id) / "exhibits.pdf").exists()
