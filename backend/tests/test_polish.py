"""Polish after INT-3c: real call counts, sample footer, video note, citation spacing."""

from pypdf import PdfReader

from app.agents import deps
from app.services import exhibit_bundle as exhibit_bundle_mod
from tests.test_case_replay import _run_full_flow, replay_env  # noqa: F401


def test_substeps_carry_real_call_counts(replay_env):
    snapshots = _run_full_flow(replay_env)
    view = replay_env.get(f"/api/cases/{snapshots['case_id']}").json()
    steps = {s["key"]: s for s in view["steps"]}
    reading_calls = sum(x.get("calls", 0) for x in steps["reading"]["substeps"])
    vision_calls = sum(x.get("calls", 0) for x in steps["vision"]["substeps"])
    # tall screenshots are read in several tiles; SAM runs several nouns
    done_reads = sum(1 for x in steps["reading"]["substeps"] if x["status"] == "done")
    assert reading_calls > done_reads
    assert vision_calls >= 4 * sum(1 for x in steps["vision"]["substeps"]
                                   if x["status"] == "done")


def test_sample_bundle_marks_every_page(replay_env, tmp_path):
    snapshots = _run_full_flow(replay_env)
    case_id = snapshots["case_id"]
    pdf = tmp_path / "exhibits.pdf"
    pdf.write_bytes(replay_env.get(f"/api/cases/{case_id}/files/exhibits.pdf").content)
    reader = PdfReader(str(pdf))
    for page in reader.pages:
        assert "SAMPLE" in (page.extract_text() or "")


def test_non_sample_case_has_no_sample_footer():
    assert not exhibit_bundle_mod.is_sample_case(
        {"fields": {"creditor_name": "김하나", "debtor_name": "박민준"}})
    assert exhibit_bundle_mod.is_sample_case(
        {"fields": {"creditor_name": "서가온(SAMPLE)", "debtor_name": "x"}})


def test_video_placeholder_warns_about_unredacted_original():
    assert "가림을 하지 않은 원본" in exhibit_bundle_mod.VIDEO_PLACEHOLDER


def test_citation_is_a_separate_token():
    text = deps.render_sentence(
        "이체 확인증에는 {{loan_date}}에 {{principal}}을 보낸 기록이 있습니다[[EX:4]]",
        {"loan_date": "2026. 3. 10.", "principal": "5,000,000원"}, {})
    assert text.endswith("있습니다 [갑 제4호증].")
