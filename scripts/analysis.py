"""Final analysis, computed from saved results and logs only (no simulation, no API calls).

Reads  results/<version>/runs.jsonl, logs/<version>/<mode>/*.jsonl and data/scenarios/*.json.
Writes results/analysis/*.csv and results/analysis/*.png (never anything under results/v1, results/v2 or logs/).
Every table has a `version` column; v1 and v2 are never pooled.

    python scripts/analysis.py            # all tables and figures
    python scripts/analysis.py --no-figures

Per-victim first contact is not stored in the logs, so `victim_outcomes` rebuilds it from the same events the
engine used (ambulance arrival on scene, medical team arrival) and `verify_reconstruction` checks that it
reproduces every run's critical service rate and mean response time in results/<version>/runs.jsonl.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from erc.config import LOG_DIR, PROJECT_ROOT, RESULTS_DIR, SCENARIO_DIR
from erc.dashboard.compare import first_difference
from erc.dashboard.results_view import SCENARIOS, SYSTEMS, csr_table, paired_table, triage_table
from erc.dashboard.story import feed_text, plain_text
from erc.eval.experiment import load_runs
from erc.eval.stats import paired_comparison, summarize

OUT = RESULTS_DIR / "analysis"
VERSIONS = ("v1", "v2")
AGENT_MODES = ("agents", "negotiation")
HORIZON_H = 2.0                      # 120-minute runs

# Dashboard design-system colours (docs/design/DESIGN_SYSTEM.md)
BG, PANEL, GRID, TEXT, TEXT2, TEXT3 = "#0A0E17", "#101624", "#1B2438", "#E6EAF2", "#9AA6BA", "#66728A"
SYS_COLOR = {"naive": "#53627A", "greedy": "#94A3B8", "agents": "#8B8EF6", "negotiation": "#6366F1", "oracle": "#A78BFA"}
SYS_LABEL = {"naive": "Naive", "greedy": "Greedy", "agents": "Agents (no negotiation)", "negotiation": "Negotiation", "oracle": "Oracle"}
SC_LABEL = {"normal": "Normal", "surge": "Surge", "bottleneck": "Bottleneck"}
TRIAGE_COLOR = {"Immediate": "#EF4444", "Delayed": "#FACC15", "Minor": "#22C55E"}
OK, WARN, DANGER = "#2DD4BF", "#FB923C", "#FB7185"
VERSION_COLOR = {"v1": "#94A3B8", "v2": "#6366F1"}


# ───────────────────────── Loading ─────────────────────────
def load_events(version: str, mode: str, scenario: str, seed: int) -> list[dict]:
    path = LOG_DIR / version / mode / f"{scenario}_seed{seed}_{mode}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def load_scenario(scenario: str, seed: int) -> dict:
    return json.loads((SCENARIO_DIR / f"{scenario}_seed{seed}.json").read_text())


def run_index(runs: list[dict]) -> dict[tuple[str, int, str], dict]:
    return {(r["scenario"], r["seed"], r["mode"]): r for r in runs}


def paired_seeds(idx: dict, scenario: str, a: str, b: str) -> list[int]:
    return sorted(s for (sc, s, m) in idx if sc == scenario and m == a and (scenario, s, b) in idx)


# ───────────────────────── Per-victim outcomes (rebuilt from the log) ─────────────────────────
def victim_outcomes(events: list[dict], scenario: dict) -> dict[str, dict]:
    """victim_id -> {incident, severity, critical, deadline, arrival, contact, unit, response, in_time,
    assign_t, assign_unit}. Mirrors Engine: an ambulance's arrival contacts the victims it was assigned,
    a medical team's arrival contacts every victim of the incident; the earliest contact counts."""
    info, arrival, incident_of = {}, {}, {}
    for inc in scenario["incidents"]:
        arrival[inc["incident_id"]] = inc["arrival_time_min"]
        for v in inc["victims"]:
            incident_of[v["victim_id"]] = inc["incident_id"]
            info[v["victim_id"]] = {"incident": inc["incident_id"], "severity": int(v["severity"]), "critical": int(v["severity"]) >= 4,
                                    "deadline": v["deadline_min"], "arrival": inc["arrival_time_min"],
                                    "contact": None, "unit": None, "assign_t": None, "assign_unit": None}
    medical = {r["team_id"] for r in scenario["responders"] if r["responder_type"] == "medical"}
    assigns = [e for e in events if e["kind"] == "action_accepted" and e["action"]["action_type"] == "assign_ambulance"]
    for e in assigns:
        for vid in e["action"]["victim_ids"]:
            if info[vid]["assign_t"] is None:
                info[vid]["assign_t"], info[vid]["assign_unit"] = e["t"], e["action"]["ambulance_id"]

    def contact(vid: str, t: int, unit: str) -> None:
        if info[vid]["contact"] is None or t < info[vid]["contact"]:
            info[vid]["contact"], info[vid]["unit"] = t, unit

    for e in events:
        if e["kind"] == "ambulance_on_scene":
            prior = [a for a in assigns if a["action"]["ambulance_id"] == e["ambulance_id"]
                     and a["incident_id"] == e["incident_id"] and a["t"] <= e["t"]]
            if prior:
                for vid in prior[-1]["action"]["victim_ids"]:
                    contact(vid, e["t"], e["ambulance_id"])
        elif e["kind"] == "responder_arrived" and e["team_id"] in medical:
            for vid, v in info.items():
                if v["incident"] == e["incident_id"]:
                    contact(vid, e["t"], e["team_id"])
    for v in info.values():
        v["response"] = None if v["contact"] is None else v["contact"] - v["arrival"]
        v["in_time"] = v["response"] is not None and v["response"] <= v["deadline"]
    return info


def outcome_summary(outcomes: dict[str, dict]) -> dict:
    crit = [v for v in outcomes.values() if v["critical"]]
    resp = [v["response"] for v in outcomes.values() if v["response"] is not None]
    cresp = [v["response"] for v in crit if v["response"] is not None]
    return {"n_critical": len(crit), "critical_in_time": sum(v["in_time"] for v in crit),
            "csr": (sum(v["in_time"] for v in crit) / len(crit)) if crit else None,
            "response_mean": float(np.mean(resp)) if resp else None,
            "critical_response_mean": float(np.mean(cresp)) if cresp else None}


def verify_reconstruction(version: str, runs: list[dict]) -> pd.DataFrame:
    """One row per run: does the rebuilt critical service rate / mean response match results/<version>/runs.jsonl?"""
    rows = []
    for r in runs:
        s = outcome_summary(victim_outcomes(load_events(version, r["mode"], r["scenario"], r["seed"]), load_scenario(r["scenario"], r["seed"])))
        csr_ok = (s["csr"] is None and r["critical_service_rate"] is None) or abs((s["csr"] or 0) - (r["critical_service_rate"] or 0)) < 1e-9
        resp_ok = abs((s["response_mean"] or 0) - (r["response_mean"] or 0)) < 1e-9
        rows.append({"version": version, "run_id": r["run_id"], "csr_matches": csr_ok, "response_matches": resp_ok})
    return pd.DataFrame(rows)


# ───────────────────────── 1. Headline tables ─────────────────────────
def with_version(df: pd.DataFrame, version: str) -> pd.DataFrame:
    df = df.copy()
    df.insert(0, "version", version)
    return df


def headline_tables(all_runs: dict[str, list[dict]]) -> dict[str, pd.DataFrame]:
    csr, rq1, rq2, oracle, triage = [], [], [], [], []
    for v, runs in all_runs.items():
        csr.append(with_version(csr_table(runs), v))
        for mode in ("naive", "agents", "negotiation", "oracle"):
            t = paired_table(runs, mode, "greedy")
            if not t.empty:
                rq1.append(with_version(t, v))
        t = paired_table(runs, "negotiation", "agents")
        rq2.append(with_version(t, v))
        t = paired_table(runs, "oracle", "negotiation")
        if not t.empty:
            oracle.append(with_version(t, v))
        triage.append(with_version(triage_table(runs), v))
    concat = lambda parts: pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return {"01_csr": concat(csr), "01_rq1_paired_vs_greedy": concat(rq1), "01_rq2_negotiation_vs_agents": concat(rq2),
            "01_oracle_ablation": concat(oracle), "01_triage_by_color": concat(triage)}


# ───────────────────────── 2. First divergence ─────────────────────────
def conflict_trigger(events: list[dict], t: int) -> str:
    """What happened in this run at minute t that explains a different decision."""
    conflicts = [e for e in events if e["kind"] == "conflict_resolved" and e["t"] == t]
    if conflicts:
        detected = {e["conflict_id"]: e for e in events if e["kind"] == "conflict_detected"}
        parts = []
        for c in conflicts:
            counter = any(m["kind"] == "agent_message" and m["t"] == t and m.get("negotiation_id") == c["conflict_id"]
                          and m["message_type"] == "counter_proposal" for m in events)
            kind = detected[c["conflict_id"]]["conflict_type"]
            parts.append(f"{kind} conflict {c['conflict_id']} resolved by {c['method']}" + (" after a counter-offer" if counter else ""))
        return "; ".join(parts)
    adm = [e for e in events if e["kind"] == "admission_resolved" and e["t"] == t and e["method"] != "accepted"]
    if adm:
        return "admission " + ", ".join(sorted({e["method"] for e in adm}))
    return "no conflict or admission negotiation at this minute"


def divergence_table(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for v, runs in all_runs.items():
        idx = run_index(runs)
        for scenario in SCENARIOS:
            for seed in paired_seeds(idx, scenario, "agents", "negotiation"):
                ev_a = load_events(v, "agents", scenario, seed)
                ev_n = load_events(v, "negotiation", scenario, seed)
                sc = load_scenario(scenario, seed)
                oa, on = victim_outcomes(ev_a, sc), victim_outcomes(ev_n, sc)
                sa, sn = outcome_summary(oa), outcome_summary(on)
                diff = first_difference(ev_a, ev_n, "Agents", "Negotiation")
                row = {"version": v, "scenario": scenario, "seed": seed, "diverged": diff is not None,
                       "first_minute": diff["t"] if diff else None,
                       "agents_did": " | ".join(plain_text(x) for x in diff["a"]) if diff else "",
                       "negotiation_did": " | ".join(plain_text(x) for x in diff["b"]) if diff else "",
                       "trigger_negotiation_run": conflict_trigger(ev_n, diff["t"]) if diff else "",
                       "trigger_agents_run": conflict_trigger(ev_a, diff["t"]) if diff else "",
                       "critical": sa["n_critical"], "critical_in_time_agents": sa["critical_in_time"],
                       "critical_in_time_negotiation": sn["critical_in_time"],
                       "csr_agents": sa["csr"], "csr_negotiation": sn["csr"],
                       "csr_diff": (sn["csr"] or 0) - (sa["csr"] or 0),
                       "critical_response_agents": sa["critical_response_mean"], "critical_response_negotiation": sn["critical_response_mean"],
                       "response_mean_agents": sa["response_mean"], "response_mean_negotiation": sn["response_mean"]}
                gained = [vid for vid in on if on[vid]["critical"] and on[vid]["in_time"] and not oa[vid]["in_time"]]
                lost = [vid for vid in on if on[vid]["critical"] and oa[vid]["in_time"] and not on[vid]["in_time"]]
                row.update(victims_gained=" ".join(gained), victims_lost=" ".join(lost))
                row["verdict"] = ("no divergence" if diff is None else
                                  "helped" if row["csr_diff"] > 1e-12 else "hurt" if row["csr_diff"] < -1e-12 else "tied")
                rows.append(row)
    return pd.DataFrame(rows)


def divergence_summary(div: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (v, sc), g in list(div.groupby(["version", "scenario"], sort=False)) + [((v, "all"), g) for v, g in div.groupby("version")]:
        d = g[g["diverged"]]
        rows.append({"version": v, "scenario": sc, "paired_runs": len(g), "diverged": len(d), "never_diverged": len(g) - len(d),
                     "helped": int((d["verdict"] == "helped").sum()), "hurt": int((d["verdict"] == "hurt").sum()),
                     "tied": int((d["verdict"] == "tied").sum()),
                     "mean_csr_diff_diverged": float(d["csr_diff"].mean()) if len(d) else None,
                     "critical_victims_gained": int(sum(len(x.split()) for x in d["victims_gained"])),
                     "critical_victims_lost": int(sum(len(x.split()) for x in d["victims_lost"]))})
    return pd.DataFrame(rows)


# ───────────────────────── 3. Per-conflict outcomes ─────────────────────────
def conflict_rows(version: str, scenario: str, seed: int, mode: str, events: list[dict], paired_agents: dict[str, dict] | None) -> list[dict]:
    sc = load_scenario(scenario, seed)
    out = victim_outcomes(events, sc)
    msgs = [e for e in events if e["kind"] == "agent_message"]
    resolved = {e["conflict_id"]: e for e in events if e["kind"] == "conflict_resolved"}
    rows = []
    for c in [e for e in events if e["kind"] == "conflict_detected"]:
        r = resolved[c["conflict_id"]]
        t = c["t"]
        resource_kind, _, resource_id = c["resources"][0].partition(":")
        proposals = [m for m in msgs if m["t"] == t and m["message_type"] == "proposal" and m["incident_id"] in c["incident_ids"]
                     and m.get("proposed_action") and (m["proposed_action"].get("ambulance_id") if resource_kind == "ambulance" else m["proposed_action"].get("hospital_id")) == resource_id]
        involved = sorted({vid for m in proposals for vid in m["proposed_action"]["victim_ids"]})
        neg = [m for m in msgs if m.get("negotiation_id") == c["conflict_id"]]
        counters = [m for m in neg if m["message_type"] == "counter_proposal"]
        counter_ids = {m["message_id"] for m in counters}
        accepted_counters = [m for m in neg if m["message_type"] == "accept" and m.get("in_reply_to") in counter_ids]
        counter_victims = sorted({vid for m in accepted_counters for vid in m["proposed_action"]["victim_ids"]})
        if r["method"] == "fallback":
            resolution = "fallback"
        elif r["method"] == "priority_rule":
            resolution = "priority rule"
        elif accepted_counters:
            resolution = "counter-offer accepted"
        else:
            resolution = "negotiated (no counter accepted)"
        crit = [vid for vid in involved if out[vid]["critical"]]
        row = {"version": version, "scenario": scenario, "seed": seed, "mode": mode, "conflict_id": c["conflict_id"], "minute": t,
               "type": c["conflict_type"], "contested": ", ".join(c["resources"]), "incidents": " ".join(c["incident_ids"]),
               "proposals": len(c["proposal_ids"]), "method": r["method"], "resolution": resolution,
               "rounds": max([m.get("round", 0) for m in neg], default=0), "counter_offers": len(counters),
               "counter_accepted": len(accepted_counters) > 0, "counter_victims": " ".join(counter_victims),
               "involved_victims": len(involved), "involved_critical": len(crit),
               "involved_in_time": sum(out[vid]["in_time"] for vid in involved),
               "involved_critical_in_time": sum(out[vid]["in_time"] for vid in crit),
               "counter_victims_in_time": sum(out[vid]["in_time"] for vid in counter_victims),
               "counter_critical": sum(out[vid]["critical"] for vid in counter_victims),
               "counter_critical_in_time": sum(out[vid]["critical"] and out[vid]["in_time"] for vid in counter_victims)}
        if paired_agents is not None:
            row["same_critical_in_time_in_agents_run"] = sum(paired_agents[vid]["in_time"] for vid in crit)
            row["same_counter_critical_in_time_in_agents_run"] = sum(paired_agents[vid]["critical"] and paired_agents[vid]["in_time"] for vid in counter_victims)
        rows.append(row)
    return rows


def conflict_table(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for v, runs in all_runs.items():
        idx = run_index(runs)
        for (scenario, seed, mode) in sorted(k for k in idx if k[2] == "negotiation"):
            ev = load_events(v, mode, scenario, seed)
            paired = None
            if (scenario, seed, "agents") in idx:
                paired = victim_outcomes(load_events(v, "agents", scenario, seed), load_scenario(scenario, seed))
            rows += conflict_rows(v, scenario, seed, mode, ev, paired)
    return pd.DataFrame(rows)


def conflict_summary(conf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (v, ctype, res), g in conf.groupby(["version", "type", "resolution"]):
        rows.append({"version": v, "type": ctype, "resolution": res, "conflicts": len(g),
                     "involved_critical": int(g["involved_critical"].sum()), "involved_critical_in_time": int(g["involved_critical_in_time"].sum()),
                     "counter_critical": int(g["counter_critical"].sum()), "counter_critical_in_time": int(g["counter_critical_in_time"].sum()),
                     "same_counter_critical_in_time_in_agents_run": int(g["same_counter_critical_in_time_in_agents_run"].sum())})
    return pd.DataFrame(rows)


# ───────────────────────── 4. Contention ─────────────────────────
def contention_table(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for v, runs in all_runs.items():
        df, idx = pd.DataFrame(runs), run_index(runs)
        for scenario in SCENARIOS:
            seeds = sorted({s for (sc, s, m) in idx if sc == scenario and m == "greedy"})
            if not seeds:
                continue
            scs = [load_scenario(scenario, s) for s in seeds]
            n_inc = np.mean([len(s["incidents"]) for s in scs])
            n_crit = np.mean([sum(int(x["severity"]) >= 4 for i in s["incidents"] for x in i["victims"]) for s in scs])
            n_vic = np.mean([sum(len(i["victims"]) for i in s["incidents"]) for s in scs])
            n_amb = len(scs[0]["ambulances"])
            n_als = sum(a["ambulance_type"] == "advanced_life_support" for a in scs[0]["ambulances"])
            window = np.mean([max(i["arrival_time_min"] for i in s["incidents"]) for s in scs])
            er_start = np.mean([sum(h["er_occupied"] for h in s["hospitals"]) / sum(h["er_capacity"] for h in s["hospitals"]) for s in scs])
            peak_wait, peak_crit_wait, er_peak, er_full_runs, idle = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
            for mode in ("greedy", "negotiation"):
                for seed in seeds:
                    if (scenario, seed, mode) not in idx:
                        continue
                    snaps = [e for e in load_events(v, mode, scenario, seed) if e["kind"] == "snapshot"]
                    peak_wait[mode].append(max(s["waiting_victims"] for s in snaps))
                    peak_crit_wait[mode].append(max(s["critical_waiting"] for s in snaps))
                    er_peak[mode].append(max(max(s["er_occupancy"].values()) for s in snaps))
                    er_full_runs[mode].append(any(max(s["er_occupancy"].values()) >= 1.0 for s in snaps))
                    idle[mode].append(np.mean([s["ambulances_available"] == 0 for s in snaps if s["time_min"] <= 75]))
            g = df[(df["scenario"] == scenario) & df["mode"].isin(AGENT_MODES)]
            ctype = lambda k: float(np.mean([d.get(k, 0) for d in g["conflicts_by_type"]])) if len(g) else None
            row = {"version": v, "scenario": scenario, "seeds": len(seeds), "incidents": n_inc, "victims": n_vic, "critical_victims": n_crit,
                   "arrival_window_min": window, "ambulances": n_amb, "als_ambulances": n_als,
                   "critical_per_als_ambulance": n_crit / n_als, "incidents_per_ambulance_hour": n_inc / (n_amb * HORIZON_H),
                   "incidents_per_ambulance_hour_in_arrival_window": n_inc / (n_amb * window / 60),
                   "er_occupied_at_start": er_start,
                   "ambulance_conflicts_per_run": ctype("resource"), "er_capacity_conflicts_per_run": ctype("capacity"),
                   "all_conflicts_per_run": float(g["conflicts"].mean()) if len(g) else None}
            for mode in ("greedy", "negotiation"):
                row.update({f"peak_waiting_victims_{mode}": float(np.mean(peak_wait[mode])) if peak_wait[mode] else None,
                            f"peak_critical_waiting_{mode}": float(np.mean(peak_crit_wait[mode])) if peak_crit_wait[mode] else None,
                            f"er_peak_occupancy_{mode}": float(np.mean(er_peak[mode])) if er_peak[mode] else None,
                            f"share_of_first_75_min_no_ambulance_free_{mode}": float(np.mean(idle[mode])) if idle[mode] else None,
                            f"runs_with_er_full_{mode}": float(np.mean(er_full_runs[mode])) if er_full_runs[mode] else None})
            row["er_full_events_per_run_all_systems"] = float(df[df["scenario"] == scenario]["er_full_events"].mean())
            rows.append(row)
    return pd.DataFrame(rows)


# ───────────────────────── 5. v2 vs v1 ─────────────────────────
def admission_stats(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    cols = ["admission_requests", "admissions_accepted", "admissions_rejected", "admissions_countered", "admission_counters_accepted",
            "admission_rounds_mean", "admission_fallbacks", "admission_rule_redirects", "invalid_proposals"]
    for v, runs in all_runs.items():
        df = pd.DataFrame(runs)
        for (scenario, mode), g in df[df["mode"].isin(AGENT_MODES + ("oracle",))].groupby(["scenario", "mode"]):
            row = {"version": v, "scenario": scenario, "mode": mode, "runs": len(g)}
            row.update({f"{c}_total": float(g[c].sum()) for c in cols if c != "admission_rounds_mean"})
            row["admission_rounds_mean"] = float(g["admission_rounds_mean"].mean()) if g["admission_rounds_mean"].notna().any() else None
            rows.append(row)
    return pd.DataFrame(rows)


def admission_methods(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for v, runs in all_runs.items():
        counts: Counter = Counter()
        for r in runs:
            if r["mode"] in AGENT_MODES:
                for e in load_events(v, r["mode"], r["scenario"], r["seed"]):
                    if e["kind"] == "admission_resolved":
                        counts[(r["mode"], e["method"])] += 1
        rows += [{"version": v, "mode": m, "admission_method": k, "count": n} for (m, k), n in sorted(counts.items())]
    return pd.DataFrame(rows, columns=["version", "mode", "admission_method", "count"])


def v1_vs_v2(runs1: list[dict], runs2: list[dict]) -> pd.DataFrame:
    i1, i2, rows = run_index(runs1), run_index(runs2), []
    for mode in ("greedy", "agents", "negotiation"):
        for scenario in SCENARIOS:
            seeds = sorted(s for (sc, s, m) in i1 if sc == scenario and m == mode and (scenario, s, mode) in i2)
            if not seeds:
                continue
            a = [i1[(scenario, s, mode)]["critical_service_rate"] for s in seeds]
            b = [i2[(scenario, s, mode)]["critical_service_rate"] for s in seeds]
            c = paired_comparison(b, a)
            rows.append({"comparison": "v2 minus v1", "scenario": scenario, "mode": mode, "seeds": c.n,
                         "v1_csr": float(np.mean(a)), "v2_csr": float(np.mean(b)), "mean_diff": c.mean_diff,
                         "ci_low": c.ci_low, "ci_high": c.ci_high, "wins/losses/ties": f"{c.wins}/{c.losses}/{c.ties}",
                         "significant": c.significant})
    return pd.DataFrame(rows)


# ───────────────────────── 6. Failures and reliability ─────────────────────────
def lost_cause(sys_v: dict, greedy_v: dict) -> str:
    """Bucket for why greedy reached this critical victim in time and the other system did not."""
    if sys_v["assign_t"] is None and sys_v["contact"] is None:
        return "never reached, no ambulance ever assigned"
    if sys_v["contact"] is None:
        return "never reached, ambulance assigned too late"
    if sys_v["assign_t"] is not None and greedy_v["assign_t"] is not None:
        if sys_v["assign_t"] > greedy_v["assign_t"]:
            return "ambulance dispatched later than greedy"
        if sys_v["assign_unit"] != greedy_v["assign_unit"]:
            return "different (slower) ambulance than greedy"
    if greedy_v["unit"] != sys_v["unit"]:
        return "first contact by an ambulance instead of the medical team" if str(greedy_v["unit"]).startswith("MED") else "first contact by a different unit"
    return "same dispatch, later arrival"


def ambulances_free_at(events: list[dict], t: int | None) -> int | None:
    """Ambulances available in the snapshot at minute t (None if no such minute)."""
    if t is None:
        return None
    return next((e["ambulances_available"] for e in events if e["kind"] == "snapshot" and e["time_min"] == t), None)


def unit_state_at(events: list[dict], unit: str | None, t: int | None) -> str:
    """What `unit` was doing at the snapshot of minute t, e.g. 'en_route to INC-01'."""
    if unit is None or t is None:
        return ""
    snap = next((e for e in events if e["kind"] == "snapshot" and e["time_min"] == t), None)
    row = next((a for a in snap["ambulances"] if a["id"] == unit), None) if snap else None
    if row is None:
        return ""
    return plain_text(f"{row['status']}" + (f" {row['target']}" if row["target"] else ""))


def failure_tables(all_runs: dict[str, list[dict]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    runs_rows, victim_rows = [], []
    for v, runs in all_runs.items():
        idx = run_index(runs)
        for (scenario, seed, mode), r in sorted(idx.items()):
            if mode not in AGENT_MODES + ("oracle",) or (scenario, seed, "greedy") not in idx:
                continue
            g = idx[(scenario, seed, "greedy")]
            if r["critical_service_rate"] is None or r["critical_service_rate"] >= g["critical_service_rate"] - 1e-12:
                continue
            ev_s, ev_g = load_events(v, mode, scenario, seed), load_events(v, "greedy", scenario, seed)
            sc = load_scenario(scenario, seed)
            os_, og = victim_outcomes(ev_s, sc), victim_outcomes(ev_g, sc)
            lost = [vid for vid in os_ if os_[vid]["critical"] and og[vid]["in_time"] and not os_[vid]["in_time"]]
            won = [vid for vid in os_ if os_[vid]["critical"] and os_[vid]["in_time"] and not og[vid]["in_time"]]
            diff = first_difference(ev_g, ev_s, "Greedy", SYS_LABEL[mode])
            runs_rows.append({"version": v, "scenario": scenario, "seed": seed, "mode": mode, "n_critical": r["n_critical"],
                              "csr_system": r["critical_service_rate"], "csr_greedy": g["critical_service_rate"],
                              "csr_diff": r["critical_service_rate"] - g["critical_service_rate"],
                              "critical_lost_vs_greedy": len(lost), "critical_gained_vs_greedy": len(won),
                              "first_diff_minute": diff["t"] if diff else None,
                              "greedy_did": " | ".join(diff["a_plain"]) if diff else "",
                              "system_did": " | ".join(diff["b_plain"]) if diff else ""})
            for vid in lost:
                s_, g_ = os_[vid], og[vid]
                inc = s_["incident"]
                sys_assign = next((feed_text(e["action"], e["incident_id"], past=True) for e in ev_s if e["kind"] == "action_accepted"
                                   and e["action"]["action_type"] == "assign_ambulance" and vid in e["action"]["victim_ids"]), "no ambulance assigned")
                grd_assign = next((feed_text(e["action"], e["incident_id"], past=True) for e in ev_g if e["kind"] == "action_accepted"
                                   and e["action"]["action_type"] == "assign_ambulance" and vid in e["action"]["victim_ids"]), "no ambulance assigned")
                victim_rows.append({"version": v, "scenario": scenario, "seed": seed, "mode": mode, "victim": vid, "incident": inc,
                                    "severity": s_["severity"], "arrival_min": s_["arrival"], "deadline_min": s_["deadline"],
                                    "greedy_assigned_min": g_["assign_t"], "greedy_assigned": plain_text(grd_assign),
                                    "greedy_contact_min": g_["contact"], "greedy_response": g_["response"],
                                    "system_assigned_min": s_["assign_t"], "system_assigned": plain_text(sys_assign),
                                    "system_contact_min": s_["contact"], "system_response": s_["response"],
                                    "greedy_ambulance_in_system_run_at_that_minute": unit_state_at(ev_s, g_["assign_unit"], g_["assign_t"]),
                                    "ambulances_free_in_system_run_when_greedy_dispatched":
                                        ambulances_free_at(ev_s, g_["assign_t"] if g_["assign_t"] is not None else g_["contact"]),
                                    "cause": lost_cause(s_, g_)})
    return pd.DataFrame(runs_rows), pd.DataFrame(victim_rows)


def invalid_proposals(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    counts: Counter = Counter()
    rejected: Counter = Counter()
    for v, runs in all_runs.items():
        for r in runs:
            if r["mode"] not in AGENT_MODES + ("oracle",):
                continue
            for e in load_events(v, r["mode"], r["scenario"], r["seed"]):
                if e["kind"] == "proposal_invalid":
                    counts[(v, r["mode"], e["agent"], e["reason"])] += 1
            for reason, n in r["rejection_reasons"].items():
                rejected[(v, r["mode"], reason)] += n
    rows = [{"version": v, "mode": m, "agent": a, "reason": reason, "kind": "proposal blocked by the validator before execution", "count": n}
            for (v, m, a, reason), n in sorted(counts.items())]
    rows += [{"version": v, "mode": m, "agent": "(engine)", "reason": reason, "kind": "action rejected at execution", "count": n}
             for (v, m, reason), n in sorted(rejected.items())]
    return pd.DataFrame(rows, columns=["version", "mode", "agent", "reason", "kind", "count"])


def reliability_summary(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for v, runs in all_runs.items():
        df = pd.DataFrame(runs)
        for mode, g in df[df["mode"].isin(AGENT_MODES + ("oracle",))].groupby("mode"):
            rows.append({"version": v, "mode": mode, "runs": len(g), "policy_calls": int(g["policy_calls"].sum()),
                         "proposals_invalid": int(g["invalid_proposals"].sum()), "actions_accepted": int(g["actions_accepted"].sum()),
                         "actions_rejected_at_execution": int(g["actions_rejected"].sum()),
                         "admission_fallbacks": int(g["admission_fallbacks"].sum()), "conflict_fallbacks": int(g["resolved_by_fallback"].sum())})
    return pd.DataFrame(rows)


# ───────────────────────── 7. Cost ─────────────────────────
def cost_benefit(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for v, runs in all_runs.items():
        df, idx = pd.DataFrame(runs), run_index(runs)
        for scenario in SCENARIOS:
            for mode in AGENT_MODES + ("oracle",):
                g = df[(df["scenario"] == scenario) & (df["mode"] == mode)]
                if g.empty:
                    continue
                seeds = paired_seeds(idx, scenario, mode, "greedy")
                c = paired_comparison([idx[(scenario, s, mode)]["critical_service_rate"] for s in seeds],
                                      [idx[(scenario, s, "greedy")]["critical_service_rate"] for s in seeds])
                cost = float(g["est_cost_usd"].mean())
                rows.append({"version": v, "scenario": scenario, "mode": mode, "runs": len(g), "cost_usd_per_run": cost,
                             "tokens_in_per_run": float(g["tokens_in"].mean()), "tokens_out_per_run": float(g["tokens_out"].mean()),
                             "llm_calls_per_run": float(g["llm_calls"].mean()), "model_time_s_per_run": float(g["llm_latency_s"].mean()),
                             "csr_diff_vs_greedy_points": 100 * c.mean_diff,
                             "csr_diff_ci_low_points": None if c.ci_low is None else 100 * c.ci_low,
                             "csr_diff_ci_high_points": None if c.ci_high is None else 100 * c.ci_high,
                             "ci_excludes_zero": bool(c.significant),
                             "usd_per_extra_point": cost / (100 * c.mean_diff) if c.mean_diff and c.mean_diff > 0 else None,
                             "total_cost_usd": float(g["est_cost_usd"].sum())})
    return pd.DataFrame(rows)


def cost_overall(all_runs: dict[str, list[dict]]) -> pd.DataFrame:
    """Per-run means over every run of a system in a version (weighted by runs, not an average of scenario means)."""
    rows = []
    for v, runs in all_runs.items():
        df = pd.DataFrame(runs)
        for mode, g in df[df["mode"].isin(AGENT_MODES + ("oracle",))].groupby("mode"):
            rows.append({"version": v, "mode": mode, "runs": len(g), "cost_usd_per_run": float(g["est_cost_usd"].mean()),
                         "tokens_per_run": float((g["tokens_in"] + g["tokens_out"]).mean()), "llm_calls_per_run": float(g["llm_calls"].mean()),
                         "model_time_s_per_run": float(g["llm_latency_s"].mean()), "total_cost_usd": float(g["est_cost_usd"].sum()),
                         "total_tokens": int((g["tokens_in"] + g["tokens_out"]).sum())})
    return pd.DataFrame(rows)


# ───────────────────────── Figures ─────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": PANEL, "savefig.facecolor": BG, "axes.edgecolor": GRID,
                         "axes.labelcolor": TEXT2, "xtick.color": TEXT2, "ytick.color": TEXT2, "text.color": TEXT,
                         "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
                         "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 15,
                         "axes.titlesize": 18, "axes.titleweight": "semibold", "axes.titlecolor": TEXT, "legend.frameon": False,
                         "legend.labelcolor": TEXT2, "legend.fontsize": 14, "axes.spines.top": False, "axes.spines.right": False})
    return plt


def _save(plt, fig, name: str, title: str, subtitle: str) -> None:
    fig.text(0.045, 0.955, title, ha="left", va="center", fontsize=24, fontweight="semibold", color=TEXT)
    fig.text(0.045, 0.905, subtitle, ha="left", fontsize=14, color=TEXT2)
    fig.savefig(OUT / f"{name}.png", dpi=144)
    plt.close(fig)


def _canvas(plt, ncols: int = 1):
    fig, axes = plt.subplots(1, ncols, figsize=(13.333, 7.5), squeeze=False)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.77, bottom=0.13, wspace=0.18)
    return fig, axes[0]


def fig_csr(plt, version: str, t: pd.DataFrame) -> None:
    fig, (ax,) = _canvas(plt)
    modes = [m for m in SYSTEMS if m in set(t["mode"])]
    width = 0.8 / len(modes)
    for k, m in enumerate(modes):
        for i, sc in enumerate(SCENARIOS):
            r = t[(t["scenario"] == sc) & (t["mode"] == m)]
            if r.empty:
                continue
            r = r.iloc[0]
            x = i + (k - (len(modes) - 1) / 2) * width
            ax.bar(x, r["mean"], width * 0.9, color=SYS_COLOR[m], label=SYS_LABEL[m] if i == 0 else None)
            ax.vlines(x, max(0, r["ci_low"]), min(1, r["ci_high"]), color=TEXT, lw=1.6)
            ax.text(x, min(1, r["ci_high"]) + 0.015, f"{r['mean']:.0%}", ha="center", va="bottom", fontsize=11, color=TEXT2)
    ax.set_xticks(range(len(SCENARIOS)), [f"{SC_LABEL[s]}\n({int(t[t.scenario == s].n.max())} seeds)" for s in SCENARIOS])
    ax.set_ylim(0, 1.08); ax.set_yticks(np.arange(0, 1.01, 0.2), [f"{x:.0%}" for x in np.arange(0, 1.01, 0.2)])
    ax.set_ylabel("Critical victims reached within deadline"); ax.grid(axis="x", visible=False)
    ax.legend(ncols=len(modes), loc="lower right", bbox_to_anchor=(1, 1.01))
    _save(plt, fig, f"fig01_csr_{version}", f"Critical service rate by scenario and system ({version})",
          f"Mean over seeds with 95% confidence interval. Source: results/{version}/runs.jsonl")


def fig_paired(plt, name: str, title: str, rows: pd.DataFrame, subtitle: str) -> None:
    """Dot and whisker: paired difference in points. One row per scenario and system; v1 hollow marker, v2 filled."""
    fig, (ax,) = _canvas(plt)
    fig.subplots_adjust(left=0.20)
    keys = list(dict.fromkeys(zip(rows["mode"], rows["scenario"])))
    keys.sort(key=lambda k: (SCENARIOS.index(k[1]), ["agents", "negotiation", "oracle"].index(k[0]) if k[0] in ("agents", "negotiation", "oracle") else 9))
    n = len(keys)
    right = 100 * rows["ci_high"].max()
    lo = min(100 * rows["ci_low"].min(), -5)
    ax.set_xlim(lo - 3, max(right, 5) + 4); text_x = max(right, 5) + 5.5
    for i, (mode, scenario) in enumerate(keys):
        y = n - 1 - i
        for v, dy in (("v1", 0.17), ("v2", -0.17)):
            g = rows[(rows["mode"] == mode) & (rows["scenario"] == scenario) & (rows["version"] == v)]
            if g.empty:
                continue
            r = g.iloc[0]
            ax.hlines(y + dy, 100 * r["ci_low"], 100 * r["ci_high"], color=TEXT2, lw=2)
            ax.plot(100 * r["mean_diff"], y + dy, "o", ms=11, mfc=SYS_COLOR[mode] if v == "v2" else PANEL, mec=SYS_COLOR[mode], mew=2.2)
            ax.text(text_x, y + dy, f"{v}  {100 * r['mean_diff']:+.1f}   ({r['wins']}/{r['losses']}/{r['ties']})", va="center", fontsize=12, color=TEXT2)
    ax.axvline(0, color=TEXT3, lw=1.4)
    ax.set_yticks([n - 1 - i for i in range(n)], [f"{SC_LABEL[sc]} · {SYS_LABEL[m].split(' (')[0]}\nn = {int(rows[(rows['mode'] == m) & (rows['scenario'] == sc)]['n'].max())} seeds" for m, sc in keys])
    ax.set_ylim(-0.7, n - 0.3); ax.set_xlabel("Difference in critical service rate (points)  ·  hollow = v1, filled = v2  ·  labels: wins/losses/ties by seed")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(ax.get_xlim()[0], text_x + 14)
    _save(plt, fig, name, title, subtitle)


def fig_triage(plt, version: str, t: pd.DataFrame) -> None:
    fig, axes = _canvas(plt, 3)
    modes = [m for m in ("naive", "greedy", "agents", "negotiation") if m in set(t["mode"])]
    for ax, color in zip(axes, TRIAGE_COLOR):
        w = 0.8 / len(modes)
        for k, m in enumerate(modes):
            vals = [t[(t.scenario == s) & (t["mode"] == m) & (t.color == color)]["rate"] for s in SCENARIOS]
            ax.bar([i + (k - (len(modes) - 1) / 2) * w for i in range(3)], [x.iloc[0] if len(x) else 0 for x in vals], w * 0.9,
                   color=SYS_COLOR[m], label=SYS_LABEL[m])
        ax.set_title(color, loc="left", color=TRIAGE_COLOR[color]); ax.set_ylim(0, 1.05)
        ax.set_xticks(range(3), [SC_LABEL[s] for s in SCENARIOS], fontsize=12); ax.grid(axis="x", visible=False)
        ax.set_yticks(np.arange(0, 1.01, 0.25), [f"{x:.0%}" for x in np.arange(0, 1.01, 0.25)])
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", bbox_to_anchor=(0.97, 0.885), ncols=len(modes), fontsize=13)
    _save(plt, fig, f"fig05_triage_{version}", f"Victims served in time by START colour ({version})",
          f"Mean over seeds; Immediate = severity 4-5, Delayed = 3, Minor = 1-2. Source: results/{version}/runs.jsonl")


def fig_divergence(plt, summary: pd.DataFrame) -> None:
    fig, (ax,) = _canvas(plt)
    g = summary[summary.scenario != "all"].reset_index(drop=True)
    labels = [f"{r.version} · {SC_LABEL[r.scenario]}" for r in g.itertuples()]
    bottom = np.zeros(len(g))
    for col, color, name in (("helped", OK, "Negotiation helped"), ("tied", TEXT3, "Diverged, same outcome"), ("hurt", DANGER, "Negotiation hurt"),
                             ("never_diverged", GRID, "Never diverged (identical runs)")):
        ax.bar(range(len(g)), g[col], 0.62, bottom=bottom, color=color, label=name, edgecolor=BG)
        for i, v in enumerate(g[col]):
            if v:
                ax.text(i, bottom[i] + v / 2, int(v), ha="center", va="center", fontsize=13, color=BG if color in (OK,) else TEXT)
        bottom += g[col].values
    ax.set_xticks(range(len(g)), labels, fontsize=12); ax.set_ylabel("Paired runs (same version, scenario, seed)")
    ax.set_ylim(0, 13); ax.legend(ncols=2, loc="upper right"); ax.grid(axis="x", visible=False)
    _save(plt, fig, "fig06_divergence", "Negotiation vs agents: did the runs diverge, and who gained?",
          "Outcome = critical service rate, negotiation minus agents. Source: logs/<version>/{agents,negotiation}")


def fig_conflicts(plt, s: pd.DataFrame) -> None:
    fig, (ax,) = _canvas(plt)
    g = s.groupby(["version", "resolution"])["conflicts"].sum().unstack(fill_value=0)
    colors = {"counter-offer accepted": "#6366F1", "negotiated (no counter accepted)": "#8B8EF6", "fallback": WARN, "priority rule": TEXT3}
    bottom = np.zeros(len(g))
    for col in g.columns:
        ax.bar(range(len(g)), g[col], 0.5, bottom=bottom, color=colors.get(col, TEXT3), label=col, edgecolor=BG)
        for i, v in enumerate(g[col]):
            if v >= 3:
                ax.text(i, bottom[i] + v / 2, int(v), ha="center", va="center", fontsize=14, color=TEXT)
            elif v:
                ax.text(i + 0.29, bottom[i] + v / 2, f"{int(v)}  {col}", ha="left", va="center", fontsize=12, color=TEXT2)
        bottom += g[col].values
    ax.set_xlim(-0.5, len(g) - 0.1)
    ax.set_xticks(range(len(g)), [f"{v} negotiation runs" for v in g.index]); ax.set_ylabel("Conflicts")
    ax.legend(loc="upper right", ncols=2); ax.grid(axis="x", visible=False)
    _save(plt, fig, "fig07_conflict_resolutions", "How conflicts were resolved in negotiation runs",
          "Every conflict in logs/<version>/negotiation, by resolution")


def fig_contention(plt, t: pd.DataFrame) -> None:
    fig, axes = _canvas(plt, 3)
    panels = [("Critical victims per ALS ambulance", "critical_per_als_ambulance", "{:.1f}"),
              ("Ambulance conflicts per run", "ambulance_conflicts_per_run", "{:.1f}"),
              ("Peak ER occupancy (negotiation)", "er_peak_occupancy_negotiation", "{:.0%}")]
    for ax, (title, col, fmt) in zip(axes, panels):
        for k, v in enumerate(sorted(t.version.unique())):
            vals = [t[(t.version == v) & (t.scenario == s)][col] for s in SCENARIOS]
            vals = [x.iloc[0] if len(x) else 0 for x in vals]
            xs = [i + (k - 0.5) * 0.36 for i in range(3)]
            ax.bar(xs, vals, 0.34, color=VERSION_COLOR[v], label=v)
            for x, y in zip(xs, vals):
                ax.text(x, y, fmt.format(y), ha="center", va="bottom", fontsize=11, color=TEXT2)
        ax.set_title(title, loc="left", fontsize=14); ax.set_xticks(range(3), [SC_LABEL[s] for s in SCENARIOS], fontsize=12); ax.grid(axis="x", visible=False)
        if col == "er_peak_occupancy_negotiation":
            ax.axhline(1.0, color=DANGER, lw=1.4, ls="--"); ax.set_ylim(0, 1.25); ax.set_yticks([0, .25, .5, .75, 1.0], ["0%", "25%", "50%", "75%", "100%"]); ax.text(2.45, 1.02, "ER full", color=DANGER, ha="right", fontsize=11)
    axes[0].legend(loc="upper left", fontsize=12)
    _save(plt, fig, "fig08_contention", "Ambulance pressure rises, ambulance conflicts fall, ER beds never fill",
          "Normal → surge → bottleneck. Demand from data/scenarios; conflicts (agent systems) and ER peaks (negotiation runs) from results/ and logs/ of each version")


def fig_v1_v2(plt, t: pd.DataFrame) -> None:
    fig, axes = _canvas(plt, 2)
    for ax, mode in zip(axes, ("agents", "negotiation")):
        g = t[t["mode"] == mode].reset_index(drop=True)
        for i, r in g.iterrows():
            ax.bar(i - 0.18, r["v1_csr"], 0.34, color=VERSION_COLOR["v1"], label="v1" if i == 0 else None)
            ax.bar(i + 0.18, r["v2_csr"], 0.34, color=VERSION_COLOR["v2"], label="v2" if i == 0 else None)
            ax.text(i - 0.18, r["v1_csr"] + 0.01, f"{r['v1_csr']:.0%}", ha="center", fontsize=12, color=TEXT2)
            ax.text(i + 0.18, r["v2_csr"] + 0.01, f"{r['v2_csr']:.0%}", ha="center", fontsize=12, color=TEXT2)
        ax.set_xticks(range(len(g)), [f"{SC_LABEL[s]}\n({n} seeds)" for s, n in zip(g.scenario, g.seeds)], fontsize=12)
        ax.set_title(SYS_LABEL[mode], loc="left", color=SYS_COLOR[mode]); ax.set_ylim(0, 0.8); ax.grid(axis="x", visible=False)
        ax.set_yticks(np.arange(0, 0.81, 0.2), [f"{x:.0%}" for x in np.arange(0, 0.81, 0.2)])
    axes[0].legend(loc="upper right")
    _save(plt, fig, "fig09_v1_vs_v2", "Same agents, two protocol versions: critical service rate",
          "Paired by scenario and seed. v1 = frozen pilot, v2 = with hospital admission negotiation. Sources: results/v1 and results/v2")


def fig_failures(plt, runs: pd.DataFrame, victims: pd.DataFrame) -> None:
    import textwrap
    fig, axes = _canvas(plt, 2)
    fig.subplots_adjust(left=0.07, wspace=0.75)
    ax = axes[0]
    counts = runs.groupby(["version", "mode"]).size()
    totals = pd.DataFrame({"runs": [counts.get((v, m), 0) for v in VERSIONS for m in AGENT_MODES]},
                          index=[f"{v} · {SYS_LABEL[m].split(' (')[0]}" for v in VERSIONS for m in AGENT_MODES])
    ax.bar(range(len(totals)), totals["runs"], 0.6, color=[SYS_COLOR[m] for _ in VERSIONS for m in AGENT_MODES])
    for i, v in enumerate(totals["runs"]):
        ax.text(i, v + 0.1, int(v), ha="center", fontsize=14, color=TEXT2)
    ax.set_xticks(range(len(totals)), totals.index, fontsize=11); ax.set_title("Runs below greedy", loc="left", fontsize=14); ax.grid(axis="x", visible=False)
    ax = axes[1]
    c = victims.groupby("cause").size().sort_values() if len(victims) else pd.Series(dtype=int)
    short = ["\n".join(textwrap.wrap(x, 30)) for x in c.index]
    ax.barh(range(len(c)), c.values, 0.6, color=DANGER)
    ax.set_yticks(range(len(c)), short, fontsize=11); ax.set_title("Why critical victims were lost vs greedy", loc="left", fontsize=14); ax.grid(axis="y", visible=False)
    for i, v in enumerate(c.values):
        ax.text(v + 0.05, i, int(v), va="center", fontsize=12, color=TEXT2)
    _save(plt, fig, "fig10_failures", "Where agent systems did worse than greedy",
          "Runs with a lower critical service rate than greedy on the same scenario and seed; victims reached in time by greedy but not by the system")


def fig_cost(plt, t: pd.DataFrame, overall: pd.DataFrame) -> None:
    fig, axes = _canvas(plt, 2)
    ax = axes[0]
    for r in t.itertuples():
        ax.errorbar(r.cost_usd_per_run, r.csr_diff_vs_greedy_points,
                    yerr=None if r.csr_diff_ci_low_points is None else [[r.csr_diff_vs_greedy_points - r.csr_diff_ci_low_points], [r.csr_diff_ci_high_points - r.csr_diff_vs_greedy_points]],
                    fmt="o" if r.version == "v2" else "s", ms=10, color=SYS_COLOR[r.mode], ecolor=GRID, mec=TEXT, mew=0.8, capsize=3)
    ax.axhline(0, color=TEXT3, lw=1.4); ax.set_ylim(-30, 30)
    ax.set_xlabel("List-price cost per run (USD)"); ax.set_ylabel("Critical service rate minus greedy (points)")
    ax.set_title("Each point = scenario × system × version (oracle: 3 seeds, off-scale CI clipped)", loc="left", fontsize=13)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=SYS_COLOR[m], label=SYS_LABEL[m]) for m in AGENT_MODES] +
              [Line2D([], [], marker="s", ls="", color=TEXT2, label="v1"), Line2D([], [], marker="o", ls="", color=TEXT2, label="v2")], loc="lower right", fontsize=11)
    ax = axes[1]
    g = overall.reset_index(drop=True)
    for i, r in g.iterrows():
        ax.bar(i, r["model_time_s_per_run"], 0.6, color=SYS_COLOR[r["mode"]])
        ax.text(i, r["model_time_s_per_run"] + 3, f"{r['model_time_s_per_run']:.0f} s\n${r['cost_usd_per_run']:.2f}", ha="center", fontsize=11, color=TEXT2)
    ax.set_xticks(range(len(g)), [f"{r.version}\n{SYS_LABEL[r['mode']].split(' (')[0]}" for _, r in g.iterrows()], fontsize=11)
    ax.set_ylabel("Model time per run (s, summed over calls)"); ax.set_title("Mean model time and cost per run", loc="left", fontsize=14); ax.grid(axis="x", visible=False)
    ax.set_ylim(0, g["model_time_s_per_run"].max() * 1.25)
    _save(plt, fig, "fig11_cost_vs_benefit", "RQ4: what the agents cost vs what they change",
          "Cost at list price from logged tokens; model time is the summed latency of the logged model calls. Sources: results/v1 and results/v2")


# ───────────────────────── Driver ─────────────────────────
def build_all() -> dict[str, pd.DataFrame]:
    all_runs = {v: load_runs(v) for v in VERSIONS}
    tables = headline_tables(all_runs)
    div = divergence_table(all_runs)
    tables["02_divergence"] = div
    tables["02_divergence_summary"] = divergence_summary(div)
    conf = conflict_table(all_runs)
    tables["03_conflicts"] = conf
    tables["03_conflict_summary"] = conflict_summary(conf)
    tables["04_contention"] = contention_table(all_runs)
    tables["05_admission_stats"] = admission_stats(all_runs)
    tables["05_admission_methods"] = admission_methods(all_runs)
    tables["05_v1_vs_v2_critical_service"] = v1_vs_v2(all_runs["v1"], all_runs["v2"])
    fr, fv = failure_tables(all_runs)
    tables["06_failure_runs"], tables["06_failure_victims"] = fr, fv
    tables["06_invalid_proposals"] = invalid_proposals(all_runs)
    tables["06_reliability_summary"] = reliability_summary(all_runs)
    tables["07_cost_benefit"] = cost_benefit(all_runs)
    tables["07_cost_overall"] = cost_overall(all_runs)
    tables["00_reconstruction_check"] = pd.concat([verify_reconstruction(v, r) for v, r in all_runs.items()], ignore_index=True)
    return tables


def build_figures(t: dict[str, pd.DataFrame]) -> None:
    plt = _plt()
    for v in VERSIONS:
        fig_csr(plt, v, t["01_csr"][t["01_csr"].version == v])
        fig_triage(plt, v, t["01_triage_by_color"][t["01_triage_by_color"].version == v])
    fig_paired(plt, "fig02_rq1_vs_greedy", "RQ1: agent systems minus greedy, critical service rate", t["01_rq1_paired_vs_greedy"][t["01_rq1_paired_vs_greedy"]["mode"].isin(AGENT_MODES)],
               "Mean paired difference with 95% CI; labels show wins/losses/ties by seed. Sources: results/v1, results/v2")
    fig_paired(plt, "fig03_rq2_negotiation_vs_agents", "RQ2: negotiation minus agents without negotiation", t["01_rq2_negotiation_vs_agents"],
               "Mean paired difference with 95% CI; labels show wins/losses/ties by seed. Sources: results/v1, results/v2")
    fig_paired(plt, "fig04_oracle_ablation", "Oracle ablation (v1 only): oracle minus negotiation", t["01_oracle_ablation"],
               "Three seeds per scenario; oracle sees ground-truth victim assessments. Source: results/v1")
    fig_divergence(plt, t["02_divergence_summary"])
    fig_conflicts(plt, t["03_conflict_summary"])
    fig_contention(plt, t["04_contention"])
    fig_v1_v2(plt, t["05_v1_vs_v2_critical_service"][t["05_v1_vs_v2_critical_service"]["mode"].isin(AGENT_MODES)])
    fig_failures(plt, t["06_failure_runs"], t["06_failure_victims"])
    fig_cost(plt, t["07_cost_benefit"], t["07_cost_overall"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Final analysis from saved results and logs (no experiments, no API calls).")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    tables = build_all()
    check = tables["00_reconstruction_check"]
    bad = check[~(check.csr_matches & check.response_matches)]
    print(f"Per-victim reconstruction matches results/ for {len(check) - len(bad)} of {len(check)} runs")
    if len(bad):
        print(bad.to_string(index=False))
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"  {name}.csv  ({len(df)} rows)")
    if not args.no_figures:
        build_figures(tables)
        print(f"Figures written to {OUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
