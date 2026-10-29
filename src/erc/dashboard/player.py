"""Render the replay player as one self-contained HTML page (no CDN, works offline).

The player's markup, styles and script live in dashboard/player/; this module inlines them and the
JSON bundle from export.py. Streamlit then shows the result with st.components.v1.html.
"""
from __future__ import annotations

import json
from pathlib import Path

from erc.dashboard.replay import ROOT

PLAYER_DIR = ROOT / "dashboard" / "player"


def _json_for_script(bundle: dict) -> str:
    """JSON that is safe inside a <script> tag."""
    return json.dumps(bundle, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--")


def render_player(bundle: dict, player_dir: Path = PLAYER_DIR, embed: bool = False) -> str:
    """The player page. embed=True is the compact map + KPI cards view used inside the Compare page."""
    html = (player_dir / "player.html").read_text()
    if embed:
        html = html.replace('<body tabindex="0">', '<body tabindex="0" class="embed">')
    css, js = (player_dir / "player.css").read_text(), (player_dir / "player.js").read_text()
    # The bundle goes in last so nothing inside it can be mistaken for a placeholder.
    return (html.replace("/*__CSS__*/", css).replace("/*__JS__*/", js)
            .replace("__BUNDLE__", _json_for_script(bundle)))


def assets_stamp(player_dir: Path = PLAYER_DIR) -> float:
    """Changes whenever a player file changes (lets Streamlit's cache notice edits)."""
    return max(f.stat().st_mtime for f in player_dir.glob("*.*"))


def render_compare(left: dict, right: dict, difference: dict | None, player_dir: Path = PLAYER_DIR) -> str:
    """Two embedded players on one clock. left/right: {label, bundle}; difference: first_difference() or None."""
    side = lambda s: {"label": s["label"], "html": render_player(s["bundle"], player_dir, embed=True),
                      "last": s["bundle"]["meta"]["last_minute"],
                      "conflicts": [{"t": c["t"], "text": c["text"]} for c in s["bundle"]["conflicts"]]}
    data = {"a": side(left), "b": side(right), "diff": difference}
    html = (player_dir / "compare.html").read_text()
    css = (player_dir / "player.css").read_text() + (player_dir / "compare.css").read_text()
    js = (player_dir / "compare.js").read_text()
    return html.replace("/*__CSS__*/", css).replace("/*__JS__*/", js).replace("__DATA__", _json_for_script(data))


# ───────── The redesigned Replay app (dashboard/replay_app) ─────────
APP_DIR = ROOT / "dashboard" / "replay_app"
ASSETS_DIR = ROOT / "dashboard" / "assets"
FONT_FILES = {400: "Inter-Regular.woff2", 500: "Inter-Medium.woff2", 600: "Inter-SemiBold.woff2"}
ICON_NAMES = ["map", "git-compare", "sliders-horizontal", "chart-column", "messages-square", "play", "pause", "rotate-ccw", "siren",
              "activity", "users", "clock", "triangle-alert", "hospital", "circle-check", "flag", "chevron-down", "chevron-left",
              "chevron-right", "brain-circuit", "shield-check", "ambulance", "flame", "heart-pulse", "x"]


def fonts_css(assets_dir: Path = ASSETS_DIR) -> str:
    """@font-face rules with the Inter files embedded, so the app works offline and inside an iframe."""
    import base64
    rules = []
    for weight, name in FONT_FILES.items():
        data = base64.b64encode((assets_dir / "fonts" / name).read_bytes()).decode()
        rules.append(f'@font-face {{ font-family: "Inter"; font-weight: {weight}; font-display: block; '
                     f'src: url(data:font/woff2;base64,{data}) format("woff2"); }}')
    return "\n".join(rules)


def icon_sprite(names: list[str] = ICON_NAMES, assets_dir: Path = ASSETS_DIR) -> str:
    """One <symbol> per Lucide icon, used as <svg><use href="#i-name"/></svg>."""
    symbols = []
    for name in names:
        svg = (assets_dir / "icons" / f"{name}.svg").read_text()
        inner = svg.split(">", 2)[2] if svg.startswith("<!--") else svg.split(">", 1)[1]
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{inner.rsplit("</svg>", 1)[0]}</symbol>')
    return '<svg width="0" height="0" style="position:absolute" aria-hidden="true">' + "".join(symbols) + "</svg>"


def render_replay_app(bundle: dict, catalog: dict, app_dir: Path = APP_DIR, assets_dir: Path = ASSETS_DIR) -> str:
    """The full-window Replay page as one self-contained HTML document (fonts, icons, data all inlined)."""
    html = (app_dir / "app.html").read_text()
    css = (app_dir / "app.css").read_text().replace("/*__FONTS__*/", fonts_css(assets_dir))
    js = (app_dir / "app.js").read_text()
    # The data goes in last so nothing inside it can be mistaken for a placeholder.
    return (html.replace("/*__CSS__*/", css).replace("/*__JS__*/", js).replace("__SPRITE__", icon_sprite(assets_dir=assets_dir))
            .replace("__BUNDLE__", _json_for_script(bundle)).replace("__CATALOG__", _json_for_script(catalog)))


def app_stamp(app_dir: Path = APP_DIR) -> float:
    """Changes whenever an app file changes (lets Streamlit's cache notice edits)."""
    return max(f.stat().st_mtime for f in app_dir.glob("app.*"))
