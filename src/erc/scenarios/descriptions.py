"""LLM-written incident reports, generated once from ground truth and cached on disk.

Scenario files (the ground truth) are never modified. Reports are stored in
data/descriptions/, one JSON file per scenario and seed, and are the ONLY
incident information the Assessment Agent receives. People are always described
in victim order, so person k corresponds to victim V-<incident>-k.

Usage:
    python -m erc.scenarios.descriptions --scenario bottleneck --seed 42   # one file
    python -m erc.scenarios.descriptions                                   # everything
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agents import Agent, Runner

from erc.config import PROJECT_ROOT, SCENARIO_DIR, SETTINGS, ScenarioName, seeds_for
from erc.models.entities import Incident
from erc.models.state import Scenario

DESCRIPTION_DIR = PROJECT_ROOT / "data" / "descriptions"

# Capability-neutral signs: severity is conveyed only through responsiveness,
# breathing, bleeding, and mobility, never through the type of injury.
CONDITION_SIGNS = {
    5: "unresponsive or barely responsive, not breathing normally or bleeding massively",
    4: "confused or drowsy, struggling to breathe or bleeding heavily, in severe pain",
    3: "alert but in significant pain and unable to walk, any bleeding under control",
    2: "alert and able to walk, in moderate pain",
    1: "alert and walking, only minor discomfort",
}
# The type of problem is conveyed only here.
PROBLEM_TYPE = {
    "trauma": "an injury from force or impact, such as a wound, fracture, crush injury, or head injury",
    "burn": "burns or smoke or chemical inhalation",
    "general": "a medical condition rather than a specialist injury, such as chest pain, breathing "
               "trouble, fainting, or only minor cuts and bruises; do not describe burns or fractures",
}
SCENE_NOTE = {
    "rescue": "People are trapped and need to be freed.",
    "fire": "A fire or hazard is still active at the scene.",
    "medical": "A medical team is needed on scene.",
}
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth"]

WRITER = Agent(
    name="IncidentReportWriter",
    model=SETTINGS.llm.model,
    instructions=(
        "You write short, realistic emergency dispatch notes, like those taken during a 911 call. "
        "Start with one sentence describing the scene and how many people are hurt. Then write exactly "
        "one sentence per person, in the order given, beginning with 'The first person', 'The second "
        "person', and so on. Describe each person using both their signs and their type of problem, in "
        "plain everyday words. Never use numbers or labels for condition, and never use the words "
        "'severity', 'critical', 'life-threatening', 'stable', 'ALS', 'BLS', 'priority', or 'triage'. "
        "Mention that people are trapped or that a fire is still burning when the facts say so. "
        "Do not invent people, injuries, or details that are not given. Output only the note."
    ),
)


def incident_facts(incident: Incident) -> str:
    """Ground-truth facts handed to the report writer (never shown to the Assessment Agent)."""
    lines = [f"Incident type: {incident.incident_type.value.replace('_', ' ')}",
             f"Number of injured people: {incident.victim_count}"]
    if incident.required_responder is not None:
        lines.append(SCENE_NOTE[incident.required_responder.value])
    for k, v in enumerate(incident.victims):
        lines.append(f"The {ORDINALS[k]} person: signs: {CONDITION_SIGNS[int(v.severity)]}; "
                     f"type of problem: {PROBLEM_TYPE[v.required_capability.value]}.")
    return "\n".join(lines)


def description_path(name: ScenarioName, seed: int) -> Path:
    return DESCRIPTION_DIR / f"{name.value}_seed{seed}.json"


def load_descriptions(name: ScenarioName, seed: int) -> dict[str, str]:
    path = description_path(name, seed)
    return json.loads(path.read_text()) if path.exists() else {}


async def _write_one(incident: Incident, sem: asyncio.Semaphore) -> tuple[str, str, int, int]:
    async with sem:
        result = await Runner.run(WRITER, incident_facts(incident))
        usage = result.context_wrapper.usage
        return incident.incident_id, str(result.final_output).strip(), usage.input_tokens, usage.output_tokens


async def generate_for(scenario: Scenario, sem: asyncio.Semaphore) -> tuple[int, int, int]:
    """Writes missing reports for one scenario file. Existing reports are never regenerated."""
    reports = load_descriptions(scenario.name, scenario.seed)
    todo = [i for i in scenario.incidents if i.incident_id not in reports]
    results = await asyncio.gather(*(_write_one(i, sem) for i in todo))
    tokens_in = tokens_out = 0
    for incident_id, text, t_in, t_out in results:
        reports[incident_id] = text
        tokens_in += t_in
        tokens_out += t_out
    DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
    description_path(scenario.name, scenario.seed).write_text(json.dumps(dict(sorted(reports.items())), indent=2))
    return len(todo), tokens_in, tokens_out


async def generate_all(names: list[ScenarioName], seeds: list[int] | None, concurrency: int = 8) -> None:
    sem = asyncio.Semaphore(concurrency)
    total_new = total_in = total_out = 0
    for name in names:
        for seed in (seeds or seeds_for(name)):
            scenario = Scenario.load(SCENARIO_DIR / f"{name.value}_seed{seed}.json")
            new, t_in, t_out = await generate_for(scenario, sem)
            total_new, total_in, total_out = total_new + new, total_in + t_in, total_out + t_out
            print(f"  {name.value:10} seed {seed}: {new} new reports")
    print(f"Done. New reports: {total_new} | tokens in: {total_in} | tokens out: {total_out}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="Generate cached LLM incident reports.")
    parser.add_argument("--scenario", nargs="+", choices=[s.value for s in ScenarioName],
                        default=[s.value for s in ScenarioName])
    parser.add_argument("--seed", type=int, nargs="+")
    args = parser.parse_args()
    asyncio.run(generate_all([ScenarioName(s) for s in args.scenario], args.seed))