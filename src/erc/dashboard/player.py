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
