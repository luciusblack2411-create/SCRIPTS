from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation import feature_controller
from cisco_assessment.devtools.implementation.ci_validation import (
    ImplementationCiJobResult,
    ImplementationCiStatus,
    ImplementationCiValidationResult,
    ImplementationOperationalDecision,
)
from cisco_assessment.devtools.implementation.context import ImplementationContext
from cisco_assessment.devtools.implementation.draft_pr import (
    ImplementationDraftPrDecision,
    ImplementationDraftPrResult,
)
from cisco_assessment.devtools.implementation.draft_pr_control_plane import (
    ImplementationDraftPrControlPlaneResult,
)
from cisco_assessment.devtools.implementation.enums import (
    ImplementationAuthorization,
    ImplementationFileChangeKind,
)
from cisco_assessment.devtools.implementation.feature_controller import (
    FeatureDraftPrAuthorization,
    FeatureExecutionDecision,
    FeatureExecutionDependencies,
    FeatureExecutionOperation,
    execute_feature_delivery_controller,
)
from cisco_assessment.devtools.implementation.feature_intake import (
    FeatureContractApproval,
    FeatureContractProposalDraft,
    FeatureRequest,
    build_feature_contract_proposal,
    feature_contract_proposal_sha256,
)
from cisco_assessment.devtools.implementation.mutation import (
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
)
from cisco_assessment.devtools.implementation.operational import ImplementationOperationalResult
from cisco_assessment.devtools.implementation.orchestrator import (
    FeatureOrchestrationState,
    orchestration_artifact_sha256,
)
from cisco_assessment.devtools.implementation.run_journal import JsonFeatureRunJournalStore
from cisco_assessment.devtools.implementation.workspace import (
    ImplementationProposedFileChange,
    ImplementationWorkspace,
)
from cisco_assessment.devtools.pr_review.enums import ComponentId, ReviewDecision
from cisco_assessment.devtools.pr_review.models import ReviewReport
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewAuthorization,
    ReadyForReviewDecision,
    ReadyForReviewResult,
)
from cisco_assessment.devtools.ready_for_review_control_plane import (
    ReadyForReviewControlPlaneResult,
)

REPOSITORY = "owner/repo"
BASE_SHA = "base-123"
OBJECTIVE = "Implement the approved executable feature-controller slice."
PATH = "tests/unit/devtools/implementation/test_generated_controller.py"
WORK_BRANCH = "agent/implementation/controller-run-0001"
COMMIT_SHA = "commit-123"
PR_NUMBER = 72


def _feature_request() -> FeatureRequest:
    return FeatureRequest(
        repository=REPOSITORY,
        request_text="Implement the approved controller feature.",
        requested_max_authorization=ImplementationAuthorization.DRAFT_PR,
    )


def _proposal():
    return build_feature_contract_proposal(
        _feature_request(),
        FeatureContractProposalDraft(
            objective=OBJECTIVE,
            authorized_components=(ComponentId.TESTING_FIXTURES, ComponentId.CI_TOOLING),
            prohibited_components=(ComponentId.COLLECTOR, ComponentId.UNKNOWN),
            contracts_to_preserve=("FEATURE_ORCHESTRATOR_V1",),
            contracts_to_change=("FEATURE_EXECUTION_CONTROLLER_V1",),
            invariants=("Cisco execution remains disabled.", "Human merge remains mandatory."),
            acceptance_criteria=("Controller stops at Human Merge Gate.",),
            maximum_authorization=ImplementationAuthorization.DRAFT_PR,
        ),
        base_sha=BASE_SHA,
    )


def _approval(
    *,
    authorization: ImplementationAuthorization = ImplementationAuthorization.WORK_BRANCH,
) -> FeatureContractApproval:
    proposal = _proposal()
    return FeatureContractApproval(
        decision="CONTRACT_APPROVED",
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        proposal_sha256=feature_contract_proposal_sha256(proposal),
        authorization=authorization,
        authorized_by="human-operator",
        rationale="Approve the exact work-branch implementation boundary.",
    )


def _draft_authorization(
    *,
    proposal_sha256: str | None = None,
) -> FeatureDraftPrAuthorization:
    proposal = _proposal()
    return FeatureDraftPrAuthorization(
        decision="DRAFT_PR_APPROVED",
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        proposal_sha256=proposal_sha256 or feature_contract_proposal_sha256(proposal),
        authorization=ImplementationAuthorization.DRAFT_PR,
        authorized_by="human-operator",
        rationale="Permit the dedicated Draft PR gate after successful work-branch CI.",
    )


def _operation(
    *,
    approval: FeatureContractApproval | None = None,
    draft_authorization: FeatureDraftPrAuthorization | None = None,
) -> FeatureExecutionOperation:
    return FeatureExecutionOperation(
        proposal=_proposal(),
        approval=approval or _approval(),
        draft_pr_authorization=draft_authorization or _draft_authorization(),
        run_id="controller-run-0001",
        selected_source_paths=(PATH,),
        work_branch=WORK_BRANCH,
        commit_message="feat(devtools): execute approved controller change",
        draft_title="feat(devtools): controller generated change",
        draft_body="Generated only from approved controller inputs.",
        ready_for_review_authorization=ReadyForReviewAuthorization.READY_FOR_REVIEW,
    )


def _context() -> ImplementationContext:
    return ImplementationContext(
        repository=REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        files=(),
        observed_components=(),
    )


def _workspace() -> ImplementationWorkspace:
    content = "def test_controller_generated():\n    assert True\n"
    encoded = content.encode("utf-8")
    return ImplementationWorkspace(
        repository=REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        objective=OBJECTIVE,
        authorization=ImplementationAuthorization.WORK_BRANCH,
        plan_step_ids=("impl-step:0001",),
        inspected_paths=(PATH,),
        contracts_to_preserve=("FEATURE_ORCHESTRATOR_V1",),
        contracts_to_change=("FEATURE_EXECUTION_CONTROLLER_V1",),
        acceptance_criteria=("Controller stops at Human Merge Gate.",),
        changes=(
            ImplementationProposedFileChange(
                ordinal=1,
                change_id="impl-change:0001",
                kind=ImplementationFileChangeKind.CREATE,
                path=PATH,
                component=ComponentId.TESTING_FIXTURES,
                proposed_content_sha256=hashlib.sha256(encoded).hexdigest(),
                proposed_byte_size=len(encoded),
                proposed_content=content,
                rationale="Exercise controller composition.",
                acceptance_criteria=("Controller stops at Human Merge Gate.",),
            ),
        ),
    )


def _operational_result(workspace: ImplementationWorkspace) -> ImplementationOperationalResult:
    proposed = workspace.changes[0]
    mutation = ImplementationMutationResult(
        repository=REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        workspace_sha256=orchestration_artifact_sha256(workspace),
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        tree_sha="tree-123",
        changes=(
            ImplementationMutationChangeResult(
                ordinal=1,
                change_id="impl-change:0001",
                kind=proposed.kind,
                path=proposed.path,
                published_blob_sha="blob-123",
                proposed_content_sha256=proposed.proposed_content_sha256,
            ),
        ),
        base_head_after_publish=BASE_SHA,
        base_fresh_after_publish=True,
    )
    ci = ImplementationCiValidationResult(
        repository=REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        run_id=1001,
        ci_status=ImplementationCiStatus.PASSED,
        workflow_conclusion="success",
        jobs=(
            ImplementationCiJobResult(job_id=2001, name="quality (3.11)", conclusion="success"),
        ),
        base_head_after_ci=BASE_SHA,
        base_fresh_after_ci=True,
        decision=ImplementationOperationalDecision.READY_FOR_DRAFT_PR,
    )
    return ImplementationOperationalResult(
        repository=REPOSITORY,
        objective=OBJECTIVE,
        mutation=mutation,
        ci_validation=ci,
        decision=ImplementationOperationalDecision.READY_FOR_DRAFT_PR,
    )


def _draft_result() -> ImplementationDraftPrResult:
    return ImplementationDraftPrResult(
        repository=REPOSITORY,
        objective=OBJECTIVE,
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        pr_number=PR_NUMBER,
        pr_url=f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}",
        title="feat(devtools): controller generated change",
        base_head_after_create=BASE_SHA,
        base_fresh_after_create=True,
        decision=ImplementationDraftPrDecision.DRAFT_PR_CREATED,
    )


def _ready_result(*, approved: bool = True) -> ReadyForReviewResult:
    review = ReviewReport(
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        base_branch="main",
        base_sha=BASE_SHA,
        base_branch_head_sha=BASE_SHA,
        head_branch=WORK_BRANCH,
        head_sha=COMMIT_SHA,
        mergeable=True,
        objective=OBJECTIVE,
        detected_components=(ComponentId.TESTING_FIXTURES,),
        checks=(),
        findings=(),
        contracts_changed=("FEATURE_EXECUTION_CONTROLLER_V1",),
        contracts_verified_stable=("FEATURE_ORCHESTRATOR_V1",),
        residual_risks=(),
        decision=ReviewDecision.APPROVE if approved else ReviewDecision.REQUEST_CHANGES,
        decision_reason="Deterministic controller review result.",
    )
    return ReadyForReviewResult(
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        pr_url=f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}",
        base_branch="main",
        base_sha=BASE_SHA,
        head_branch=WORK_BRANCH,
        head_sha=COMMIT_SHA,
        review_report=review,
        base_head_after_transition=BASE_SHA,
        base_fresh_after_transition=True,
        decision=(
            ReadyForReviewDecision.READY_FOR_REVIEW
            if approved
            else ReadyForReviewDecision.REVIEW_NOT_APPROVED
        ),
        ready_for_review=approved,
    )


class FakeSourceBackend:
    def __init__(self, base_sha: str = BASE_SHA) -> None:
        self.base_sha = base_sha

    def get_branch(self, repository: str, branch: str) -> dict[str, object]:
        return {"name": branch, "commit": {"sha": self.base_sha}}

    def list_tree(self, repository: str, commit_sha: str) -> tuple[dict[str, object], ...]:
        return ()

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        return b""


class DummyCodex:
    def synthesize(self, prompt: str) -> str:
        raise AssertionError("Codex backend should be patched in controller unit tests")


class DummyMutation:
    pass


class DummyCi:
    pass


def _dependencies(
    tmp_path: Path,
    *,
    base_sha: str = BASE_SHA,
    approved_review: bool = True,
    observed: dict[str, Any] | None = None,
) -> FeatureExecutionDependencies:
    calls = observed if observed is not None else {}

    def draft_executor(operation: Any) -> ImplementationDraftPrControlPlaneResult:
        calls["draft_operation"] = operation
        return ImplementationDraftPrControlPlaneResult(draft_pr=_draft_result())

    def ready_executor(operation: Any) -> ReadyForReviewControlPlaneResult:
        calls["ready_operation"] = operation
        return ReadyForReviewControlPlaneResult(
            ready_for_review=_ready_result(approved=approved_review)
        )

    return FeatureExecutionDependencies(
        source_backend=FakeSourceBackend(base_sha),
        codex_backend=DummyCodex(),
        mutation_backend=DummyMutation(),  # type: ignore[arg-type]
        ci_backend=DummyCi(),  # type: ignore[arg-type]
        draft_pr_executor=draft_executor,
        ready_for_review_executor=ready_executor,
        journal_store=JsonFeatureRunJournalStore(tmp_path),
    )


def _patch_middle_stages(monkeypatch: pytest.MonkeyPatch, workspace: ImplementationWorkspace) -> None:
    monkeypatch.setattr(feature_controller, "load_implementation_context", lambda *args: _context())
    monkeypatch.setattr(feature_controller, "build_implementation_plan", lambda *args: object())
    monkeypatch.setattr(feature_controller, "inspect_implementation_sources", lambda *args: object())
    monkeypatch.setattr(feature_controller, "run_codex_synthesis_adapter", lambda *args: workspace)
    monkeypatch.setattr(
        feature_controller,
        "execute_implementation_operation",
        lambda *args, **kwargs: _operational_result(workspace),
    )


def test_controller_executes_existing_gates_and_stops_at_human_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    _patch_middle_stages(monkeypatch, workspace)
    observed: dict[str, Any] = {}

    result = execute_feature_delivery_controller(
        _operation(),
        _dependencies(tmp_path, observed=observed),
    )

    assert result.decision is FeatureExecutionDecision.HUMAN_MERGE_GATE
    assert result.run.state is FeatureOrchestrationState.HUMAN_MERGE_GATE
    assert len(result.journal.entries) == 7
    assert result.journal.head_checkpoint == result.run
    assert result.workspace == workspace
    assert result.operational_result is not None
    assert result.draft_pr_result is not None
    assert result.ready_for_review_result is not None
    assert result.merge_performed is False
    assert result.human_merge_gate_required is True
    assert result.cisco_execution_allowed is False

    draft_operation = observed["draft_operation"]
    assert draft_operation.request.authorization is ImplementationAuthorization.DRAFT_PR
    ready_operation = observed["ready_operation"]
    review_request = ready_operation.review_request
    assert review_request.expected_components == (
        ComponentId.TESTING_FIXTURES,
        ComponentId.CI_TOOLING,
    )
    assert review_request.expected_contracts == (
        "FEATURE_ORCHESTRATOR_V1",
        "FEATURE_EXECUTION_CONTROLLER_V1",
    )
    assert review_request.invariants == (
        "Cisco execution remains disabled.",
        "Human merge remains mandatory.",
    )


def test_controller_detects_base_drift_before_external_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        feature_controller,
        "load_implementation_context",
        lambda *args: pytest.fail("context must not be loaded after preflight drift"),
    )

    result = execute_feature_delivery_controller(
        _operation(),
        _dependencies(tmp_path, base_sha="new-base"),
    )

    assert result.decision is FeatureExecutionDecision.NEEDS_BASE_REFRESH
    assert result.run.state is FeatureOrchestrationState.IMPLEMENTATION_READY
    assert len(result.journal.entries) == 3
    assert result.workspace is None
    assert result.merge_performed is False
    assert result.cisco_execution_allowed is False


def test_controller_records_review_rejection_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    _patch_middle_stages(monkeypatch, workspace)

    result = execute_feature_delivery_controller(
        _operation(),
        _dependencies(tmp_path, approved_review=False),
    )

    assert result.decision is FeatureExecutionDecision.BLOCKED
    assert result.run.state is FeatureOrchestrationState.BLOCKED
    assert result.ready_for_review_result is not None
    assert result.merge_performed is False
    assert result.cisco_execution_allowed is False


def test_controller_preserves_exact_work_branch_authorization_boundary() -> None:
    with pytest.raises(ValidationError, match="WORK_BRANCH contract approval"):
        _operation(approval=_approval(authorization=ImplementationAuthorization.DRAFT_PR))


def test_controller_rejects_unbound_draft_pr_authorization() -> None:
    with pytest.raises(ValidationError, match="exact proposal and base"):
        _operation(draft_authorization=_draft_authorization(proposal_sha256="0" * 64))
