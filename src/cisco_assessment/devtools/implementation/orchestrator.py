"""In-memory feature orchestration checkpoints built from existing protected gate artifacts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..pr_review.enums import ReviewDecision
from ..ready_for_review import ReadyForReviewDecision, ReadyForReviewResult
from .ci_validation import ImplementationOperationalDecision
from .draft_pr import ImplementationDraftPrDecision, ImplementationDraftPrResult
from .feature_intake import (
    FeatureContractApproval,
    FeatureContractProposal,
    FeatureRequest,
    approve_feature_contract,
    feature_contract_proposal_sha256,
)
from .models import FrozenImplementationModel, ImplementationRequest
from .operational import ImplementationOperationalResult
from .workspace import ImplementationWorkspace

ORCHESTRATOR_ID: Literal["FEATURE_ORCHESTRATOR_V1"] = "FEATURE_ORCHESTRATOR_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class FeatureOrchestrationError(RuntimeError):
    """Raised when an orchestration checkpoint cannot be advanced safely."""


class FeatureOrchestrationState(StrEnum):
    """Stable in-memory states for v0.1 feature delivery orchestration."""

    FEATURE_RECEIVED = "FEATURE_RECEIVED"
    NEEDS_CONTRACT_APPROVAL = "NEEDS_CONTRACT_APPROVAL"
    IMPLEMENTATION_READY = "IMPLEMENTATION_READY"
    WORKSPACE_VALIDATED = "WORKSPACE_VALIDATED"
    CI_PASSED = "CI_PASSED"
    DRAFT_PR_CREATED = "DRAFT_PR_CREATED"
    HUMAN_MERGE_GATE = "HUMAN_MERGE_GATE"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"
    BLOCKED = "BLOCKED"


class FeatureOrchestrationRun(FrozenImplementationModel):
    """Canonical in-memory checkpoint for one feature run.

    This model records evidence from existing contracts only. It does not execute
    repository mutation, PR transitions, merge, or Cisco commands.
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    orchestrator_id: Literal["FEATURE_ORCHESTRATOR_V1"] = ORCHESTRATOR_ID
    run_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    request_text: str = Field(min_length=1)
    objective: str | None = None
    state: FeatureOrchestrationState
    feature_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    implementation_request_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    workspace_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    operational_result_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    draft_pr_result_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    review_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ready_result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    work_branch: str | None = None
    commit_sha: str | None = None
    ci_run_id: int | None = Field(default=None, gt=0)
    pr_number: int | None = Field(default=None, gt=0)
    pr_url: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_checkpoint_contract(self) -> FeatureOrchestrationRun:
        """Require coherent evidence density as a run advances."""
        if self.proposal_sha256 is not None and self.objective is None:
            raise ValueError("proposal evidence requires an objective")
        if self.implementation_request_sha256 is not None and self.proposal_sha256 is None:
            raise ValueError("implementation request evidence requires proposal evidence")
        if self.workspace_sha256 is not None and self.implementation_request_sha256 is None:
            raise ValueError("workspace evidence requires an approved implementation request")
        if self.commit_sha is not None and self.work_branch is None:
            raise ValueError("commit evidence requires a work branch")
        pr_values = (self.pr_number, self.pr_url, self.head_branch, self.head_sha)
        if any(value is not None for value in pr_values) and not all(
            value is not None for value in pr_values
        ):
            raise ValueError("pull-request evidence must be complete")
        if self.state is FeatureOrchestrationState.HUMAN_MERGE_GATE:
            if self.ready_result_sha256 is None or self.review_report_sha256 is None:
                raise ValueError("HUMAN_MERGE_GATE requires Ready and review evidence")
            if not all(value is not None for value in pr_values):
                raise ValueError("HUMAN_MERGE_GATE requires complete pull-request refs")
        return self


def orchestration_artifact_sha256(artifact: BaseModel) -> str:
    """Return a deterministic SHA-256 over one complete typed artifact."""
    canonical = json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def begin_feature_orchestration(
    request: FeatureRequest,
    *,
    run_id: str,
    base_sha: str,
) -> FeatureOrchestrationRun:
    """Start an in-memory run from explicit feature intent and one observed base SHA."""
    request = FeatureRequest.model_validate(request.model_dump(mode="python"))
    if not run_id.strip():
        raise FeatureOrchestrationError("run_id must not be blank")
    if not base_sha.strip():
        raise FeatureOrchestrationError("base_sha must not be blank")
    return FeatureOrchestrationRun(
        run_id=run_id,
        repository=request.repository,
        base_branch=request.expected_base_branch,
        base_sha=base_sha,
        request_text=request.request_text,
        state=FeatureOrchestrationState.FEATURE_RECEIVED,
        feature_request_sha256=orchestration_artifact_sha256(request),
    )


def record_contract_proposal(
    run: FeatureOrchestrationRun,
    proposal: FeatureContractProposal,
) -> FeatureOrchestrationRun:
    """Record one exact proposal and stop for explicit contract approval."""
    run = _validated_run(run)
    _require_state(run, FeatureOrchestrationState.FEATURE_RECEIVED)
    proposal = FeatureContractProposal.model_validate(proposal.model_dump(mode="python"))
    if orchestration_artifact_sha256(proposal.request) != run.feature_request_sha256:
        raise FeatureOrchestrationError("proposal FeatureRequest does not match the run")
    if (
        proposal.request.repository != run.repository
        or proposal.request.expected_base_branch != run.base_branch
        or proposal.base_sha != run.base_sha
    ):
        raise FeatureOrchestrationError("proposal repository/base binding does not match the run")
    return run.model_copy(
        update={
            "objective": proposal.objective,
            "proposal_sha256": feature_contract_proposal_sha256(proposal),
            "state": FeatureOrchestrationState.NEEDS_CONTRACT_APPROVAL,
        }
    )


def record_contract_approval(
    run: FeatureOrchestrationRun,
    proposal: FeatureContractProposal,
    approval: FeatureContractApproval,
) -> tuple[FeatureOrchestrationRun, ImplementationRequest]:
    """Use the existing intake approval boundary and record its exact output."""
    run = _validated_run(run)
    _require_state(run, FeatureOrchestrationState.NEEDS_CONTRACT_APPROVAL)
    proposal = FeatureContractProposal.model_validate(proposal.model_dump(mode="python"))
    expected_proposal_hash = feature_contract_proposal_sha256(proposal)
    if expected_proposal_hash != run.proposal_sha256:
        raise FeatureOrchestrationError("approved proposal does not match the run checkpoint")
    request = approve_feature_contract(proposal, approval)
    if request.repository != run.repository or proposal.base_sha != run.base_sha:
        raise FeatureOrchestrationError("approved implementation request is not bound to the run")
    advanced = run.model_copy(
        update={
            "implementation_request_sha256": orchestration_artifact_sha256(request),
            "state": FeatureOrchestrationState.IMPLEMENTATION_READY,
        }
    )
    return advanced, request


def record_workspace_validation(
    run: FeatureOrchestrationRun,
    request: ImplementationRequest,
    workspace: ImplementationWorkspace,
) -> FeatureOrchestrationRun:
    """Record an existing validated workspace without executing repository mutation."""
    run = _validated_run(run)
    _require_state(run, FeatureOrchestrationState.IMPLEMENTATION_READY)
    request = ImplementationRequest.model_validate(request.model_dump(mode="python"))
    workspace = ImplementationWorkspace.model_validate(workspace.model_dump(mode="python"))
    if orchestration_artifact_sha256(request) != run.implementation_request_sha256:
        raise FeatureOrchestrationError("ImplementationRequest does not match the approved run")
    if (
        workspace.repository != run.repository
        or workspace.base_branch != run.base_branch
        or workspace.base_sha != run.base_sha
        or workspace.objective != run.objective
        or workspace.authorization != request.authorization
    ):
        raise FeatureOrchestrationError("workspace binding does not match the run")
    return run.model_copy(
        update={
            "workspace_sha256": orchestration_artifact_sha256(workspace),
            "state": FeatureOrchestrationState.WORKSPACE_VALIDATED,
        }
    )


def record_operational_result(
    run: FeatureOrchestrationRun,
    result: ImplementationOperationalResult,
) -> FeatureOrchestrationRun:
    """Record the existing work-branch/CI result and derive only orchestration state."""
    run = _validated_run(run)
    _require_state(run, FeatureOrchestrationState.WORKSPACE_VALIDATED)
    result = ImplementationOperationalResult.model_validate(result.model_dump(mode="python"))
    mutation = result.mutation
    if (
        result.repository != run.repository
        or result.objective != run.objective
        or mutation.base_branch != run.base_branch
        or mutation.base_sha != run.base_sha
        or mutation.workspace_sha256 != run.workspace_sha256
    ):
        raise FeatureOrchestrationError("operational result does not match the run checkpoint")
    if result.decision is ImplementationOperationalDecision.READY_FOR_DRAFT_PR:
        state = FeatureOrchestrationState.CI_PASSED
    elif result.decision is ImplementationOperationalDecision.NEEDS_BASE_REFRESH:
        state = FeatureOrchestrationState.NEEDS_BASE_REFRESH
    else:
        state = FeatureOrchestrationState.BLOCKED
    return run.model_copy(
        update={
            "operational_result_sha256": orchestration_artifact_sha256(result),
            "work_branch": mutation.work_branch,
            "commit_sha": mutation.commit_sha,
            "ci_run_id": result.ci_validation.run_id,
            "state": state,
        }
    )


def record_draft_pr_result(
    run: FeatureOrchestrationRun,
    result: ImplementationDraftPrResult,
) -> FeatureOrchestrationRun:
    """Record the existing Draft PR gate result without creating or modifying a PR."""
    run = _validated_run(run)
    _require_state(run, FeatureOrchestrationState.CI_PASSED)
    result = ImplementationDraftPrResult.model_validate(result.model_dump(mode="python"))
    if (
        result.repository != run.repository
        or result.objective != run.objective
        or result.base_branch != run.base_branch
        or result.base_sha != run.base_sha
        or result.work_branch != run.work_branch
        or result.commit_sha != run.commit_sha
    ):
        raise FeatureOrchestrationError("Draft PR result does not match the run checkpoint")
    state = (
        FeatureOrchestrationState.DRAFT_PR_CREATED
        if result.decision is ImplementationDraftPrDecision.DRAFT_PR_CREATED
        else FeatureOrchestrationState.NEEDS_BASE_REFRESH
    )
    return run.model_copy(
        update={
            "draft_pr_result_sha256": orchestration_artifact_sha256(result),
            "pr_number": result.pr_number,
            "pr_url": result.pr_url,
            "head_branch": result.work_branch,
            "head_sha": result.commit_sha,
            "state": state,
        }
    )


def record_ready_for_review_result(
    run: FeatureOrchestrationRun,
    result: ReadyForReviewResult,
) -> FeatureOrchestrationRun:
    """Record the existing review/Ready gate and stop at the Human Merge Gate."""
    run = _validated_run(run)
    _require_state(run, FeatureOrchestrationState.DRAFT_PR_CREATED)
    result = ReadyForReviewResult.model_validate(result.model_dump(mode="python"))
    if (
        result.repository != run.repository
        or result.pr_number != run.pr_number
        or result.pr_url != run.pr_url
        or result.base_branch != run.base_branch
        or result.base_sha != run.base_sha
        or result.head_branch != run.head_branch
        or result.head_sha != run.head_sha
    ):
        raise FeatureOrchestrationError("Ready-for-Review result does not match the run checkpoint")
    _validate_nested_review_binding(run, result)

    if result.decision is ReadyForReviewDecision.NEEDS_BASE_REFRESH:
        state = FeatureOrchestrationState.NEEDS_BASE_REFRESH
    elif result.decision is ReadyForReviewDecision.REVIEW_NOT_APPROVED:
        state = FeatureOrchestrationState.BLOCKED
    else:
        if not result.ready_for_review or not result.base_fresh_after_transition:
            raise FeatureOrchestrationError("READY_FOR_REVIEW result lacks fresh Ready evidence")
        if result.base_head_after_transition != run.base_sha:
            raise FeatureOrchestrationError("READY_FOR_REVIEW result base evidence does not match the run")
        if result.review_report.base_branch_head_sha != run.base_sha:
            raise FeatureOrchestrationError("APPROVE review base evidence does not match the run")
        if result.review_report.decision is not ReviewDecision.APPROVE:
            raise FeatureOrchestrationError("Human Merge Gate requires an APPROVE review report")
        state = FeatureOrchestrationState.HUMAN_MERGE_GATE

    return run.model_copy(
        update={
            "review_report_sha256": orchestration_artifact_sha256(result.review_report),
            "ready_result_sha256": orchestration_artifact_sha256(result),
            "state": state,
        }
    )


def _validate_nested_review_binding(
    run: FeatureOrchestrationRun,
    result: ReadyForReviewResult,
) -> None:
    report = result.review_report
    if (
        report.repository != run.repository
        or report.pr_number != run.pr_number
        or report.base_branch != run.base_branch
        or report.base_sha != run.base_sha
        or report.head_branch != run.head_branch
        or report.head_sha != run.head_sha
        or report.objective != run.objective
    ):
        raise FeatureOrchestrationError(
            "Ready-for-Review nested review report does not match the run checkpoint"
        )


def _validated_run(run: FeatureOrchestrationRun) -> FeatureOrchestrationRun:
    return FeatureOrchestrationRun.model_validate(run.model_dump(mode="python"))


def _require_state(
    run: FeatureOrchestrationRun,
    expected: FeatureOrchestrationState,
) -> None:
    if run.state is not expected:
        raise FeatureOrchestrationError(
            f"orchestration state must be {expected.value}, observed {run.state.value}"
        )