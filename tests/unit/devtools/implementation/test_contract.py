from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationEvidence,
    ImplementationEvidenceKind,
    ImplementationRequest,
)


def _base_request() -> dict[str, object]:
    return {
        "repository": "owner/repo",
        "objective": "Implement an approved parser adapter.",
        "authorized_components": (ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
        "prohibited_components": (ComponentId.COLLECTOR, ComponentId.RULES),
        "invariants": ("Parser remains extraction-only.",),
        "acceptance_criteria": ("Unit tests cover the approved behavior.",),
    }


def test_request_is_frozen_and_forbids_extra_fields() -> None:
    request = ImplementationRequest.model_validate(_base_request())

    with pytest.raises(ValidationError):
        request.__setattr__("objective", "mutated")

    payload = _base_request()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ImplementationRequest.model_validate(payload)


def test_request_rejects_authorized_and_prohibited_scope_overlap() -> None:
    payload = _base_request()
    payload["prohibited_components"] = (ComponentId.PARSER,)

    with pytest.raises(ValidationError, match="must not overlap"):
        ImplementationRequest.model_validate(payload)


def test_request_rejects_contract_preserve_change_overlap() -> None:
    payload = _base_request()
    payload["contracts_to_preserve"] = ("ParserId.IOS_EXAMPLE_V1",)
    payload["contracts_to_change"] = ("ParserId.IOS_EXAMPLE_V1",)

    with pytest.raises(ValidationError, match="must not overlap"):
        ImplementationRequest.model_validate(payload)


def test_request_rejects_duplicate_evidence_ids() -> None:
    payload = _base_request()
    payload["required_evidence_ids"] = ("raw-001", "raw-001")

    with pytest.raises(ValidationError, match="required_evidence_ids must be unique"):
        ImplementationRequest.model_validate(payload)

    evidence = ImplementationEvidence(
        evidence_id="raw-001",
        kind=ImplementationEvidenceKind.RAW_FIXTURE,
        description="Sanitized real RAW fixture.",
    )
    payload = _base_request()
    payload["available_evidence"] = (evidence, evidence)

    with pytest.raises(ValidationError, match="available_evidence evidence_id values must be unique"):
        ImplementationRequest.model_validate(payload)


def test_request_cannot_disable_human_merge_gate_or_enable_cisco_execution() -> None:
    payload = _base_request()
    payload["human_merge_gate_required"] = False

    with pytest.raises(ValidationError):
        ImplementationRequest.model_validate(payload)

    payload = _base_request()
    payload["cisco_execution_allowed"] = True

    with pytest.raises(ValidationError):
        ImplementationRequest.model_validate(payload)


def test_mutation_authorization_has_no_merge_mode() -> None:
    assert tuple(ImplementationAuthorization) == (
        ImplementationAuthorization.PLAN_ONLY,
        ImplementationAuthorization.WORK_BRANCH,
        ImplementationAuthorization.DRAFT_PR,
    )
