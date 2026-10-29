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


def render_player(bundle: dict, player_dir: Path = PLAYER_DIR) -> str:
    html = (player_dir / "player.html").read_text()
    css, js = (player_dir / "player.css").read_text(), (player_dir / "player.js").read_text()
    # The bundle goes in last so nothing inside it can be mistaken for a placeholder.
    return (html.replace("/*__CSS__*/", css).replace("/*__JS__*/", js)
            .replace("__BUNDLE__", _json_for_script(bundle)))


def assets_stamp(player_dir: Path = PLAYER_DIR) -> float:
    """Changes whenever a player file changes (lets Streamlit's cache notice edits)."""
    return max(f.stat().st_mtime for f in player_dir.glob("player.*"))
