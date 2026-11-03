"""M2b case-flow E2E (pytest + Playwright, Chromium, 1920x1080).

Target is $E2E_BASE_URL when set (later: the real M2a backend); otherwise the
stub server in this folder is started on a free 127.0.0.1 port for the test.
"""

import os
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


class Steps:
    def __init__(self, page):
        self.page = page
        self.n = 0

    def shot(self, name: str) -> None:
        ARTIFACTS.mkdir(exist_ok=True)
        self.n += 1
        self.page.screenshot(
            path=str(ARTIFACTS / f"{self.n:02d}-{name}.png"), full_page=True
        )
        found = check_text(self.page.inner_text("body"))
        assert found == [], f"forbidden names at step {name}: {found}"


def test_case_flow(page, base_url):
    expect_stub = not os.environ.get("E2E_BASE_URL")
    steps = Steps(page)
    page.goto(base_url + "/", wait_until="networkidle")
    expect(page.get_by_test_id("offline-notice")).to_be_hidden()

    # 1. sample load -> agent board -> CHECKPOINT_1
    page.get_by_test_id("load-sample").click()
    expect(page.get_by_test_id("case-state")).to_have_text(
        "CHECKPOINT_1", timeout=30000
    )
    if expect_stub:
        expect(page.get_by_test_id("stub-banner")).to_be_visible()
    else:
        expect(page.get_by_test_id("stub-banner")).to_be_hidden()
    expect(page.get_by_test_id("step-reading")).to_be_visible()
    expect(page.get_by_test_id("replay-badge")).to_be_visible()
    steps.shot("board")

    # 2. checkpoint 1: at least one reading box, then switch evidence
    page.get_by_test_id("reading-box-EX1-item1").wait_for(
        state="visible", timeout=15000
    )
    assert page.locator(".reading-box").count() >= 1
    page.get_by_test_id("evidence-EX4").click()
    page.get_by_test_id("reading-box-EX4-item1").wait_for(
        state="visible", timeout=15000
    )
    steps.shot("checkpoint-evidence")

    # 3. fixed demo inputs: first repay_promise highlight, suggested roles,
    # as_of 2026-06-01, empty fields from fallback
    page.get_by_test_id("highlight-EX1-item4").check()
    phone = page.get_by_test_id("field-creditor_phone")
    if (phone.input_value() or "").strip() == "":
        phone.fill("010-0000-0000")
    expect(page.get_by_test_id("asof")).to_have_value("2026-06-01")
    steps.shot("checkpoint-filled")

    # 4. confirm -> CALCULATING -> DRAFT_APPROVAL, calc shows remainder
    page.get_by_test_id("confirm-facts").click()
    expect(page.get_by_test_id("case-state")).to_have_text(
        "DRAFT_APPROVAL", timeout=30000
    )
    expect(page.get_by_test_id("calc-section")).to_be_visible()
    expect(page.get_by_test_id("remaining-principal")).to_contain_text("4,014,383")
    steps.shot("calculation")

    # 5. drafts shown, slot view on for s1
    expect(page.get_by_test_id("sentence-s3")).to_be_visible()
    expect(page.get_by_test_id("revision-rounds")).to_contain_text("문안 작성")
    page.get_by_test_id("slots-toggle-s1").click()
    expect(page.get_by_test_id("slots-s1")).to_be_visible()
    steps.shot("drafts")

    # 6. G1a scene: digits outside slots are blocked
    edit = page.get_by_test_id("edit-s3")
    original = edit.input_value()
    assert "{{" in original, "edit box should hold text_with_slots"
    edit.fill("500만 원을 보냈습니다.")
    page.get_by_test_id("update-s3").click()
    findings = page.get_by_test_id("findings-s3")
    expect(findings).to_contain_text("G1a", timeout=15000)
    expect(page.get_by_test_id("approve-s3")).to_be_disabled()
    steps.shot("g1a-blocked")

    # 7. revert -> pass
    edit.fill(original)
    page.get_by_test_id("update-s3").click()
    expect(findings).to_contain_text("지적 없음", timeout=15000)
    expect(page.get_by_test_id("approve-s3")).to_be_enabled()
    steps.shot("drafts-fixed")

    # 8. approve all sentences
    for sid in ("s1", "s2", "s3", "s4"):
        box = page.get_by_test_id(f"approve-{sid}")
        if not box.is_checked():
            box.check()
        expect(box).to_be_checked(timeout=15000)
    steps.shot("drafts-approved")

    # 9. continue -> package
    page.get_by_test_id("approve-continue").click()
    expect(page.get_by_test_id("case-state")).to_have_text(
        "CHECKPOINT_2", timeout=30000
    )
    expect(page.get_by_test_id("package-section")).to_be_visible()
    expect(page.get_by_test_id("file-content_proof.pdf")).to_be_visible()
    expect(page.get_by_test_id("claim-purpose")).to_contain_text("2026. 5. 2.")
    copy_btn = page.get_by_test_id("copy-claim-purpose")
    expect(copy_btn).to_be_visible()
    copy_btn.click()
    expect(copy_btn).to_contain_text("복사 완료", timeout=5000)
    steps.shot("package")

    # 10. delete case
    page.get_by_test_id("delete-case").click()
    expect(page.get_by_test_id("board-section")).to_be_hidden(timeout=15000)
    steps.shot("deleted")
