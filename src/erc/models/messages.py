"""Structured communication protocol between agents.

Agents never exchange free-form text. Every message is a validated
AgentMessage, so negotiation is reproducible, loggable, and measurable.
"""
from __future__ import annotations

from enum import Enum

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from erc.models.entities import Capability, ResponderType, Severity, StrictModel

MAX_NEGOTIATION_ROUNDS = 3


class AgentName(str, Enum):
    ASSESSMENT = "incident_assessment"
    DISPATCH = "dispatch"
    HOSPITAL = "hospital_coordination"
    RESOURCE_ALLOCATION = "resource_allocation"
    SIMULATOR = "simulator"


class MessageType(str, Enum):
    INFO = "info"
    REQUEST = "request"
    PROPOSAL = "proposal"
    COUNTER_PROPOSAL = "counter_proposal"
    ACCEPT = "accept"
    REJECT = "reject"
    ESCALATE = "escalate"
    COMMIT = "commit"


ACTION_REQUIRED = {MessageType.REQUEST, MessageType.PROPOSAL,
                   MessageType.COUNTER_PROPOSAL, MessageType.COMMIT}
REPLY_REQUIRED = {MessageType.COUNTER_PROPOSAL, MessageType.ACCEPT, MessageType.REJECT}


class ActionType(str, Enum):
    ASSIGN_AMBULANCE = "assign_ambulance"
    ASSIGN_RESPONDER = "assign_responder"
    ADMIT_PATIENT = "admit_patient"
    DIVERT_PATIENT = "divert_patient"
    LOAN_STAFF = "loan_staff"                 # v3: lend doctor + nurse team(s) and a treatment slot to another hospital


class LoanSpec(StrictModel):
    """Terms of a staff loan. Counts and durations are checked by the validator, not here."""
    lender_id: str
    borrower_id: str
    capability: Capability
    teams: int
    duration_min: int
    serves: list[str] = Field(default_factory=list, description="Queued victims this loan is meant to help")


class ProposedAction(StrictModel):
    action_type: ActionType
    ambulance_id: str | None = None
    responder_id: str | None = None
    hospital_id: str | None = None
    victim_ids: list[str] = Field(default_factory=list)
    loan: LoanSpec | None = Field(default=None, exclude_if=lambda v: v is None)   # omitted unless a loan

    @model_validator(mode="after")
    def _has_required_ids(self) -> ProposedAction:
        need = {
            ActionType.LOAN_STAFF: ("loan", self.loan),
            ActionType.ASSIGN_AMBULANCE: ("ambulance_id", self.ambulance_id),
            ActionType.ASSIGN_RESPONDER: ("responder_id", self.responder_id),
            ActionType.ADMIT_PATIENT: ("hospital_id", self.hospital_id),
            ActionType.DIVERT_PATIENT: ("hospital_id", self.hospital_id),
        }[self.action_type]
        if need[1] is None:
            raise ValueError(f"{self.action_type.value} requires {need[0]}")
        if self.action_type in (ActionType.ADMIT_PATIENT, ActionType.DIVERT_PATIENT) and not self.victim_ids:
            raise ValueError(f"{self.action_type.value} requires victim_ids")
        return self


class AgentMessage(StrictModel):
    # The five fields required by the assignment brief
    sender: AgentName
    recipient: AgentName
    message_type: MessageType
    incident_id: str
    proposed_action: ProposedAction | None = None
    # Extensions for negotiation and analysis
    message_id: str
    timestamp_min: int = Field(ge=0)
    priority: int = Field(ge=1, le=5, description="1 = highest")
    reason: str = Field(min_length=1, max_length=500)
    alternative: ProposedAction | None = None
    deadline_min: int | None = Field(default=None, ge=0)
    negotiation_id: str | None = None
    round: int = Field(default=0, ge=0, le=MAX_NEGOTIATION_ROUNDS)
    in_reply_to: str | None = None
    # v3: one Hospital Coordination instance per hospital (ids like hospital_coordination:H-T)
    sender_instance: str | None = Field(default=None, exclude_if=lambda v: v is None)
    recipient_instance: str | None = Field(default=None, exclude_if=lambda v: v is None)

    @property
    def sender_id(self) -> str:
        return f"{self.sender.value}:{self.sender_instance}" if self.sender_instance else self.sender.value

    @property
    def recipient_id(self) -> str:
        return f"{self.recipient.value}:{self.recipient_instance}" if self.recipient_instance else self.recipient.value

    @model_serializer(mode="wrap")
    def _with_ids(self, handler: SerializerFunctionWrapHandler) -> dict:
        data = handler(self)
        if self.sender_instance:
            data["sender_id"] = self.sender_id
        if self.recipient_instance:
            data["recipient_id"] = self.recipient_id
        return data

    @model_validator(mode="after")
    def _protocol_rules(self) -> AgentMessage:
        if self.sender == self.recipient and self.sender_id == self.recipient_id:
            raise ValueError("An agent cannot message itself")
        if self.message_type in ACTION_REQUIRED and self.proposed_action is None:
            raise ValueError(f"{self.message_type.value} requires a proposed_action")
        if self.message_type in REPLY_REQUIRED and self.in_reply_to is None:
            raise ValueError(f"{self.message_type.value} must reply to an earlier message")
        if self.message_type == MessageType.COUNTER_PROPOSAL and self.negotiation_id is None:
            raise ValueError("counter_proposal must belong to a negotiation")
        return self


class RejectionReason(str, Enum):
    UNKNOWN_RESOURCE = "unknown_resource"
    AMBULANCE_UNAVAILABLE = "ambulance_unavailable"
    AMBULANCE_CAPABILITY_MISMATCH = "ambulance_capability_mismatch"
    AMBULANCE_OVER_CAPACITY = "ambulance_over_capacity"
    NO_FEASIBLE_DESTINATION = "no_feasible_destination"
    RESPONDER_UNAVAILABLE = "responder_unavailable"
    VICTIM_UNAVAILABLE = "victim_unavailable"
    HOSPITAL_FULL = "hospital_full"
    HOSPITAL_LACKS_CAPABILITY = "hospital_lacks_capability"
    ROUTING_CONFLICT = "routing_conflict"
    STAFF_UNAVAILABLE = "staff_unavailable"
    LOAN_NOT_NEEDED = "loan_not_needed"
    LENDER_NO_IDLE_SLOT = "lender_no_idle_slot"
    LENDER_UNDERSTAFFED = "lender_understaffed"
    BORROWER_BEDS_FULL = "borrower_beds_full"
    INCIDENT_NOT_ACTIVE = "incident_not_active"
    MALFORMED = "malformed"


class ValidationResult(StrictModel):
    """The validator's verdict on one proposed action."""
    accepted: bool
    reason: RejectionReason | None = None
    detail: str = ""

    @model_validator(mode="after")
    def _reason_iff_rejected(self) -> ValidationResult:
        if not self.accepted and self.reason is None:
            raise ValueError("A rejection must include a reason")
        if self.accepted and self.reason is not None:
            raise ValueError("An accepted action cannot have a rejection reason")
        return self


class VictimAssessment(StrictModel):
    """One person's assessed condition, mapped to a victim ID."""
    victim_id: str
    severity: Severity
    required_capability: Capability
    needs_als: bool


class AssessmentReport(StrictModel):
    """What the Assessment Agent concludes about one incident from its text report."""
    incident_id: str
    victims: list[VictimAssessment] = Field(min_length=1)
    reported_victim_count: int = Field(ge=0, description="How many people the agent found in the report")
    required_responder: ResponderType | None = None
    priority_score: int = Field(ge=0, le=100)
    reasoning: str = Field(min_length=1, max_length=1000)

    @property
    def max_severity(self) -> Severity:
        return max(v.severity for v in self.victims)