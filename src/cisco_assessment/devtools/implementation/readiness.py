"""Deterministic readiness evaluation for Implementation Agent v0.1."""

from __future__ import annotations

from ..pr_review import ComponentId
from .enums import ImplementationDecision, ImplementationGateStatus
from .gate_ids import ImplementationGateId
from .models import ImplementationGate, ImplementationReadinessReport, ImplementationRequest


def evaluate_implementation_readiness(
    request: ImplementationRequest,
) -> ImplementationReadinessReport:
    """Evaluate one request without mutating the repository or executing Cisco commands."""
    missing_evidence_ids = _missing_evidence_ids(request)
    gates = (
        _contract_gate(request),
        _scope_gate(request),
        _evidence_gate(missing_evidence_ids),
        _safety_gate(request),
        _authorization_gate(request),
    )
    decision, reason = _derive_decision(gates)
    return ImplementationReadinessReport(
        repository=request.repository,
        objective=request.objective,
        authorization=request.authorization,
        gates=gates,
        missing_evidence_ids=missing_evidence_ids,
        decision=decision,
        decision_reason=reason,
    )


def _contract_gate(request: ImplementationRequest) -> ImplementationGate:
    if request.contract_approved:
        return ImplementationGate(
            gate_id=ImplementationGateId.CONTRACT_APPROVED,
            status=ImplementationGateStatus.PASS,
            summary="Implementation contract is explicitly approved.",
        )
    return ImplementationGate(
        gate_id=ImplementationGateId.CONTRACT_APPROVED,
        status=ImplementationGateStatus.NEEDS_HUMAN_INPUT,
        summary="Implementation contract requires explicit human approval before execution.",
    )


def _scope_gate(request: ImplementationRequest) -> ImplementationGate:
    if ComponentId.UNKNOWN in request.authorized_components:
        return ImplementationGate(
            gate_id=ImplementationGateId.SCOPE_EXPLICIT,
            status=ImplementationGateStatus.BLOCKED,
            summary="Authorized scope contains UNKNOWN and cannot be executed deterministically.",
        )
    return ImplementationGate(
        gate_id=ImplementationGateId.SCOPE_EXPLICIT,
        status=ImplementationGateStatus.PASS,
        summary="Authorized implementation components are explicit.",
    )


def _evidence_gate(missing_evidence_ids: tuple[str, ...]) -> ImplementationGate:
    if missing_evidence_ids:
        return ImplementationGate(
            gate_id=ImplementationGateId.EVIDENCE_COMPLETE,
            status=ImplementationGateStatus.NEEDS_HUMAN_INPUT,
            summary=(
                f"{len(missing_evidence_ids)} required evidence item(s) are not available."
            ),
        )
    return ImplementationGate(
        gate_id=ImplementationGateId.EVIDENCE_COMPLETE,
        status=ImplementationGateStatus.PASS,
        summary="All required evidence IDs are available.",
    )


def _safety_gate(request: ImplementationRequest) -> ImplementationGate:
    return ImplementationGate(
        gate_id=ImplementationGateId.SAFETY_BOUNDARIES,
        status=ImplementationGateStatus.PASS,
        summary=(
            "Human merge gate is mandatory and Cisco execution is disabled by contract "
            f"(merge_gate={request.human_merge_gate_required}, "
            f"cisco_execution={request.cisco_execution_allowed})."
        ),
    )


def _authorization_gate(request: ImplementationRequest) -> ImplementationGate:
    return ImplementationGate(
        gate_id=ImplementationGateId.MUTATION_AUTHORIZATION,
        status=ImplementationGateStatus.PASS,
        summary=f"Repository mutation authorization is {request.authorization.value}.",
    )


def _missing_evidence_ids(request: ImplementationRequest) -> tuple[str, ...]:
    available = {item.evidence_id for item in request.available_evidence}
    return tuple(
        evidence_id
        for evidence_id in request.required_evidence_ids
        if evidence_id not in available
    )


def _derive_decision(
    gates: tuple[ImplementationGate, ...],
) -> tuple[ImplementationDecision, str]:
    if any(gate.status is ImplementationGateStatus.BLOCKED for gate in gates):
        return (
            ImplementationDecision.BLOCKED,
            "At least one implementation-readiness gate is blocked.",
        )
    if any(gate.status is ImplementationGateStatus.NEEDS_HUMAN_INPUT for gate in gates):
        return (
            ImplementationDecision.NEEDS_HUMAN_INPUT,
            "Human approval or required evidence is still missing.",
        )
    return (
        ImplementationDecision.READY,
        "All implementation-readiness gates passed within the granted authorization.",
    )
