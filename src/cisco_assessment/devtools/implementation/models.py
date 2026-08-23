"""Typed contracts for Implementation Agent v0.1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..pr_review import ComponentId
from .enums import (
    ImplementationAuthorization,
    ImplementationDecision,
    ImplementationEvidenceKind,
    ImplementationGateStatus,
)
from .gate_ids import ImplementationGateId

AGENT_ID: Literal["IMPLEMENTATION_AGENT_V1"] = "IMPLEMENTATION_AGENT_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class FrozenImplementationModel(BaseModel):
    """Strict immutable base model for implementation-agent contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ImplementationEvidence(FrozenImplementationModel):
    """Evidence explicitly available to an implementation request."""

    evidence_id: str = Field(min_length=1)
    kind: ImplementationEvidenceKind
    description: str = Field(min_length=1)
    reference: str | None = None
    commit_sha: str | None = None
    sha256: str | None = None


class ImplementationRequest(FrozenImplementationModel):
    """Approved implementation scope and the evidence required to execute it safely."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    expected_base_branch: str = Field(default="main", min_length=1)
    objective: str = Field(min_length=1)
    authorized_components: tuple[ComponentId, ...] = Field(min_length=1)
    prohibited_components: tuple[ComponentId, ...] = ()
    contracts_to_preserve: tuple[str, ...] = ()
    contracts_to_change: tuple[str, ...] = ()
    invariants: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    required_evidence_ids: tuple[str, ...] = ()
    available_evidence: tuple[ImplementationEvidence, ...] = ()
    contract_approved: bool = False
    authorization: ImplementationAuthorization = ImplementationAuthorization.PLAN_ONLY
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False
    related_issue_ids: tuple[str, ...] = ()
    handoff_text: str | None = None

    @model_validator(mode="after")
    def validate_request_contract(self) -> ImplementationRequest:
        """Reject ambiguous scope, conflicting contracts, and duplicate evidence IDs."""
        if set(self.authorized_components).intersection(self.prohibited_components):
            raise ValueError("authorized_components and prohibited_components must not overlap")
        if set(self.contracts_to_preserve).intersection(self.contracts_to_change):
            raise ValueError("contracts_to_preserve and contracts_to_change must not overlap")
        if len(set(self.required_evidence_ids)) != len(self.required_evidence_ids):
            raise ValueError("required_evidence_ids must be unique")
        available_ids = tuple(item.evidence_id for item in self.available_evidence)
        if len(set(available_ids)) != len(available_ids):
            raise ValueError("available_evidence evidence_id values must be unique")
        return self


class ImplementationGate(FrozenImplementationModel):
    """Result of evaluating one stable readiness gate."""

    gate_id: ImplementationGateId
    status: ImplementationGateStatus
    summary: str = Field(min_length=1)


class ImplementationReadinessReport(FrozenImplementationModel):
    """Canonical result of evaluating whether an implementation may proceed."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    authorization: ImplementationAuthorization
    gates: tuple[ImplementationGate, ...]
    missing_evidence_ids: tuple[str, ...]
    decision: ImplementationDecision
    decision_reason: str = Field(min_length=1)
