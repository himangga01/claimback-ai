# ClaimBack My Money logo files

The wordmark is the site header (`frontend/index.html` `.brand`, styled in `frontend/case.css`):
four coral `#e55749` bars, then "claimback" in Paperlogy SemiBold and " my money." in Paperlogy
Regular at 27px, letter-spacing -1.1px, with the font's own kerning.

| File | What it is |
| --- | --- |
| `claimback-logo.svg` | Wordmark for light backgrounds. Text `#252722`. The text is outline paths, so no font is needed. Transparent background, 312×34 viewBox (header size plus a 2px margin). |
| `claimback-logo-dark.svg` | Same wordmark for dark backgrounds. Text `#fffefa`, bars unchanged. |
| `claimback-logo.png`, `claimback-logo-dark.png` | The two SVGs rendered at 4× (1248×136), transparent. |
| `claimback-icon.png` | `frontend/favicon.svg` rendered at 512×512, transparent corners. |
| `make_logo.py` | Rebuilds all of the above. |

GitHub shows SVGs through `<img>`, where webfonts do not load, so the SVGs carry the glyph
outlines. To switch with the reader's theme:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/claimback-logo-dark.svg">
  <img src="assets/logo/claimback-logo.svg" alt="claimback my money." width="440">
</picture>
```

## How the files are made

`make_logo.py` reads `frontend/fonts/Paperlogy-6SemiBold.woff2` and `Paperlogy-4Regular.woff2`
with fontTools, applies the `kern` table pairs and the letter-spacing, and places the glyph
outlines and bars where Chromium places them in the header (line-height `normal` with ascent and
descent rounded to whole px; bars painted on whole px). Playwright's Chromium then renders each SVG
as an `<img>` for the PNGs. `--check` screenshots the real header at 4× and diffs it against the
light PNG on the paper colour `#f5f4ef`.

fontTools and brotli are not in the project's requirements (the app does not need them), so
install them into a separate venv first. Run from the repo root:

```powershell
python -m venv .venv-logo
.\.venv-logo\Scripts\python.exe -m pip install fonttools brotli playwright   # brotli reads woff2
.\.venv-logo\Scripts\python.exe -m playwright install chromium
.\.venv-logo\Scripts\python.exe assets\logo\make_logo.py --check
```

Check result on 2026-11-04: 1248×136 px, mean difference 0.80/255, 65 pixels (0.04%) over 64/255,
all on glyph anti-aliasing edges.

## Font licence

Paperlogy, Copyright 2024 The PAPERLOGY Authors, is licensed under the SIL Open Font License 1.1.
See `frontend/fonts/OFL-Paperlogy.txt` and `frontend/fonts/README.md`. The SVGs and PNGs contain
only the outlines of the glyphs in "claimback my money."; no font file is embedded.
