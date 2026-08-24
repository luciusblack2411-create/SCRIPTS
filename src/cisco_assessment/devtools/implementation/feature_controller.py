"""Executable feature-delivery controller composed from existing protected gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..pr_review.models import ReviewRequest
from ..ready_for_review import (
    ReadyForReviewAuthorization,
    ReadyForReviewOperation,
    ReadyForReviewResult,
)
from ..ready_for_review_control_plane import ReadyForReviewControlPlaneResult
from .ci_validation import ImplementationCiBackend
from .context import load_implementation_context
from .draft_pr import ImplementationDraftPrRequest, ImplementationDraftPrResult
from .draft_pr_control_plane import (
    ImplementationDraftPrControlPlaneOperation,
    ImplementationDraftPrControlPlaneResult,
)
from .enums import ImplementationAuthorization
from .feature_intake import (
    FeatureContractApproval,
    FeatureContractProposal,
    feature_contract_proposal_sha256,
)
from .models import FrozenImplementationModel
from .mutation import ImplementationMutationBackend
from .operational import (
    ImplementationOperation,
    ImplementationOperationalResult,
    execute_implementation_operation,
)
from .orchestrator import (
    FeatureOrchestrationRun,
    FeatureOrchestrationState,
    begin_feature_orchestration,
    record_contract_approval,
    record_contract_proposal,
    record_draft_pr_result,
    record_operational_result,
    record_ready_for_review_result,
    record_workspace_validation,
)
from .planning import build_implementation_plan
from .run_journal import (
    FeatureRunJournal,
    FeatureRunResumeDecision,
    JsonFeatureRunJournalStore,
    append_feature_run_checkpoint,
    create_feature_run_journal,
    evaluate_feature_run_resume,
)
from .source_inspection import ImplementationSourceReadBackend, inspect_implementation_sources
from .synthesis import CodexSynthesisBackend, run_codex_synthesis_adapter
from .workspace import ImplementationWorkspace

CONTROLLER_ID: Literal["FEATURE_EXECUTION_CONTROLLER_V1"] = "FEATURE_EXECUTION_CONTROLLER_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class FeatureExecutionControllerError(RuntimeError):
    """Raised when one protected feature-delivery run cannot proceed safely."""


class FeatureExecutionDecision(StrEnum):
    """Terminal decisions produced before the separate Human Merge control plane."""

    HUMAN_MERGE_GATE = "HUMAN_MERGE_GATE"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"
    BLOCKED = "BLOCKED"


class DraftPrExecutor(Protocol):
    """Dedicated Draft PR control-plane execution seam."""

    def __call__(
        self, operation: ImplementationDraftPrControlPlaneOperation
    ) -> ImplementationDraftPrControlPlaneResult:
        ...


class ReadyForReviewExecutor(Protocol):
    """Dedicated Ready-for-Review control-plane execution seam."""

    def __call__(self, operation: ReadyForReviewOperation) -> ReadyForReviewControlPlaneResult:
        ...


@dataclass(frozen=True)
class FeatureExecutionDependencies:
    """External engines and protected mutation seams used by one controller run."""

    source_backend: ImplementationSourceReadBackend
    codex_backend: CodexSynthesisBackend
    mutation_backend: ImplementationMutationBackend
    ci_backend: ImplementationCiBackend
    draft_pr_executor: DraftPrExecutor
    ready_for_review_executor: ReadyForReviewExecutor
    journal_store: JsonFeatureRunJournalStore


class FeatureDraftPrAuthorization(FrozenImplementationModel):
    """Separate explicit human authority for the later Draft PR control plane."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    controller_id: Literal["FEATURE_EXECUTION_CONTROLLER_V1"] = CONTROLLER_ID
    decision: Literal["DRAFT_PR_APPROVED"]
    repository: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization: ImplementationAuthorization
    authorized_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_authority(self) -> FeatureDraftPrAuthorization:
        if self.authorization is not ImplementationAuthorization.DRAFT_PR:
            raise ValueError("Draft PR authorization must be DRAFT_PR exactly")
        return self


class FeatureExecutionOperation(FrozenImplementationModel):
    """Explicit authority and deterministic execution inputs for one feature run."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    controller_id: Literal["FEATURE_EXECUTION_CONTROLLER_V1"] = CONTROLLER_ID
    proposal: FeatureContractProposal
    approval: FeatureContractApproval
    draft_pr_authorization: FeatureDraftPrAuthorization
    run_id: str = Field(min_length=1)
    selected_source_paths: tuple[str, ...] = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    commit_message: str = Field(min_length=1)
    draft_title: str = Field(min_length=1)
    draft_body: str = ""
    ready_for_review_authorization: ReadyForReviewAuthorization
    timeout_seconds: float = Field(default=900.0, gt=0)
    poll_interval_seconds: float = Field(default=5.0, gt=0)
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_operation_contract(self) -> FeatureExecutionOperation:
        if self.approval.authorization is not ImplementationAuthorization.WORK_BRANCH:
            raise ValueError("implementation execution requires WORK_BRANCH contract approval exactly")
        if self.proposal.maximum_authorization is not ImplementationAuthorization.DRAFT_PR:
            raise ValueError("feature proposal must permit DRAFT_PR as its maximum authorization")
        proposal_sha = feature_contract_proposal_sha256(self.proposal)
        draft_authority = self.draft_pr_authorization
        if (
            draft_authority.repository != self.proposal.request.repository
            or draft_authority.base_sha != self.proposal.base_sha
            or draft_authority.proposal_sha256 != proposal_sha
        ):
            raise ValueError("Draft PR authorization must bind to the exact proposal and base")
        if not self.work_branch.startswith("agent/implementation/"):
            raise ValueError("work_branch must use the agent/implementation/ namespace")
        if not self.commit_message.strip() or not self.draft_title.strip():
            raise ValueError("commit_message and draft_title must not be blank")
        if len(set(self.selected_source_paths)) != len(self.selected_source_paths):
            raise ValueError("selected_source_paths must be unique")
        if self.ready_for_review_authorization is not ReadyForReviewAuthorization.READY_FOR_REVIEW:
            raise ValueError("READY_FOR_REVIEW authorization is required for full controller execution")
        return self


class FeatureExecutionResult(FrozenImplementationModel):
    """Canonical terminal controller evidence; merge is always outside this contract."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    controller_id: Literal["FEATURE_EXECUTION_CONTROLLER_V1"] = CONTROLLER_ID
    repository: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    decision: FeatureExecutionDecision
    run: FeatureOrchestrationRun
    journal: FeatureRunJournal
    workspace: ImplementationWorkspace | None = None
    operational_result: ImplementationOperationalResult | None = None
    draft_pr_result: ImplementationDraftPrResult | None = None
    ready_for_review_result: ReadyForReviewResult | None = None
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_result_contract(self) -> FeatureExecutionResult:
        if self.repository != self.run.repository or self.run_id != self.run.run_id:
            raise ValueError("controller result identity must match the orchestration run")
        if self.journal.run_id != self.run_id or self.journal.head_checkpoint != self.run:
            raise ValueError("controller result journal must end at the returned run")
        expected = _decision_for_state(self.run.state)
        if expected is not None and self.decision is not expected:
            raise ValueError("controller decision must match terminal orchestration state")
        if self.decision is FeatureExecutionDecision.HUMAN_MERGE_GATE:
            if self.ready_for_review_result is None:
                raise ValueError("HUMAN_MERGE_GATE requires Ready-for-Review evidence")
            if self.run.state is not FeatureOrchestrationState.HUMAN_MERGE_GATE:
                raise ValueError("HUMAN_MERGE_GATE decision requires matching orchestration state")
        return self


def execute_feature_delivery_controller(
    operation: FeatureExecutionOperation,
    dependencies: FeatureExecutionDependencies,
) -> FeatureExecutionResult:
    """Execute approved feature delivery through Ready and stop at Human Merge Gate."""
    operation = FeatureExecutionOperation.model_validate(operation.model_dump(mode="python"))
    proposal = FeatureContractProposal.model_validate(operation.proposal.model_dump(mode="python"))
    approval = FeatureContractApproval.model_validate(operation.approval.model_dump(mode="python"))

    run = begin_feature_orchestration(
        proposal.request,
        run_id=operation.run_id,
        base_sha=proposal.base_sha,
    )
    journal = create_feature_run_journal(run)
    dependencies.journal_store.create(journal)

    run = record_contract_proposal(run, proposal)
    journal = _append_and_persist(dependencies.journal_store, journal, run)

    run, request = record_contract_approval(run, proposal, approval)
    journal = _append_and_persist(dependencies.journal_store, journal, run)
    if request.authorization is not ImplementationAuthorization.WORK_BRANCH:
        raise FeatureExecutionControllerError("approved ImplementationRequest lost WORK_BRANCH authority")

    resume = evaluate_feature_run_resume(journal, dependencies.source_backend)
    if resume.decision is FeatureRunResumeDecision.NEEDS_BASE_REFRESH:
        return _result(
            run=run,
            journal=journal,
            decision=FeatureExecutionDecision.NEEDS_BASE_REFRESH,
        )

    context = load_implementation_context(request, dependencies.source_backend)
    if context.base_sha != run.base_sha:
        return _result(
            run=run,
            journal=journal,
            decision=FeatureExecutionDecision.NEEDS_BASE_REFRESH,
        )
    plan = build_implementation_plan(request, context)
    inspection = inspect_implementation_sources(
        context,
        dependencies.source_backend,
        operation.selected_source_paths,
    )
    workspace = run_codex_synthesis_adapter(
        request,
        context,
        plan,
        inspection,
        dependencies.codex_backend,
    )

    run = record_workspace_validation(run, request, workspace)
    journal = _append_and_persist(dependencies.journal_store, journal, run)

    operational_result = execute_implementation_operation(
        ImplementationOperation(
            request=request,
            workspace=workspace,
            work_branch=operation.work_branch,
            commit_message=operation.commit_message,
        ),
        mutation_backend=dependencies.mutation_backend,
        ci_backend=dependencies.ci_backend,
        timeout_seconds=operation.timeout_seconds,
        poll_interval_seconds=operation.poll_interval_seconds,
    )
    run = record_operational_result(run, operational_result)
    journal = _append_and_persist(dependencies.journal_store, journal, run)
    terminal = _decision_for_state(run.state)
    if terminal is not None:
        return _result(
            run=run,
            journal=journal,
            decision=terminal,
            workspace=workspace,
            operational_result=operational_result,
        )

    draft_request = ImplementationDraftPrRequest(
        repository=request.repository,
        objective=request.objective,
        base_branch=operational_result.mutation.base_branch,
        base_sha=operational_result.mutation.base_sha,
        work_branch=operational_result.mutation.work_branch,
        commit_sha=operational_result.mutation.commit_sha,
        title=operation.draft_title,
        body=operation.draft_body,
        authorization=operation.draft_pr_authorization.authorization,
    )
    draft_control = dependencies.draft_pr_executor(
        ImplementationDraftPrControlPlaneOperation(
            operational_result=operational_result,
            request=draft_request,
        )
    )
    draft_result = draft_control.draft_pr
    run = record_draft_pr_result(run, draft_result)
    journal = _append_and_persist(dependencies.journal_store, journal, run)
    terminal = _decision_for_state(run.state)
    if terminal is not None:
        return _result(
            run=run,
            journal=journal,
            decision=terminal,
            workspace=workspace,
            operational_result=operational_result,
            draft_pr_result=draft_result,
        )

    review_request = ReviewRequest(
        repository=request.repository,
        pr_number=draft_result.pr_number,
        expected_base_branch=request.expected_base_branch,
        objective=request.objective,
        expected_components=proposal.authorized_components,
        prohibited_components=proposal.prohibited_components,
        expected_contracts=_stable_unique(
            (*proposal.contracts_to_preserve, *proposal.contracts_to_change)
        ),
        invariants=proposal.invariants,
        related_issue_ids=proposal.request.related_issue_ids,
        require_ci_success=True,
    )
    ready_control = dependencies.ready_for_review_executor(
        ReadyForReviewOperation(
            review_request=review_request,
            authorization=operation.ready_for_review_authorization,
        )
    )
    ready_result = ready_control.ready_for_review
    run = record_ready_for_review_result(run, ready_result)
    journal = _append_and_persist(dependencies.journal_store, journal, run)
    terminal = _decision_for_state(run.state)
    if terminal is None:
        raise FeatureExecutionControllerError(
            f"controller reached unexpected non-terminal state {run.state.value}"
        )
    return _result(
        run=run,
        journal=journal,
        decision=terminal,
        workspace=workspace,
        operational_result=operational_result,
        draft_pr_result=draft_result,
        ready_for_review_result=ready_result,
    )


def _append_and_persist(
    store: JsonFeatureRunJournalStore,
    journal: FeatureRunJournal,
    run: FeatureOrchestrationRun,
) -> FeatureRunJournal:
    previous_head = journal.head_entry_sha256
    advanced = append_feature_run_checkpoint(journal, run)
    store.append(advanced, expected_previous_head_sha256=previous_head)
    return advanced


def _decision_for_state(state: FeatureOrchestrationState) -> FeatureExecutionDecision | None:
    if state is FeatureOrchestrationState.HUMAN_MERGE_GATE:
        return FeatureExecutionDecision.HUMAN_MERGE_GATE
    if state is FeatureOrchestrationState.NEEDS_BASE_REFRESH:
        return FeatureExecutionDecision.NEEDS_BASE_REFRESH
    if state is FeatureOrchestrationState.BLOCKED:
        return FeatureExecutionDecision.BLOCKED
    return None


def _stable_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _result(
    *,
    run: FeatureOrchestrationRun,
    journal: FeatureRunJournal,
    decision: FeatureExecutionDecision,
    workspace: ImplementationWorkspace | None = None,
    operational_result: ImplementationOperationalResult | None = None,
    draft_pr_result: ImplementationDraftPrResult | None = None,
    ready_for_review_result: ReadyForReviewResult | None = None,
) -> FeatureExecutionResult:
    return FeatureExecutionResult(
        repository=run.repository,
        run_id=run.run_id,
        decision=decision,
        run=run,
        journal=journal,
        workspace=workspace,
        operational_result=operational_result,
        draft_pr_result=draft_pr_result,
        ready_for_review_result=ready_for_review_result,
    )
