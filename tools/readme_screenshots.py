"""Take the README screenshots of the ClaimBack My Money screen.

Drives the real backend in replay mode (no API key) through the sample
case with Playwright (Chromium) and saves cropped PNGs to
``assets/screenshots/``:

  01-start.png        English start screen (header, headline, dividers, cover)
  02-reading.png      evidence list, original with reading boxes, redacted copy
  03-fact-check.png   checkpoint 1: fact-check sheet, values with their sources
  04-calculation.png  interest allocation and principal left
  05-draft.png        draft approval: sentences with citations, one slot view open
  06-package.png      filing package: files, document checks, e-court text
  07-start-ko.png     Korean start screen
  08-mobile.png       phone width (390x844), English, agent board at checkpoint 1 (kept at 2x)

Desktop shots use a 1440 px wide viewport at device_scale_factor 2 and are
downscaled to CSS pixel size (1440 px for full-width shots) with LANCZOS.
Each PNG is saved with optimize=True; one still above --max-kb is quantized
to 256 colours.

The facts confirmed at checkpoint 1 follow the same rule as the E2E test
(specs/case-api-contract.md section 5): review values, empty fields from
specs/case-api-examples/confirmed_facts_kr.json, suggested roles, the first
repay_promise statement highlighted, as of 2026-06-01. Replay only matches
that exact input.

Start the backend first (PowerShell):

  cd backend
  $env:META_MODE = "replay"
  ..\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8050

Then, from the repo root:

  .\\.venv\\Scripts\\python.exe tools\\readme_screenshots.py --base-url http://127.0.0.1:8050

Optional: --doc SRC=NAME (repeatable) copies an existing PNG render of a
generated PDF page into the output folder, downscaled to --doc-width.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "screenshots"
CONFIRMED_EXAMPLE = ROOT / "specs" / "case-api-examples" / "confirmed_facts_kr.json"
KNOWN_ROLES = ("loan_transfer", "repayment", "loan_agreement", "other")

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
DSF = 2
MARGIN = 24  # CSS px kept around a cropped section
RUN_TIMEOUT_MS = 180_000


# ---------- confirmed facts (same rule as e2e/test_case_flow.py) ----------

def _ex_num(ex_id: str) -> int:
    return int(ex_id[2:])


def _item_num(item_id: str) -> int:
    digits = "".join(ch for ch in (item_id or "") if ch.isdigit())
    return int(digits) if digits else 0


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


def expected_confirmed_facts(review: dict, fallback: dict) -> dict:
    fields = {}
    for f in review["fields"]:
        name, val = f["field"], f["value"]
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
    return {"fields": fields, "evidence_roles": roles, "highlight": highlight,
            "as_of": "2026-06-01"}


def fill_demo_facts(page: Page, base_url: str, case_id: str) -> dict:
    resp = page.request.get(f"{base_url}/api/cases/{case_id}/review")
    if not resp.ok:
        raise RuntimeError(f"GET /review failed: {resp.status}")
    review = resp.json()
    fallback = json.loads(CONFIRMED_EXAMPLE.read_text(encoding="utf-8"))["fallback_fields"]
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
    return expected


# ---------- page helpers ----------

SETTLE_JS = """async () => {
  await document.fonts.ready;
  const imgs = [...document.images].filter((im) => !im.hidden && im.getAttribute('src'));
  await Promise.all(imgs.map((im) => im.complete ? null
    : new Promise((ok) => { im.addEventListener('load', ok, {once: true});
                            im.addEventListener('error', ok, {once: true}); })));
  await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
  return imgs.filter((im) => !(im.naturalWidth > 0)).map((im) => im.src);
}"""

RECT_JS = """(sels) => {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      x1 = Math.min(x1, r.left + scrollX); y1 = Math.min(y1, r.top + scrollY);
      x2 = Math.max(x2, r.right + scrollX); y2 = Math.max(y2, r.bottom + scrollY);
    }
  }
  if (!isFinite(x1)) return null;
  return {x1, y1, x2, y2,
          pw: document.documentElement.scrollWidth,
          ph: document.documentElement.scrollHeight};
}"""


def settle(page: Page) -> None:
    broken = page.evaluate(SETTLE_JS)
    if broken:
        raise RuntimeError(f"images failed to load: {broken}")
    page.wait_for_timeout(300)


def rect_of(page: Page, sels: list[str], margin: int = MARGIN,
            full_width: bool = False, top: float | None = None,
            bottom_sels: list[str] | None = None) -> dict:
    """Page-coordinate clip covering the union of ``sels`` plus a margin.

    ``top`` fixes the top edge; ``bottom_sels`` ends the clip at the bottom
    of those elements instead of the bottom of ``sels``."""
    r = page.evaluate(RECT_JS, sels)
    if r is None:
        raise RuntimeError(f"nothing visible for {sels}")
    if bottom_sels:
        b = page.evaluate(RECT_JS, bottom_sels)
        if b is None:
            raise RuntimeError(f"nothing visible for {bottom_sels}")
        r["y2"] = b["y2"]
    x1 = 0 if full_width else max(0, r["x1"] - margin)
    x2 = r["pw"] if full_width else min(r["pw"], r["x2"] + margin)
    y1 = top if top is not None else max(0, r["y1"] - margin)
    y2 = min(r["ph"], r["y2"] + margin)
    return {"x": round(x1), "y": round(y1),
            "width": round(x2 - x1), "height": round(y2 - y1)}


def save_png(raw: bytes, path: Path, scale: float, max_kb: int) -> tuple[int, str]:
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if scale != 1:
        size = (round(im.width * scale), round(im.height * scale))
        im = im.resize(size, Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)
    mode = "rgb"
    if path.stat().st_size > max_kb * 1024:
        q = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                        dither=Image.Dither.NONE)
        q.save(path, optimize=True)
        mode = "256 colours"
    return path.stat().st_size, mode


class Shooter:
    def __init__(self, out: Path, max_kb: int, only: set[str] | None):
        self.out = out
        self.max_kb = max_kb
        self.only = only
        self.saved: list[tuple[str, int, str, tuple[int, int]]] = []

    def wanted(self, name: str) -> bool:
        return not self.only or name in self.only

    def shot(self, page: Page, name: str, clip: dict | None,
             scale: float = 1 / DSF) -> None:
        if not self.wanted(name):
            return
        settle(page)
        if clip is None:
            raw = page.screenshot(full_page=False)
        else:
            raw = page.screenshot(full_page=True, clip=clip)
        path = self.out / f"{name}.png"
        size, mode = save_png(raw, path, scale, self.max_kb)
        with Image.open(path) as im:
            dims = im.size
        self.saved.append((path.name, size, mode, dims))
        print(f"saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}"
              f"  {dims[0]}x{dims[1]}  {size / 1024:.0f} KB  ({mode})")


# ---------- flows ----------

def new_context(browser, viewport: dict, locale: str, phone: bool = False):
    return browser.new_context(
        viewport=viewport,
        device_scale_factor=DSF,
        locale=locale,
        reduced_motion="reduce",  # the screen drops its animations and smooth scroll
        is_mobile=phone,
        has_touch=phone,
    )


def open_start(page: Page, base_url: str, lang: str) -> None:
    page.goto(f"{base_url}/?lang={lang}", wait_until="networkidle")
    expect(page.locator("html")).to_have_attribute("lang", lang)
    expect(page.locator("#app")).to_be_visible()
    expect(page.get_by_test_id("offline-notice")).to_be_hidden()


def start_clip(page: Page) -> dict:
    # Header through the cover and the bottom note, full width.
    return rect_of(page, ["header.site-header", "main.main-container"],
                   full_width=True, top=0, margin=0)


def load_sample(page: Page) -> str:
    """Load the sample case and return its id as soon as the screen shows it,
    so cleanup can delete the case even if the run later times out."""
    page.get_by_test_id("load-sample").click()
    expect(page.get_by_test_id("case-id")).not_to_be_empty(timeout=30_000)
    case_id = page.get_by_test_id("case-id").inner_text().strip()
    # The screen shows the replay badge from the same case view; without it
    # the backend is calling the Meta API live and spending credit.
    if not page.get_by_test_id("replay-badge").is_visible():
        raise SystemExit(f"backend is not in replay mode (case {case_id}); "
                         "start it with META_MODE=replay")
    return case_id


def wait_checkpoint_1(page: Page) -> None:
    expect(page.get_by_test_id("case-state")).to_have_attribute(
        "data-state", "CHECKPOINT_1", timeout=RUN_TIMEOUT_MS)
    page.locator(".reading-box").first.wait_for(state="visible", timeout=30_000)


def delete_case(page: Page, base_url: str, case_id: str | None) -> None:
    if not case_id:
        return
    try:
        resp = page.request.delete(f"{base_url}/api/cases/{case_id}")
        if not resp.ok:
            print(f"warning: case {case_id} not deleted (HTTP {resp.status}); "
                  "delete it on the screen once its run ends", file=sys.stderr)
    except Exception as exc:  # cleanup only
        print(f"warning: could not delete {case_id}: {exc}", file=sys.stderr)


def desktop_flow(browser, base_url: str, shooter: Shooter) -> None:
    ctx = new_context(browser, DESKTOP, "en-US")
    page = ctx.new_page()
    case_id = None
    try:
        open_start(page, base_url, "en")
        shooter.shot(page, "01-start", start_clip(page))

        case_id = load_sample(page)
        wait_checkpoint_1(page)
        expect(page.get_by_test_id("case-state")).to_have_text("Waiting for your fact check")
        expect(page.get_by_test_id("redaction-img")).to_be_visible()

        # 02: the evidence column (list, original with boxes, redacted copy).
        # The column itself stretches to the grid row, so use its children.
        shooter.shot(page, "02-reading", rect_of(page, [".cp-left > *"]))

        # 03: the sheet from its heading to the conflicts, both columns.
        sec = page.evaluate(RECT_JS, ["#checkpoint-section"])
        shooter.shot(page, "03-fact-check", rect_of(
            page, ["#checkpoint-section"], top=sec["y1"] - MARGIN,
            bottom_sels=["#conflict-list"]))

        fill_demo_facts(page, base_url, case_id)
        page.get_by_test_id("confirm-facts").click()
        expect(page.get_by_test_id("case-state")).to_have_attribute(
            "data-state", "DRAFT_APPROVAL", timeout=RUN_TIMEOUT_MS)
        expect(page.get_by_test_id("calc-section")).to_be_visible()
        expect(page.locator(".sentence").first).to_be_visible()

        shooter.shot(page, "04-calculation", rect_of(page, ["#calc-section"]))

        # 05: open the slot view of the sentence that holds {{principal}}
        # (else the first fact sentence) so the slots show next to the
        # rendered sentences.
        drafts = page.request.get(f"{base_url}/api/cases/{case_id}/drafts").json()
        sentences = drafts.get("sentences", [])
        sid = next((s["sentence_id"] for s in sentences
                    if "{{principal}}" in (s.get("text_with_slots") or "")), None)
        if sid is None:
            sid = next((s["sentence_id"] for s in sentences if s.get("type") == "fact"),
                       sentences[0]["sentence_id"] if sentences else None)
        if sid is not None:
            page.get_by_test_id(f"slots-toggle-{sid}").click()
            expect(page.get_by_test_id(f"slots-{sid}")).to_be_visible()
        shooter.shot(page, "05-draft", rect_of(page, ["#drafts-section"]))

        boxes = page.locator("input[data-testid^='approve-']")
        for i in range(boxes.count()):
            box = boxes.nth(i)
            if not box.is_checked():
                with page.expect_response(
                        lambda r: r.request.method == "PUT" and "/drafts" in r.url):
                    box.check()
            expect(box).to_be_checked(timeout=15_000)
        page.get_by_test_id("approve-continue").click()
        expect(page.get_by_test_id("case-state")).to_have_attribute(
            "data-state", "CHECKPOINT_2", timeout=RUN_TIMEOUT_MS)
        expect(page.get_by_test_id("package-section")).to_be_visible()
        expect(page.get_by_test_id("file-content_proof.pdf")).to_be_visible()

        shooter.shot(page, "06-package", rect_of(page, ["#package-section"]))
    finally:
        delete_case(page, base_url, case_id)
        ctx.close()


def korean_start(browser, base_url: str, shooter: Shooter) -> None:
    if not shooter.wanted("07-start-ko"):
        return
    ctx = new_context(browser, DESKTOP, "ko-KR")
    page = ctx.new_page()
    try:
        open_start(page, base_url, "ko")
        expect(page.get_by_test_id("load-sample")).to_contain_text("샘플 사건 불러오기")
        shooter.shot(page, "07-start-ko", start_clip(page))
    finally:
        ctx.close()


def phone_flow(browser, base_url: str, shooter: Shooter) -> None:
    if not shooter.wanted("08-mobile"):
        return
    ctx = new_context(browser, PHONE, "en-US", phone=True)
    page = ctx.new_page()
    case_id = None
    try:
        open_start(page, base_url, "en")
        case_id = load_sample(page)
        wait_checkpoint_1(page)
        # The agent board at checkpoint 1 (reading, vision and privacy done,
        # waiting for the fact check): one phone viewport from the board's
        # top, kept at 2x for a crisp phone shot.
        expect(page.get_by_test_id("board-summary")).to_contain_text("Meta model calls")
        page.evaluate("""() => {
          const top = document.getElementById('board-section').getBoundingClientRect().top;
          window.scrollTo({top: top + window.scrollY - 12, behavior: 'instant'});
        }""")
        shooter.shot(page, "08-mobile", None, scale=1)
    finally:
        delete_case(page, base_url, case_id)
        ctx.close()


def copy_docs(specs: list[str], out: Path, width: int, shooter: Shooter) -> None:
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"--doc needs SRC=NAME, got {spec!r}")
        src, name = spec.split("=", 1)
        if not name.endswith(".png"):
            name += ".png"
        with Image.open(src) as im:
            im = im.convert("RGB")
            scale = min(1.0, width / im.width)
            buf = io.BytesIO()
            im.save(buf, format="PNG")
        path = out / name
        size, mode = save_png(buf.getvalue(), path, scale, shooter.max_kb)
        with Image.open(path) as done:
            dims = done.size
        shooter.saved.append((path.name, size, mode, dims))
        print(f"saved {name}  {dims[0]}x{dims[1]}  {size / 1024:.0f} KB  ({mode})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8050")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-kb", type=int, default=600)
    ap.add_argument("--only", nargs="*", help="names to take, e.g. 01-start 08-mobile")
    ap.add_argument("--doc", action="append", default=[],
                    help="SRC=NAME: copy a PDF page render, e.g. ...\\content_proof_p1.png=09-document-demand-letter")
    ap.add_argument("--doc-width", type=int, default=1000)
    args = ap.parse_args()

    base_url = args.base_url.rstrip("/")
    shooter = Shooter(args.out, args.max_kb, set(args.only) if args.only else None)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            if any(shooter.wanted(n) for n in ("01-start", "02-reading", "03-fact-check",
                                                "04-calculation", "05-draft", "06-package")):
                desktop_flow(browser, base_url, shooter)
            korean_start(browser, base_url, shooter)
            phone_flow(browser, base_url, shooter)
        finally:
            browser.close()
    if args.doc:
        copy_docs(args.doc, args.out, args.doc_width, shooter)
    over = [s for s in shooter.saved if s[1] > args.max_kb * 1024]
    for name, size, _, _ in over:
        print(f"warning: {name} is {size / 1024:.0f} KB, above {args.max_kb} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
