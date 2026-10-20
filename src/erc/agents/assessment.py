"""Incident Assessment Agent: reads a dispatch report and assesses each person in it.

It never sees ground truth. Accuracy is measured against ground truth separately,
and oracle_assessment() builds the same report from ground truth for the oracle ablation.
"""
from __future__ import annotations

from typing import Literal

from agents import Agent
from pydantic import BaseModel, Field

from erc.config import SETTINGS
from erc.models.entities import Capability, Incident, ResponderType, Severity
from erc.models.messages import AssessmentReport, VictimAssessment

INSTRUCTIONS = """You are the Incident Assessment Agent in an emergency coordination center.
You read one dispatch report and assess every person described in it, in the order they appear.

Urgency scale:
5 - unresponsive or barely responsive, absent or abnormal breathing, or massive bleeding
4 - reduced consciousness (confused or drowsy), difficulty breathing, heavy bleeding, or severe pain
3 - alert, significant pain, unable to walk, any bleeding controlled
2 - alert and walking, moderate pain
1 - alert and walking, minor complaints

Care type:
trauma  - injury from force or impact (wounds, fractures, crush or head injury)
burn    - burns, smoke or chemical inhalation
general - medical conditions (chest pain, breathing trouble, fainting) or minor injuries

Advanced life support: required for every person at urgency 4 or 5.
Team needed: "rescue" if people are trapped, "fire" if a fire or hazard is still active, otherwise "none".
Priority score (0-100): overall urgency of the incident, driven by its most urgent people and how many
of them are at urgency 4 or 5.

Use only what the report says. Number people by their order in the report, starting at 1."""


class VictimFinding(BaseModel):
    position: int = Field(description="1 for the first person described, 2 for the second, and so on")
    severity: int = Field(description="Urgency from 1 (minor) to 5 (immediate threat to life)")
    care_type: Literal["trauma", "burn", "general"]
    needs_advanced_life_support: bool


class AssessmentOutput(BaseModel):
    victims: list[VictimFinding]
    team_needed: Literal["rescue", "fire", "none"]
    priority_score: int = Field(description="Overall urgency of the incident from 0 to 100")
    reasoning: str = Field(description="One or two sentences explaining the assessment")


ASSESSMENT_AGENT = Agent(name="IncidentAssessmentAgent", model=SETTINGS.llm.model,
                         instructions=INSTRUCTIONS, output_type=AssessmentOutput)


def to_report(incident: Incident, output: AssessmentOutput | dict) -> AssessmentReport:
    """Maps the agent's findings onto victim IDs by position and validates the result."""
    out = AssessmentOutput.model_validate(output) if isinstance(output, dict) else output
    by_position = {f.position: f for f in out.victims}
    victims = []
    for k, truth in enumerate(incident.victims, start=1):
        f = by_position.get(k)
        if f is not None:
            victims.append(VictimAssessment(
                victim_id=truth.victim_id, severity=Severity(min(5, max(1, f.severity))),
                required_capability=Capability(f.care_type), needs_als=f.needs_advanced_life_support))
    if not victims:
        raise ValueError(f"Assessment of {incident.incident_id} matched no victims")
    return AssessmentReport(
        incident_id=incident.incident_id, victims=victims, reported_victim_count=len(out.victims),
        required_responder=None if out.team_needed == "none" else ResponderType(out.team_needed),
        priority_score=min(100, max(0, out.priority_score)), reasoning=out.reasoning[:1000] or "-")


def oracle_assessment(incident: Incident) -> AssessmentReport:
    """Ground-truth assessment for the oracle ablation (no LLM call)."""
    critical = sum(v.is_critical for v in incident.victims)
    return AssessmentReport(
        incident_id=incident.incident_id,
        victims=[VictimAssessment(victim_id=v.victim_id, severity=v.severity,
                                  required_capability=v.required_capability, needs_als=v.needs_als)
                 for v in incident.victims],
        reported_victim_count=incident.victim_count, required_responder=incident.required_responder,
        priority_score=min(100, 15 * int(incident.max_severity) + 5 * critical),
        reasoning="Ground truth (oracle).")


def score(incident: Incident, report: AssessmentReport) -> dict[str, int]:
    """Counts correct extractions against ground truth. Missing victims count as wrong."""
    found = {v.victim_id: v for v in report.victims}
    s = dict(incidents=1, victims_true=incident.victim_count, victims_matched=0,
             count_correct=int(report.reported_victim_count == incident.victim_count),
             responder_correct=int(report.required_responder == incident.required_responder),
             severity_exact=0, severity_within1=0, critical_correct=0, capability_correct=0, als_correct=0)
    for v in incident.victims:
        f = found.get(v.victim_id)
        if f is None:
            continue
        s["victims_matched"] += 1
        s["severity_exact"] += int(f.severity == v.severity)
        s["severity_within1"] += int(abs(int(f.severity) - int(v.severity)) <= 1)
        s["critical_correct"] += int((f.severity >= Severity.SEVERE) == v.is_critical)
        s["capability_correct"] += int(f.required_capability == v.required_capability)
        s["als_correct"] += int(f.needs_als == v.needs_als)
    return s