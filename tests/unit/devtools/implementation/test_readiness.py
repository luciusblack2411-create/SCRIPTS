from __future__ import annotations

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationDecision,
    ImplementationEvidence,
    ImplementationEvidenceKind,
    ImplementationGateId,
    ImplementationGateStatus,
    ImplementationRequest,
    evaluate_implementation_readiness,
)


def _request(
    *,
    contract_approved: bool = True,
    authorized_components: tuple[ComponentId, ...] = (ComponentId.PARSER,),
    required_evidence_ids: tuple[str, ...] = (),
    available_evidence: tuple[ImplementationEvidence, ...] = (),
) -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Implement approved parser behavior.",
        authorized_components=authorized_components,
        prohibited_components=(ComponentId.COLLECTOR, ComponentId.RULES),
        invariants=("Parser remains extraction-only.",),
        acceptance_criteria=("Unit tests cover the approved behavior.",),
        required_evidence_ids=required_evidence_ids,
        available_evidence=available_evidence,
        contract_approved=contract_approved,
        authorization=ImplementationAuthorization.DRAFT_PR,
    )


def test_readiness_gate_order_is_stable() -> None:
    report = evaluate_implementation_readiness(_request())

    assert tuple(gate.gate_id for gate in report.gates) == (
        ImplementationGateId.CONTRACT_APPROVED,
        ImplementationGateId.SCOPE_EXPLICIT,
        ImplementationGateId.EVIDENCE_COMPLETE,
        ImplementationGateId.SAFETY_BOUNDARIES,
        ImplementationGateId.MUTATION_AUTHORIZATION,
    )


def test_unapproved_contract_requires_human_input() -> None:
    report = evaluate_implementation_readiness(_request(contract_approved=False))

    assert report.decision is ImplementationDecision.NEEDS_HUMAN_INPUT
    assert report.gates[0].status is ImplementationGateStatus.NEEDS_HUMAN_INPUT


def test_missing_required_evidence_requires_human_input_without_inference() -> None:
    report = evaluate_implementation_readiness(
        _request(required_evidence_ids=("raw-real-001", "cisco-source-001"))
    )

    assert report.decision is ImplementationDecision.NEEDS_HUMAN_INPUT
    assert report.missing_evidence_ids == ("raw-real-001", "cisco-source-001")
    assert report.gates[2].status is ImplementationGateStatus.NEEDS_HUMAN_INPUT


def test_unknown_authorized_component_blocks_execution() -> None:
    report = evaluate_implementation_readiness(
        _request(authorized_components=(ComponentId.UNKNOWN,))
    )

    assert report.decision is ImplementationDecision.BLOCKED
    assert report.gates[1].status is ImplementationGateStatus.BLOCKED


def test_complete_approved_request_is_ready_within_granted_authorization() -> None:
    raw = ImplementationEvidence(
        evidence_id="raw-real-001",
        kind=ImplementationEvidenceKind.RAW_FIXTURE,
        description="Sanitized real RAW fixture.",
        reference="tests/fixtures/example.raw",
    )
    source = ImplementationEvidence(
        evidence_id="cisco-source-001",
        kind=ImplementationEvidenceKind.SOURCE,
        description="Applicable official Cisco command reference.",
    )
    report = evaluate_implementation_readiness(
        _request(
            required_evidence_ids=("raw-real-001", "cisco-source-001"),
            available_evidence=(raw, source),
        )
    )

    assert report.decision is ImplementationDecision.READY
    assert report.missing_evidence_ids == ()
    assert all(gate.status is ImplementationGateStatus.PASS for gate in report.gates)
    assert report.authorization is ImplementationAuthorization.DRAFT_PR
