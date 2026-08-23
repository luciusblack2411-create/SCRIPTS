"""Stable enums for Implementation Agent v0.1."""

from enum import StrEnum


class ImplementationDecision(StrEnum):
    """Deterministic readiness decision for an implementation request."""

    READY = "READY"
    NEEDS_HUMAN_INPUT = "NEEDS_HUMAN_INPUT"
    BLOCKED = "BLOCKED"


class ImplementationGateStatus(StrEnum):
    """Outcome of one implementation-readiness gate."""

    PASS = "PASS"
    NEEDS_HUMAN_INPUT = "NEEDS_HUMAN_INPUT"
    BLOCKED = "BLOCKED"


class ImplementationAuthorization(StrEnum):
    """Maximum repository mutation explicitly granted to the agent."""

    PLAN_ONLY = "PLAN_ONLY"
    WORK_BRANCH = "WORK_BRANCH"
    DRAFT_PR = "DRAFT_PR"


class ImplementationEvidenceKind(StrEnum):
    """Stable evidence categories consumed by implementation readiness."""

    CONTRACT = "CONTRACT"
    RAW_FIXTURE = "RAW_FIXTURE"
    SOURCE = "SOURCE"
    ISSUE = "ISSUE"
    HANDOFF = "HANDOFF"
    TEST = "TEST"
    CI = "CI"
    OTHER = "OTHER"


class ImplementationPlanStepKind(StrEnum):
    """Stable kinds of non-executing implementation-plan steps."""

    OBSERVE_CONTEXT = "OBSERVE_CONTEXT"
    PRESERVE_CONTRACTS = "PRESERVE_CONTRACTS"
    APPLY_APPROVED_CONTRACT_CHANGES = "APPLY_APPROVED_CONTRACT_CHANGES"
    IMPLEMENT_COMPONENT = "IMPLEMENT_COMPONENT"
    VERIFY_ACCEPTANCE = "VERIFY_ACCEPTANCE"
    PREPARE_DRAFT_PR = "PREPARE_DRAFT_PR"


class ImplementationFileChangeKind(StrEnum):
    """Stable proposal-only source-file change kinds supported by v0.1."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
