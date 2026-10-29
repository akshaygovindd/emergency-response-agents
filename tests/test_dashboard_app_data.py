"""Tests: data logic added for the redesigned Replay app (plain wording, timeline, spread markers, run catalog)."""
import math
from pathlib import Path

import pytest

from erc.dashboard.catalog import resolve_selection, run_catalog
from erc.dashboard.export import export_replay
from erc.dashboard.replay import LOGS_DIR, RunRef
from erc.dashboard.spread import GRID_KM, MAX_SHIFT_KM, MIN_SEPARATION_KM, spread_positions
from erc.dashboard.story import plain_text
from erc.dashboard.timeline import timeline_items


# ───────── plain wording ─────────
def test_plain_text_replaces_ids_and_drops_victim_lists():
    assert plain_text("send AMB-03 to INC-01 (V-01-1)") == "send Ambulance 3 to Incident 1"
    assert plain_text("INC-01 and INC-02 both want AMB-01") == "Incident 1 and Incident 2 both want Ambulance 1"
    assert plain_text("send RESCUE-1 to INC-02") == "send Rescue team to Incident 2"
    assert plain_text("Resource Alloc. offers AMB-03") == "Resource Allocation offers Ambulance 3"


def test_plain_text_turns_bare_victim_lists_into_counts():
    assert plain_text("admit V-02-1, V-02-2 to H-T") == "admit 2 patients to Trauma Center"
    assert plain_text("admit V-04-1 to H-G") == "admit 1 patient to General Hospital"


# ───────── timeline ─────────
def row(i, kind, text, who="Dispatch", why="because"):
    return {"i": i, "t": 6, "id": f"t006-M{i:04d}", "from": who, "to": "x", "type": kind, "badge": kind.upper(), "text": text, "why": why}


def test_timeline_groups_executed_lines_and_skips_commits():
    rows = [row(0, "proposal", "send AMB-05 to INC-02 (V-02-3)"), row(1, "commit", "send AMB-05 to INC-02"),
            row(2, "executed", "sent AMB-05 to INC-02 (V-02-3)", "System"), row(3, "executed", "sent RESCUE-1 to INC-02", "System"),
            row(4, "reject", "send AMB-01 to INC-01 (V-01-1)", "Resource Alloc.")]
    items = timeline_items(rows)
    assert [i["text"] for i in items] == ["Proposed to send Ambulance 5 to Incident 2", "Dispatched Ambulance 5 and Rescue team",
                                          "Declined: Ambulance 1 to Incident 1"]
    group = items[1]
    assert (group["a"], group["b"]) == (2, 3) and group["who"] == "System" and "t006-M0002" in group["tip"]
    assert items[2]["who"] == "Resource Allocation" and items[2]["icon"] == "sliders-horizontal" and items[2]["tag"] == "Declined"


def test_timeline_keeps_internal_ids_out_of_the_sentence():
    for item in timeline_items([row(0, "counter", "send AMB-03 to INC-01 (V-01-1)", "Resource Alloc.")]):
        assert "AMB-" not in item["text"] and "INC-" not in item["text"] and "t006" not in item["text"] and "t006" in item["tip"]


def test_real_run_timeline_covers_every_non_commit_message():
    if not (LOGS_DIR / "v1" / "negotiation" / "normal_seed42_negotiation.jsonl").exists():
        pytest.skip("saved run not available")
    b = export_replay("v1", "normal", 42, "negotiation")
    covered = set()
    for item in b["timeline"]:
        covered.update(range(item["a"], item["b"] + 1))
    assert all(m["i"] in covered for m in b["messages"] if m["type"] != "commit")
    assert all(item["b"] < len(b["messages"]) for item in b["timeline"])
    conflict = b["conflicts"][0]
    assert conflict["plain"] == "Incident 1 and Incident 2 both want Ambulance 1" and all(s["plain"] for s in conflict["stages"])


# ───────── spread markers ─────────
def test_spread_separates_close_markers_and_leaves_others_alone():
    far = (3.0, 3.0)
    out = spread_positions([(7.5, 10.0), (7.2, 10.5), far])
    assert math.dist(out[0], out[1]) >= MIN_SEPARATION_KM - 0.05
    assert out[2] == far
    assert all(math.dist(a, b) <= MAX_SHIFT_KM + 0.01 for a, b in zip(out, [(7.5, 10.0), (7.2, 10.5), far]))


def test_spread_is_deterministic_and_handles_identical_points_and_edges():
    pts = [(5.0, 5.0), (5.0, 5.0), (0.1, 19.9)]
    assert spread_positions(pts) == spread_positions(pts)
    out = spread_positions(pts)
    assert out[0] != out[1] and all(0 < x < GRID_KM and 0 < y < GRID_KM for x, y in out)


def test_every_saved_run_has_spread_incident_positions():
    for run in [r for r in __import__("erc.dashboard.replay", fromlist=["x"]).available_runs() if r.mode == "negotiation"][:6]:
        b = export_replay(run.version, run.scenario, run.seed, run.mode)
        assert all("map_x" in i and "map_y" in i for i in b["incidents"])
        for a in range(len(b["incidents"])):
            for c in range(a + 1, len(b["incidents"])):
                ia, ic = b["incidents"][a], b["incidents"][c]
                assert math.dist((ia["map_x"], ia["map_y"]), (ic["map_x"], ic["map_y"])) > 1.4
        assert all(i["x"] is not None for i in b["incidents"])       # true positions are kept


# ───────── run catalog ─────────
def refs():
    return [RunRef(v, s, 41 + n, m, Path("x")) for v, s, n, m in
            [("v2", "surge", 2, "negotiation"), ("v1", "normal", 1, "greedy"), ("v1", "normal", 1, "negotiation"),
             ("v1", "bottleneck", 1, "agents"), ("v1", "normal", 2, "negotiation")]]


def test_catalog_is_nested_and_ordered():
    cat = run_catalog(refs())
    assert list(cat) == ["v1", "v2"] and list(cat["v1"]) == ["normal", "bottleneck"]
    assert cat["v1"]["normal"] == {"1": ["greedy", "negotiation"], "2": ["negotiation"]}


def test_resolve_selection_keeps_valid_requests_and_falls_back_otherwise():
    cat = run_catalog(refs())
    assert resolve_selection(cat, "v1", "normal", "2", "negotiation") == ("v1", "normal", "2", "negotiation")
    assert resolve_selection(cat, "v1", "normal", "2", "greedy") == ("v1", "normal", "2", "negotiation")      # mode missing for that run
    assert resolve_selection(cat, "v9", None, None, None) == ("v1", "normal", "1", "negotiation")
    assert resolve_selection(cat, "v2", "normal", "1", "naive") == ("v2", "surge", "2", "negotiation")


# ───────── the app page ─────────
def test_render_replay_app_is_self_contained():
    from erc.dashboard.player import render_replay_app
    if not (LOGS_DIR / "v1" / "negotiation" / "normal_seed42_negotiation.jsonl").exists():
        pytest.skip("saved run not available")
    from erc.dashboard.replay import available_runs
    html = render_replay_app(export_replay("v1", "normal", 42, "negotiation"), run_catalog(available_runs()))
    for placeholder in ("/*__CSS__*/", "/*__JS__*/", "/*__FONTS__*/", "__SPRITE__", "__BUNDLE__", "__CATALOG__"):
        assert placeholder not in html
    assert "data:font/woff2;base64," in html and 'id="i-heart-pulse"' in html and 'id="i-ambulance"' in html
    assert 'src="http' not in html and "https://" not in html.replace("http://www.w3.org", "")      # nothing is loaded from the network


def test_expectant_icon_differs_from_the_conflict_icon():
    js = (Path(__file__).resolve().parents[1] / "dashboard" / "replay_app" / "app.js").read_text()
    assert 'kpi("", "heart-pulse"' in js and 'kpi("w3", "git-compare"' in js and 'triangle-alert' in js
    assert '"Expectant"' in js and js.index('"heart-pulse"') < js.index('"Conflicts"')


def test_app_has_resources_row_and_unit_legend():
    js = (Path(__file__).resolve().parents[1] / "dashboard" / "replay_app" / "app.js").read_text()
    for needle in ("Ambulances", "Response teams", '["transporting", "transporting"]', '"on_scene", "on scene"', "ALS ambulance" if False else "ALS",
                   'ico("ambulance", 16)', 'ico("users", 16)', 'ico("hospital", 16)', "Response team"):
        assert needle in js, needle


def test_executed_lines_are_grouped_in_plain_words_without_mixed_lists():
    rows = [row(0, "executed", "sent AMB-03 to INC-01 (V-01-1)", "System"), row(1, "executed", "sent AMB-05 to INC-02", "System"),
            row(2, "executed", "admitted V-04-1, V-04-3 to H-T", "System"), row(3, "executed", "admitted V-05-1 to H-G", "System")]
    (item,) = timeline_items(rows)
    assert item["text"] == "Dispatched Ambulance 3 and Ambulance 5 · admitted 3 patients"
    assert (item["a"], item["b"]) == (0, 3) and "t006-M0002" in item["tip"]
    (only_admit,) = timeline_items([row(0, "executed", "admitted V-04-1 to H-T", "System")])
    assert only_admit["text"] == "Admitted 1 patient"


def test_executed_lines_from_different_minutes_stay_separate():
    a, b = row(0, "executed", "sent AMB-01 to INC-01", "System"), row(1, "executed", "sent AMB-02 to INC-02", "System")
    b["t"] = 9
    assert [i["text"] for i in timeline_items([a, b])] == ["Dispatched Ambulance 1", "Dispatched Ambulance 2"]


def test_orange_is_reserved_for_conflicts_in_the_replay_app():
    js = (Path(__file__).resolve().parents[1] / "dashboard" / "replay_app" / "app.js").read_text()
    assert 'transporting: "var(--violet)"' in js and '"Moderate": "var(--moderate)"' in js
    assert 'u.pulse.style.display = hot ? "" : "none"' in js                       # the ring is shown only for a unit in a conflict
    assert 'fill: "var(--warn)" }, g); als.textContent' not in js
