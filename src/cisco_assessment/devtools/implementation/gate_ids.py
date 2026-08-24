"""Stable readiness-gate identifiers for Implementation Agent v0.1."""

from enum import StrEnum


class ImplementationGateId(StrEnum):
    """Stable IDs for deterministic implementation-readiness gates."""

    CONTRACT_APPROVED = "IMPL-001"
    SCOPE_EXPLICIT = "IMPL-002"
    EVIDENCE_COMPLETE = "IMPL-003"
    SAFETY_BOUNDARIES = "IMPL-004"
    MUTATION_AUTHORIZATION = "IMPL-005"
