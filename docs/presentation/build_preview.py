"""Assemble the deck into one standalone ``deck.html`` for local preview.

The slides under ``project/`` are kept in the Slides artifact format so they
can be published back to claude.ai unchanged. That format leans on its
runtime for a few things this script approximates:

- ``/_blob/<id>`` image sources are rewritten to ``assets/<id>.<ext>``;
- ``<x-icon>`` and ``<x-connector>`` become simple inline stand-ins;
- each 1920x1080 slide is scaled to the window width;
- speaker notes (``<aside>``) are shown under their slide.

Usage::

    python docs/presentation/build_preview.py
    open docs/presentation/deck.html
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "project"
ASSETS = HERE / "assets"
OUT = HERE / "deck.html"

BLOB = re.compile(r"/_blob/([0-9a-f]{32})")
ICON = re.compile(r"<x-icon\b([^>]*)>\s*</x-icon>")
CONNECTOR = re.compile(r"<x-connector\b([^>]*)>\s*</x-connector>")
STYLE = re.compile(r'style="([^"]*)"')


def _asset_paths() -> dict[str, str]:
    return {p.stem: f"assets/{p.name}" for p in ASSETS.iterdir() if p.is_file()}


def _style_of(attrs: str) -> str:
    m = STYLE.search(attrs)
    return m.group(1) if m else ""


def _render_slide(html: str, assets: dict[str, str]) -> str:
    def blob(m: re.Match[str]) -> str:
        blob_id = m.group(1)
        if blob_id not in assets:
            raise SystemExit(f"missing asset for /_blob/{blob_id} in {ASSETS}")
        return assets[blob_id]

    html = BLOB.sub(blob, html)
    html = ICON.sub(
        lambda m: (
            f'<span class="x-icon" style="{_style_of(m.group(1))}">'
            '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="6"/></svg></span>'
        ),
        html,
    )
    html = CONNECTOR.sub(
        lambda m: f'<span class="x-connector" style="{_style_of(m.group(1))}"></span>',
        html,
    )
    return html


def build() -> Path:
    deck = json.loads((PROJECT / "deck.json").read_text(encoding="utf-8"))
    assets = _asset_paths()
    slides_dir = PROJECT / "slides"

    order = list(deck["order"])
    # A slide file the index leaves out still shows, last (Slides semantics).
    order += sorted(p.stem for p in slides_dir.glob("*.html") if p.stem not in order)

    fonts = "\n".join(
        f'<link rel="stylesheet" href="{face["href"]}">'
        for face in deck.get("faces", {}).values()
        if "href" in face
    )
    frames = "\n".join(
        '<div class="frame"><div class="stage">'
        + _render_slide((slides_dir / f"{sid}.html").read_text(encoding="utf-8"), assets)
        + "</div></div>"
        for sid in order
    )

    OUT.write_text(
        f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{deck["title"]}</title>
{fonts}
<style>
  body {{ margin: 0; background: #1b1c2a; color: #e6e7f2; font-family: Inter, Arial, sans-serif; }}
  .frame {{ max-width: 1280px; margin: 24px auto; }}
  .stage {{ position: relative; width: 100%; aspect-ratio: 16 / 9; overflow: hidden; }}
  .stage > section {{ position: absolute; top: 0; left: 0; width: 1920px; height: 1080px;
                      box-sizing: border-box; transform-origin: 0 0; overflow: hidden; }}
  .stage > section * {{ margin: 0; box-sizing: border-box; }}
  .stage > section > aside {{ display: none; }}
  .notes {{ font-size: 15px; line-height: 1.5; color: #b7bae0; padding: 12px 4px 0; white-space: pre-wrap; }}
  .x-icon {{ display: inline-flex; }}
  .x-icon svg {{ width: 100%; height: 100%; fill: currentColor; }}
  .x-connector {{ display: inline-block; flex: none; height: 2px; background: currentColor; position: relative; }}
  .x-connector::after {{ content: ""; position: absolute; right: -2px; top: -5px;
                         border: 6px solid transparent; border-left-color: currentColor; border-right: 0; }}
</style>
</head>
<body>
{frames}
<script>
  for (const stage of document.querySelectorAll(".stage")) {{
    const section = stage.querySelector("section");
    const aside = section.querySelector(":scope > aside");
    if (aside) {{
      const notes = document.createElement("div");
      notes.className = "notes";
      notes.textContent = section.id + " · " + aside.textContent.trim();
      stage.after(notes);
    }}
  }}
  const fit = () => document.querySelectorAll(".stage").forEach(stage => {{
    stage.firstElementChild.style.transform = `scale(${{stage.clientWidth / 1920}})`;
  }});
  addEventListener("resize", fit);
  fit();
</script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return OUT


if __name__ == "__main__":
    print(f"wrote {build()}")
