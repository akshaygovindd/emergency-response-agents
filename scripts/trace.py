"""Print a readable story of one run from its event log.

Usage:
    python scripts/trace.py logs/v1/agents/bottleneck_seed42_agents.jsonl --until 20
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from erc.logging.event_log import EventLog


def act(a: dict | None) -> str:
    if not a:
        return ""
    kind = a["action_type"]
    if kind == "assign_ambulance":
        return f"{a['ambulance_id']} pick up {a['victim_ids']}"
    if kind == "assign_responder":
        return f"{a['responder_id']}"
    return f"{'divert' if kind == 'divert_patient' else 'admit'} {a['victim_ids']} -> {a['hospital_id']}"


def line(e: dict) -> str | None:
    k, t = e["kind"], f"t={e['t']:3}"
    if k == "incident_arrived":
        return f"{t}  INCIDENT  {e['incident_id']} arrives ({e['victims']} victims)"
    if k == "assessment":
        return f"{t}  ASSESS    {e['incident_id']} -> {e['victims']}"
    if k == "agent_message" and e["message_type"] != "info":
        tail = f" (re {e['in_reply_to']})" if e.get("in_reply_to") else ""
        return (f"{t}  MSG {e['message_id']} {e['sender']} -> {e['recipient']} {e['message_type'].upper()} "
                f"{e['incident_id']} {act(e.get('proposed_action'))}{tail} | {e['reason'][:90]}")
    if k == "proposal_invalid":
        return f"{t}  INVALID   {e['agent']} {e['tool']} -> {e['reason']}: {e['detail'][:80]}"
    if k == "conflict_detected":
        return f"{t}  CONFLICT  {e['conflict_id']} {e['conflict_type']}: {e['reason']}"
    if k == "conflict_resolved":
        return f"{t}  RESOLVED  {e['conflict_id']} by {e['method']}: winners {e['winners']}, losers {e['losers']}"
    if k == "action_accepted":
        return f"{t}  EXECUTED  {act(e['action'])} (commit {e['message_id']})"
    if k == "action_rejected":
        return f"{t}  VALIDATOR REJECTED {act(e['action'])}: {e['reason']}"
    if k in ("ambulance_on_scene", "handover_complete", "victim_deteriorated", "treatment_started"):
        rest = {x: y for x, y in e.items() if x not in ("t", "kind")}
        return f"{t}  {k.upper():9} {rest}"
    return None


def main(path: Path, until: int | None) -> None:
    log = EventLog.load(path)
    for e in log.events:
        if until is not None and e["t"] > until:
            break
        text = line(e)
        if text:
            print(text)
    llm = log.of_kind("llm_call")
    by_agent = Counter(e["agent"] for e in llm)
    print("\n=== Totals for the whole run ===")
    print(f"agent runs: {len(llm)} {dict(by_agent)} | cache hits: {sum(e['cache_hit'] for e in llm)}")
    print(f"model calls: {sum(e['requests'] for e in llm)} | tokens in: {sum(e['tokens_in'] for e in llm)} | "
          f"tokens out: {sum(e['tokens_out'] for e in llm)}")
    print(f"messages: {len(log.of_kind('agent_message'))} | conflicts: {len(log.of_kind('conflict_detected'))} | "
          f"invalid proposals: {len(log.of_kind('proposal_invalid'))} | "
          f"validator rejections: {len(log.of_kind('action_rejected'))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--until", type=int)
    args = parser.parse_args()
    main(args.path, args.until)