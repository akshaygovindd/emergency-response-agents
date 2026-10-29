"""Tests: shared page rendering and the data behind the redesigned Compare page."""
import json
from pathlib import Path

import pytest

from erc.dashboard.compare import first_difference
from erc.dashboard.export import export_replay
from erc.dashboard.pages import base_css, icon_sprite, json_for_script, render_page
from erc.dashboard.player import render_replay_app
from erc.dashboard.replay import LOGS_DIR

ROOT = Path(__file__).resolve().parents[1]
RUN = LOGS_DIR / "v1" / "negotiation" / "normal_seed42_negotiation.jsonl"


def test_json_for_script_cannot_close_the_script_tag():
    assert "</script>" not in json_for_script({"x": "</script><!--"})


def test_base_assets_are_inlined_and_complete():
    css = base_css()
    assert "data:font/woff2;base64," in css and "/*__FONTS__*/" not in css and "--accent: #6366F1" in css
    sprite = icon_sprite()
    for name in ("play", "heart-pulse", "flag", "plus", "minus", "code", "flask-conical", "chart-column", "messages-square"):
        assert f'id="i-{name}"' in sprite, name


def test_render_page_replaces_every_placeholder(tmp_path):
    (tmp_path / "page.html").write_text("<html><body><style>/*__CSS__*/</style>__SPRITE__<script>/*__JS__*/</script><i>__DATA__</i></body></html>")
    (tmp_path / "page.css").write_text(".x{}")
    (tmp_path / "page.js").write_text("console.log(1)")
    html = render_page(tmp_path, {"a": 1}, body_class="mode-x")
    assert 'class="mode-x"' in html and '"a":1' in html and "window.UI" in html and ".x{}" in html
    assert "/*__" not in html and "__SPRITE__" not in html and "__DATA__" not in html


@pytest.mark.skipif(not RUN.exists(), reason="saved run not available")
def test_replay_app_modes_are_set_on_the_body():
    bundle = export_replay("v1", "normal", 42, "negotiation")
    for mode in ("compare", "inline"):
        assert f'class="mode-{mode}"' in render_replay_app(bundle, {}, mode=mode)
    assert "mode-" not in render_replay_app(bundle, {}).split("</style>")[1].split("<script")[0]


def test_first_difference_card_text_is_plain():
    def accepted(t, incident, ambulance):
        return {"t": t, "kind": "action_accepted", "incident_id": incident, "source": "dispatch", "message_id": "m",
                "action": {"action_type": "assign_ambulance", "ambulance_id": ambulance, "victim_ids": ["V-02-1"]}}
    diff = first_difference([accepted(6, "INC-02", "AMB-01")], [accepted(6, "INC-02", "AMB-05")], "Greedy", "Negotiation")
    assert diff["a_plain"] == ["sent Ambulance 1 to Incident 2"] and diff["b_plain"] == ["sent Ambulance 5 to Incident 2"]
    assert "AMB-" not in " ".join(diff["a_plain"] + diff["b_plain"])


@pytest.mark.skipif(not RUN.exists(), reason="saved run not available")
def test_compare_page_files_exist_and_use_the_shared_shell():
    page = (ROOT / "dashboard" / "compare_app" / "page.js").read_text()
    assert "UI.mountRail(\"Compare\")" in page and "UI.runPicker" in page and "contentWindow.__app" in page
    html = (ROOT / "dashboard" / "compare_app" / "page.html").read_text()
    assert 'id="frameA"' in html and 'id="frameB"' in html and 'id="diff"' in html and 'class="playbar"' in html
