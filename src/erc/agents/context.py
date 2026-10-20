"""Shared context for one agent decision round: what agents may see, and where proposals go."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from erc.models.messages import AgentName, AssessmentReport, ProposedAction
from erc.models.state import SimulationState


class Proposal(BaseModel):
    proposal_id: str
    proposer: AgentName
    incident_id: str
    action: ProposedAction
    priority: int = Field(ge=1, le=5, description="Proposer's urgency, 1 = highest")
    reason: str
    time_min: int


@dataclass
class AgentContext:
    state: SimulationState
    assessments: dict[str, AssessmentReport]          # incident_id -> report (never ground truth)
    round_id: str = "R0"
    proposals: list[Proposal] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)  # rejected submissions, for the reliability metric

    def next_proposal_id(self) -> str:
        return f"{self.round_id}-P{len(self.proposals) + 1:02d}"

    def snapshot_since(self, n_proposals: int, n_invalid: int) -> dict:
        """What one agent run added, so a cached rerun can replay it exactly."""
        return {"proposals": [p.model_dump(mode="json") for p in self.proposals[n_proposals:]],
                "invalid": self.invalid[n_invalid:]}

    def restore(self, data: dict) -> None:
        self.proposals += [Proposal.model_validate(p) for p in data.get("proposals", [])]
        self.invalid += data.get("invalid", [])


def state_fingerprint(state: SimulationState) -> str:
    """Short hash of the full state; goes into prompts so cache keys reflect the exact situation."""
    return hashlib.sha256(state.model_dump_json().encode()).hexdigest()[:16]