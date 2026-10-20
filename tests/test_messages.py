"""Tests: the message protocol must reject malformed communication."""
import pytest
from pydantic import ValidationError

from erc.models.messages import (
    ActionType, AgentMessage, AgentName, MessageType, ProposedAction,
    RejectionReason, ValidationResult,
)

AMB = ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE, ambulance_id="AMB-02")


def msg(**overrides):
    base = dict(sender=AgentName.DISPATCH, recipient=AgentName.RESOURCE_ALLOCATION,
                message_type=MessageType.REQUEST, incident_id="INC-07", proposed_action=AMB,
                message_id="M-1", timestamp_min=23, priority=1, reason="Critical trauma, 3 victims")
    base.update(overrides)
    return AgentMessage(**base)


def test_valid_request():
    m = msg()
    assert m.proposed_action.ambulance_id == "AMB-02"


def test_cannot_message_self():
    with pytest.raises(ValidationError):
        msg(recipient=AgentName.DISPATCH)


def test_request_needs_action():
    with pytest.raises(ValidationError):
        msg(proposed_action=None)


def test_counter_proposal_needs_reply_and_negotiation():
    with pytest.raises(ValidationError):
        msg(message_type=MessageType.COUNTER_PROPOSAL)
    ok = msg(message_type=MessageType.COUNTER_PROPOSAL, in_reply_to="M-0", negotiation_id="N-1", round=1)
    assert ok.round == 1


def test_round_limit_enforced():
    with pytest.raises(ValidationError):
        msg(message_type=MessageType.COUNTER_PROPOSAL, in_reply_to="M-0", negotiation_id="N-1", round=4)


def test_action_missing_ids_rejected():
    with pytest.raises(ValidationError):
        ProposedAction(action_type=ActionType.ASSIGN_AMBULANCE)
    with pytest.raises(ValidationError):
        ProposedAction(action_type=ActionType.ADMIT_PATIENT, hospital_id="H-T")


def test_validation_result_rules():
    with pytest.raises(ValidationError):
        ValidationResult(accepted=False)
    r = ValidationResult(accepted=False, reason=RejectionReason.AMBULANCE_UNAVAILABLE)
    assert r.reason == RejectionReason.AMBULANCE_UNAVAILABLE