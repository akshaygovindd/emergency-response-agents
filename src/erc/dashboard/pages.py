"""Shared building blocks for the redesigned dashboard pages (Compare, What-if, Results, Negotiations, Replay).

Every page is one self-contained HTML document: tokens/components from dashboard/ui/base.css, helpers from
dashboard/ui/base.js, the page's own files, the Lucide icon sprite, the Inter fonts and the page's data, all inlined
(works offline, inside a Streamlit iframe). Python computes the data; the page only draws it.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from erc.dashboard.replay import ROOT

DASHBOARD = ROOT / "dashboard"
UI_DIR = DASHBOARD / "ui"
ASSETS_DIR = DASHBOARD / "assets"
FONT_FILES = {400: "Inter-Regular.woff2", 500: "Inter-Medium.woff2", 600: "Inter-SemiBold.woff2"}


def json_for_script(data) -> str:
    """JSON that is safe inside a <script> tag."""
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--")


def fonts_css(assets_dir: Path = ASSETS_DIR) -> str:
    rules = []
    for weight, name in FONT_FILES.items():
        data = base64.b64encode((assets_dir / "fonts" / name).read_bytes()).decode()
        rules.append(f'@font-face {{ font-family: "Inter"; font-weight: {weight}; font-display: block; '
                     f'src: url(data:font/woff2;base64,{data}) format("woff2"); }}')
    return "\n".join(rules)


def icon_sprite(assets_dir: Path = ASSETS_DIR) -> str:
    """Every bundled Lucide icon as a <symbol> (used as <svg><use href="#i-name"/></svg>)."""
    symbols = []
    for path in sorted((assets_dir / "icons").glob("*.svg")):
        svg = path.read_text()
        inner = svg.split(">", 2)[2] if svg.startswith("<!--") else svg.split(">", 1)[1]
        symbols.append(f'<symbol id="i-{path.stem}" viewBox="0 0 24 24">{inner.rsplit("</svg>", 1)[0]}</symbol>')
    return '<svg width="0" height="0" style="position:absolute" aria-hidden="true">' + "".join(symbols) + "</svg>"


def base_css(assets_dir: Path = ASSETS_DIR, ui_dir: Path = UI_DIR) -> str:
    return (ui_dir / "base.css").read_text().replace("/*__FONTS__*/", fonts_css(assets_dir))


def render_page(page_dir: Path, data: dict, *, body_class: str = "", assets_dir: Path = ASSETS_DIR, ui_dir: Path = UI_DIR) -> str:
    """page_dir holds page.html (with /*__CSS__*/, /*__JS__*/, __SPRITE__, __DATA__), page.css and page.js."""
    html = (page_dir / "page.html").read_text()
    css = base_css(assets_dir, ui_dir) + "\n" + (page_dir / "page.css").read_text()
    js = (ui_dir / "base.js").read_text() + "\n" + (page_dir / "page.js").read_text()
    if body_class:
        html = html.replace("<body", f'<body class="{body_class}"', 1)
    # The data goes in last so nothing inside it can be mistaken for a placeholder.
    return (html.replace("/*__CSS__*/", css).replace("/*__JS__*/", js).replace("__SPRITE__", icon_sprite(assets_dir))
            .replace("__DATA__", json_for_script(data)))


def page_stamp(page_dir: Path, ui_dir: Path = UI_DIR) -> float:
    """Changes whenever one of the page's files (or the shared base) changes, so Streamlit's cache notices edits."""
    files = [*page_dir.glob("page.*"), *ui_dir.glob("base.*"), *page_dir.glob("*.py")]
    return max(f.stat().st_mtime for f in files)


FULL_WINDOW_CSS = """<style>
header[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stStatusWidget"],
[data-testid="stToolbar"],[data-testid="stDecoration"],footer{display:none !important}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#0A0E17}
.block-container{padding:0 !important;max-width:100% !important}
iframe{position:fixed;inset:0;width:100vw !important;height:100vh !important;border:0;z-index:5}
</style>"""
