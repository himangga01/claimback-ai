"""Rebuild the ClaimBack My Money logo files in assets/logo/.

The wordmark copies the site header (frontend/index.html `.brand`, frontend/case.css
`.brand*` rules): four coral bars, a 9px gap, then "claimback" in Paperlogy 600 and
" my money." in Paperlogy 400, 27px, letter-spacing -1.1px, kerning from the font's
`kern` table. The SVG text is converted to outline paths, so it renders without the
webfont (GitHub shows SVGs through <img>, where webfonts do not load).

Outputs (all in this folder):
  claimback-logo.svg, claimback-logo-dark.svg   outlined wordmark, transparent
  claimback-logo.png, claimback-logo-dark.png   the SVGs rendered at 4x (transparent)
  claimback-icon.png                            frontend/favicon.svg at 512x512

Needs: fonttools + brotli (to read the woff2 fonts) for the SVGs, and Playwright with
Chromium for the PNGs and for --check. Run from anywhere:
  python assets/logo/make_logo.py            # SVGs and PNGs
  python assets/logo/make_logo.py --check    # also diff against the live header
"""

from __future__ import annotations

import argparse
import base64
import math
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FONTS = ROOT / "frontend" / "fonts"
FAVICON = ROOT / "frontend" / "favicon.svg"

# Values copied from frontend/case.css (.brand, .brand strong, .brand-symbol).
FONT_PX = 27.0
LETTER_SPACING_PX = -1.1
BRAND_GAP_PX = 9.0
BAR_WIDTH_PX = 3.0
BAR_GAP_PX = 2.0
BAR_HEIGHTS_PX = (20.0, 27.0, 24.0, 16.0)
SYMBOL_HEIGHT_PX = 27.0
RUNS = (("claimback", "Paperlogy-6SemiBold.woff2"), (" my money.", "Paperlogy-4Regular.woff2"))

BAR_COLOR = "#e55749"
INK = "#252722"  # --ink
SHEET = "#fffefa"  # --sheet, text colour of the dark-mode variant
PAPER = "#f5f4ef"  # --paper, page background used by --check

MARGIN_PX = 2.0  # around the ink, then rounded out to whole px
PNG_SCALE = 4  # whole number keeps the bar edges on device pixels
ICON_PX = 512


def num(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def layout() -> dict:
    """Place the bars and glyph outlines the way Chromium lays out the header."""
    fonts = [TTFont(FONTS / name) for _, name in RUNS]
    hhea = fonts[0]["hhea"]
    upem = fonts[0]["head"].unitsPerEm
    # line-height: normal. Blink rounds ascent and descent to whole px separately.
    ascent = round(hhea.ascent * FONT_PX / upem)
    descent = round(-hhea.descent * FONT_PX / upem)
    line_h = ascent + descent
    brand_h = max(line_h, SYMBOL_HEIGHT_PX)  # .brand is a flex row, align-items: center
    text_top = (brand_h - line_h) / 2
    baseline = text_top + ascent
    symbol_top = (brand_h - SYMBOL_HEIGHT_PX) / 2

    bars = []
    for i, h in enumerate(BAR_HEIGHTS_PX):
        x = i * (BAR_WIDTH_PX + BAR_GAP_PX)
        # Centring gives half-px tops (5.5, 3.5, 7.5); Chromium paints them on whole
        # px, rounding half up (seen in header screenshots at 1x, 1.5x, 2x, 3x and 4x).
        top = math.floor(symbol_top + (SYMBOL_HEIGHT_PX - h) / 2 + 0.5)
        bars.append((x, top, BAR_WIDTH_PX, h))
    symbol_w = len(BAR_HEIGHTS_PX) * BAR_WIDTH_PX + (len(BAR_HEIGHTS_PX) - 1) * BAR_GAP_PX

    scale = FONT_PX / upem
    pen_x = symbol_w + BRAND_GAP_PX
    glyphs = []  # (path data, bounds) per drawn glyph
    for (text, _), font in zip(RUNS, fonts):
        cmap = font.getBestCmap()
        names = [cmap[ord(ch)] for ch in text]
        kern = {}
        for table in font["kern"].kernTables:
            for pair, value in table.kernTable.items():
                kern[pair] = kern.get(pair, 0) + value
        glyph_set = font.getGlyphSet()
        hmtx = font["hmtx"]
        for i, name in enumerate(names):
            transform = (scale, 0, 0, -scale, pen_x, baseline)
            svg_pen = SVGPathPen(glyph_set, ntos=num)
            glyph_set[name].draw(TransformPen(svg_pen, transform))
            data = svg_pen.getCommands()
            if data:
                bounds_pen = BoundsPen(glyph_set)
                glyph_set[name].draw(TransformPen(bounds_pen, transform))
                glyphs.append((data, bounds_pen.bounds))
            advance = hmtx[name][0]
            if i + 1 < len(names):
                advance += kern.get((name, names[i + 1]), 0)
            pen_x += advance * scale + LETTER_SPACING_PX

    boxes = [(x, y, x + w, y + h) for x, y, w, h in bars] + [b for _, b in glyphs]
    x0 = math.floor(min(b[0] for b in boxes) - MARGIN_PX)
    y0 = math.floor(min(b[1] for b in boxes) - MARGIN_PX)
    x1 = math.ceil(max(b[2] for b in boxes) + MARGIN_PX)
    y1 = math.ceil(max(b[3] for b in boxes) + MARGIN_PX)
    return {"bars": bars, "glyphs": glyphs, "origin": (x0, y0), "size": (x1 - x0, y1 - y0)}


def build_svg(lay: dict, text_color: str, bar_color: str) -> str:
    x0, y0 = lay["origin"]
    w, h = lay["size"]
    rects = "".join(
        f'<rect x="{num(x - x0)}" y="{num(y - y0)}" width="{num(bw)}" height="{num(bh)}"/>'
        for x, y, bw, bh in lay["bars"]
    )
    # Glyph paths are in brand-box px; shift them with one translate.
    path = "".join(data for data, _ in lay["glyphs"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}"'
        f' role="img" aria-labelledby="title">\n'
        f'<title id="title">ClaimBack My Money</title>\n'
        f'<g fill="{bar_color}">{rects}</g>\n'
        f'<path fill="{text_color}" transform="translate({num(-x0)} {num(-y0)})" d="{path}"/>\n'
        f"</svg>\n"
    )


def render_png(page, svg: Path, png: Path, css_w: float, css_h: float) -> None:
    """Screenshot the SVG as an <img>; the page's device_scale_factor sets the PNG size."""
    src = "data:image/svg+xml;base64," + base64.b64encode(svg.read_bytes()).decode("ascii")
    page.set_viewport_size({"width": math.ceil(css_w), "height": math.ceil(css_h)})
    page.set_content(
        "<style>html,body{margin:0;background:transparent}img{display:block}</style>"
        f'<img src="{src}" width="{css_w}" height="{css_h}">'
    )
    page.wait_for_function("document.images[0].complete && document.images[0].naturalWidth > 0")
    page.screenshot(path=str(png), omit_background=True, clip={"x": 0, "y": 0, "width": css_w, "height": css_h})


def check(lay: dict, png: Path, browser) -> None:
    """Diff the light PNG (on the paper colour) against the real header at the same scale."""
    import io

    from PIL import Image, ImageChops

    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=PNG_SCALE)
    page.goto((ROOT / "frontend" / "index.html").as_uri())
    page.evaluate("document.fonts.ready.then(() => true)")
    bx, by = page.evaluate("(() => { const b = document.querySelector('.brand').getBoundingClientRect(); return [b.x, b.y]; })()")
    x0, y0 = lay["origin"]
    w, h = lay["size"]
    shot = page.screenshot(clip={"x": bx + x0, "y": by + y0, "width": w, "height": h})
    page.close()
    site = Image.open(io.BytesIO(shot)).convert("RGB")
    logo = Image.open(png).convert("RGBA")
    flat = Image.new("RGBA", logo.size, PAPER)
    flat.alpha_composite(logo)
    flat = flat.convert("RGB")
    if flat.size != site.size:
        raise SystemExit(f"size mismatch: logo {flat.size} vs header {site.size}")
    hist = ImageChops.difference(site, flat).convert("L").histogram()
    total = sum(hist)
    mean = sum(i * n for i, n in enumerate(hist)) / total
    over = sum(hist[65:])
    print(
        f"check: {flat.size[0]}x{flat.size[1]} px, mean diff {mean:.2f}/255,"
        f" max {max(i for i, n in enumerate(hist) if n)}, pixels over 64: {over} ({100 * over / total:.3f}%)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-png", action="store_true", help="write only the SVGs")
    parser.add_argument("--check", action="store_true", help="diff the PNG against the live header")
    args = parser.parse_args()

    lay = layout()
    w, h = lay["size"]
    light, dark = HERE / "claimback-logo.svg", HERE / "claimback-logo-dark.svg"
    light.write_text(build_svg(lay, INK, BAR_COLOR), encoding="utf-8")
    dark.write_text(build_svg(lay, SHEET, BAR_COLOR), encoding="utf-8")
    print(f"svg: {w}x{h} px viewBox")
    if args.no_png:
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=PNG_SCALE)
        for svg in (light, dark):
            render_png(page, svg, svg.with_suffix(".png"), w, h)
        page.close()
        icon_page = browser.new_page(device_scale_factor=ICON_PX / 64)
        render_png(icon_page, FAVICON, HERE / "claimback-icon.png", 64, 64)
        icon_page.close()
        print(f"png: {w * PNG_SCALE}x{h * PNG_SCALE} logos, {ICON_PX}x{ICON_PX} icon")
        if args.check:
            check(lay, light.with_suffix(".png"), browser)
        browser.close()


if __name__ == "__main__":
    main()
