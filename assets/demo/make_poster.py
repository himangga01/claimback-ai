"""Build the README poster for the demo video (assets/demo/demo-poster.jpg).

Takes one frame of docs/demo/claimback-demo.mp4 with ffmpeg, then draws a play
button and a caption band over it in Chromium (Playwright) so the Paperlogy
webfont renders the same as on the site.

    python assets/demo/make_poster.py            # needs ffmpeg and playwright
"""
from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "docs" / "demo" / "claimback-demo.mp4"
FONTS = ROOT / "frontend" / "fonts"
OUT = ROOT / "assets" / "demo" / "demo-poster.jpg"
FRAME_AT = "9"  # seconds: the five SAMPLE evidence cards over the start screen

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Paperlogy; font-weight: 400; src: url(data:font/woff2;base64,{f4}); }}
@font-face {{ font-family: Paperlogy; font-weight: 600; src: url(data:font/woff2;base64,{f6}); }}
html, body {{ margin: 0; width: 1280px; height: 720px; overflow: hidden; }}
.frame {{ position: absolute; inset: 0; background: url(data:image/png;base64,{frame}) center/cover; }}
.shade {{ position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(37,39,34,0) 54%, rgba(37,39,34,.94) 64%, #252722 68%); }}
.play {{ position: absolute; left: 50%; top: 44%; width: 132px; height: 132px; margin: -66px 0 0 -66px;
  border-radius: 50%; background: #ff7769; box-shadow: 0 10px 34px rgba(0,0,0,.28), 0 0 0 10px rgba(255,254,250,.55); }}
.play::after {{ content: ""; position: absolute; left: 52px; top: 38px;
  border-style: solid; border-width: 28px 0 28px 46px; border-color: transparent transparent transparent #fffefa; }}
.band {{ position: absolute; left: 56px; right: 56px; bottom: 40px; display: flex; align-items: flex-end;
  justify-content: space-between; color: #fffefa; font-family: Paperlogy, sans-serif; }}
.band strong {{ display: block; font-weight: 600; font-size: 44px; letter-spacing: -1.4px; }}
.band span {{ display: block; margin-top: 8px; font-weight: 400; font-size: 22px; opacity: .86; }}
.band em {{ font-style: normal; font-weight: 600; font-size: 22px; padding: 8px 16px;
  border: 2px solid rgba(255,254,250,.8); border-radius: 999px; }}
</style></head><body>
<div class="frame"></div><div class="shade"></div><div class="play"></div>
<div class="band"><div><strong>Watch the demo</strong>
<span>ClaimBack My Money &middot; live Meta Model API calls &middot; English captions</span></div><em>2:58</em></div>
</body></html>"""


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> int:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", FRAME_AT, "-i", str(VIDEO),
                        "-frames:v", "1", str(frame)], check=True)
        html = HTML.format(f4=b64(FONTS / "Paperlogy-4Regular.woff2"),
                           f6=b64(FONTS / "Paperlogy-6SemiBold.woff2"), frame=b64(frame))
        shot = Path(tmp) / "poster.png"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(html)
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(shot))
            browser.close()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(shot), "-q:v", "3", str(OUT)], check=True)
    print(OUT, OUT.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
