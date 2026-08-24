"""Feature intake and explicit contract-approval boundary for Implementation Agent v0.1."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..pr_review import ComponentId
from .enums import ImplementationAuthorization
from .models import ImplementationEvidence, ImplementationRequest

FEATURE_INTAKE_ID: Literal["FEATURE_INTAKE_V1"] = "FEATURE_INTAKE_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class FeatureIntakeError(RuntimeError):
    """Raised when a feature contract cannot be proposed or approved safely."""


class FrozenFeatureIntakeModel(BaseModel):
    """Strict immutable base model for feature-intake contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FeatureRequest(FrozenFeatureIntakeModel):
    """Raw human feature intent plus only evidence and mutation bounds supplied explicitly."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    intake_id: Literal["FEATURE_INTAKE_V1"] = FEATURE_INTAKE_ID
    repository: str = Field(min_length=1)
    expected_base_branch: str = Field(default="main", min_length=1)
    request_text: str = Field(min_length=1)
    requested_max_authorization: ImplementationAuthorization = ImplementationAuthorization.PLAN_ONLY
    explicit_evidence: tuple[ImplementationEvidence, ...] = ()
    related_issue_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_explicit_evidence(self) -> FeatureRequest:
        """Reject duplicate evidence IDs instead of silently collapsing supplied evidence."""
        evidence_ids = tuple(item.evidence_id for item in self.explicit_evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("explicit_evidence evidence_id values must be unique")
        return self


class FeatureContractProposalDraft(FrozenFeatureIntakeModel):
    """Semantic proposal input; it has no approval or repository-mutation authority."""

    objective: str = Field(min_length=1)
    authorized_components: tuple[ComponentId, ...] = Field(min_length=1)
    prohibited_components: tuple[ComponentId, ...] = ()
    contracts_to_preserve: tuple[str, ...] = ()
    contracts_to_change: tuple[str, ...] = ()
    invariants: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    required_evidence_ids: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    maximum_authorization: ImplementationAuthorization = ImplementationAuthorization.PLAN_ONLY


class FeatureContractProposal(FrozenFeatureIntakeModel):
    """Base-bound implementation contract proposal that always requires human approval."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    intake_id: Literal["FEATURE_INTAKE_V1"] = FEATURE_INTAKE_ID
    request: FeatureRequest
    base_sha: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    authorized_components: tuple[ComponentId, ...] = Field(min_length=1)
    prohibited_components: tuple[ComponentId, ...] = ()
    contracts_to_preserve: tuple[str, ...] = ()
    contracts_to_change: tuple[str, ...] = ()
    invariants: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    required_evidence_ids: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    maximum_authorization: ImplementationAuthorization
    contract_approved: Literal[False] = False
    requires_human_approval: Literal[True] = True
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


class FeatureContractApproval(FrozenFeatureIntakeModel):
    """Explicit human approval bound to one exact proposal hash and base SHA."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    intake_id: Literal["FEATURE_INTAKE_V1"] = FEATURE_INTAKE_ID
    decision: Literal["CONTRACT_APPROVED"]
    repository: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization: ImplementationAuthorization
    authorized_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


_AUTHORIZATION_ORDER: dict[ImplementationAuthorization, int] = {
    ImplementationAuthorization.PLAN_ONLY: 0,
    ImplementationAuthorization.WORK_BRANCH: 1,
    ImplementationAuthorization.DRAFT_PR: 2,
}


def build_feature_contract_proposal(
    request: FeatureRequest,
    draft: FeatureContractProposalDraft,
    *,
    base_sha: str,
) -> FeatureContractProposal:
    """Validate one semantic proposal without inferring approval, evidence, or Cisco authority."""
    request = FeatureRequest.model_validate(request.model_dump(mode="python"))
    draft = FeatureContractProposalDraft.model_validate(draft.model_dump(mode="python"))
    if not base_sha.strip():
        raise FeatureIntakeError("base_sha must not be empty")
    if ComponentId.UNKNOWN in draft.authorized_components:
        raise FeatureIntakeError("authorized_components must not contain UNKNOWN")
    if set(draft.authorized_components).intersection(draft.prohibited_components):
        raise FeatureIntakeError(
            "authorized_components and prohibited_components must not overlap"
        )
    if set(draft.contracts_to_preserve).intersection(draft.contracts_to_change):
        raise FeatureIntakeError(
            "contracts_to_preserve and contracts_to_change must not overlap"
        )
    _require_unique("authorized_components", draft.authorized_components)
    _require_unique("prohibited_components", draft.prohibited_components)
    _require_unique("contracts_to_preserve", draft.contracts_to_preserve)
    _require_unique("contracts_to_change", draft.contracts_to_change)
    _require_unique("required_evidence_ids", draft.required_evidence_ids)
    _require_unique("ambiguities", draft.ambiguities)
    if _AUTHORIZATION_ORDER[draft.maximum_authorization] > _AUTHORIZATION_ORDER[
        request.requested_max_authorization
    ]:
        raise FeatureIntakeError(
            "proposal maximum_authorization exceeds the FeatureRequest mutation bound"
        )
    return FeatureContractProposal(
        request=request,
        base_sha=base_sha,
        objective=draft.objective,
        authorized_components=draft.authorized_components,
        prohibited_components=draft.prohibited_components,
        contracts_to_preserve=draft.contracts_to_preserve,
        contracts_to_change=draft.contracts_to_change,
        invariants=draft.invariants,
        acceptance_criteria=draft.acceptance_criteria,
        required_evidence_ids=draft.required_evidence_ids,
        ambiguities=draft.ambiguities,
        maximum_authorization=draft.maximum_authorization,
    )


def feature_contract_proposal_sha256(proposal: FeatureContractProposal) -> str:
    """Return a deterministic SHA-256 over the complete canonical proposal payload."""
    proposal = FeatureContractProposal.model_validate(proposal.model_dump(mode="python"))
    payload = json.dumps(
        proposal.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def approve_feature_contract(
    proposal: FeatureContractProposal,
    approval: FeatureContractApproval,
) -> ImplementationRequest:
    """Transform one exact approved proposal into the existing ImplementationRequest contract."""
    proposal = FeatureContractProposal.model_validate(proposal.model_dump(mode="python"))
    approval = FeatureContractApproval.model_validate(approval.model_dump(mode="python"))
    expected_hash = feature_contract_proposal_sha256(proposal)
    if approval.repository != proposal.request.repository:
        raise FeatureIntakeError("approval repository does not match the proposal")
    if approval.base_sha != proposal.base_sha:
        raise FeatureIntakeError("approval base_sha does not match the proposal")
    if approval.proposal_sha256 != expected_hash:
        raise FeatureIntakeError("approval proposal_sha256 does not match the proposal")
    if _AUTHORIZATION_ORDER[approval.authorization] > _AUTHORIZATION_ORDER[
        proposal.maximum_authorization
    ]:
        raise FeatureIntakeError(
            "approved authorization exceeds the proposal maximum_authorization"
        )
    return ImplementationRequest(
        repository=proposal.request.repository,
        expected_base_branch=proposal.request.expected_base_branch,
        objective=proposal.objective,
        authorized_components=proposal.authorized_components,
        prohibited_components=proposal.prohibited_components,
        contracts_to_preserve=proposal.contracts_to_preserve,
        contracts_to_change=proposal.contracts_to_change,
        invariants=proposal.invariants,
        acceptance_criteria=proposal.acceptance_criteria,
        required_evidence_ids=proposal.required_evidence_ids,
        available_evidence=proposal.request.explicit_evidence,
        contract_approved=True,
        authorization=approval.authorization,
        related_issue_ids=proposal.request.related_issue_ids,
    )


def _require_unique(label: str, values: tuple[object, ...]) -> None:
    if len(set(values)) != len(values):
        raise FeatureIntakeError(f"{label} values must be unique")
