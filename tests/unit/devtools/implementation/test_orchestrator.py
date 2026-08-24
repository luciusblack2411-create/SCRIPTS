from __future__ import annotations

import hashlib

import pytest

from cisco_assessment.devtools.implementation.ci_validation import (
    ImplementationCiJobResult,
    ImplementationCiStatus,
    ImplementationCiValidationResult,
    ImplementationOperationalDecision,
)
from cisco_assessment.devtools.implementation.draft_pr import (
    ImplementationDraftPrDecision,
    ImplementationDraftPrResult,
)
from cisco_assessment.devtools.implementation.enums import (
    ImplementationAuthorization,
    ImplementationFileChangeKind,
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
    FeatureOrchestrationError,
    FeatureOrchestrationState,
    begin_feature_orchestration,
    orchestration_artifact_sha256,
    record_contract_approval,
    record_contract_proposal,
    record_draft_pr_result,
    record_operational_result,
    record_ready_for_review_result,
    record_workspace_validation,
)
from cisco_assessment.devtools.implementation.workspace import (
    ImplementationProposedFileChange,
    ImplementationWorkspace,
)
from cisco_assessment.devtools.pr_review.enums import (
    ComponentId,
    ReviewDecision,
)
from cisco_assessment.devtools.pr_review.models import ReviewReport
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewDecision,
    ReadyForReviewResult,
)

REPOSITORY = "owner/repo"
BASE_SHA = "base-123"
OBJECTIVE = "Implement an approved DevTools orchestration change."
PATH = "tests/unit/devtools/test_feature.py"
WORK_BRANCH = "agent/implementation/run-0001"
COMMIT_SHA = "commit-123"


def _feature_request() -> FeatureRequest:
    return FeatureRequest(
        repository=REPOSITORY,
        request_text="Please implement the approved feature.",
        requested_max_authorization=ImplementationAuthorization.WORK_BRANCH,
    )


def _proposal(request: FeatureRequest):
    return build_feature_contract_proposal(
        request,
        FeatureContractProposalDraft(
            objective=OBJECTIVE,
            authorized_components=(ComponentId.TESTING_FIXTURES,),
            prohibited_components=(ComponentId.COLLECTOR, ComponentId.UNKNOWN),
            invariants=("Cisco execution remains disabled.",),
            acceptance_criteria=("Tests pass.",),
            maximum_authorization=ImplementationAuthorization.WORK_BRANCH,
        ),
        base_sha=BASE_SHA,
    )


def _approved_front():
    feature = _feature_request()
    proposal = _proposal(feature)
    run = begin_feature_orchestration(feature, run_id="run-0001", base_sha=BASE_SHA)
    run = record_contract_proposal(run, proposal)
    approval = FeatureContractApproval(
        decision="CONTRACT_APPROVED",
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        proposal_sha256=feature_contract_proposal_sha256(proposal),
        authorization=ImplementationAuthorization.WORK_BRANCH,
        authorized_by="human-operator",
        rationale="Approve the exact bounded proposal.",
    )
    return record_contract_approval(run, proposal, approval)


def _workspace() -> ImplementationWorkspace:
    content = "def test_feature():\n    assert True\n"
    encoded = content.encode("utf-8")
    return ImplementationWorkspace(
        repository=REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        objective=OBJECTIVE,
        authorization=ImplementationAuthorization.WORK_BRANCH,
        plan_step_ids=("step:0001",),
        inspected_paths=(PATH,),
        acceptance_criteria=("Tests pass.",),
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
                rationale="Add the approved regression coverage.",
                acceptance_criteria=("Tests pass.",),
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
            ImplementationCiJobResult(
                job_id=2001,
                name="quality (3.11)",
                conclusion="success",
            ),
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


def _draft_result(*, base_after: str = BASE_SHA) -> ImplementationDraftPrResult:
    fresh = base_after == BASE_SHA
    return ImplementationDraftPrResult(
        repository=REPOSITORY,
        objective=OBJECTIVE,
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        pr_number=70,
        pr_url="https://github.com/owner/repo/pull/70",
        title="feat(devtools): test orchestrator",
        base_head_after_create=base_after,
        base_fresh_after_create=fresh,
        decision=(
            ImplementationDraftPrDecision.DRAFT_PR_CREATED
            if fresh
            else ImplementationDraftPrDecision.NEEDS_BASE_REFRESH
        ),
    )


def _review_report(*, decision: ReviewDecision = ReviewDecision.APPROVE) -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=70,
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
        contracts_changed=(),
        contracts_verified_stable=(),
        residual_risks=(),
        decision=decision,
        decision_reason="Deterministic test review result.",
    )


def _ready_result(*, approved: bool = True) -> ReadyForReviewResult:
    review = _review_report(
        decision=ReviewDecision.APPROVE if approved else ReviewDecision.REQUEST_CHANGES
    )
    return ReadyForReviewResult(
        repository=REPOSITORY,
        pr_number=70,
        pr_url="https://github.com/owner/repo/pull/70",
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


def _run_through_ci():
    run, request = _approved_front()
    workspace = _workspace()
    run = record_workspace_validation(run, request, workspace)
    operational = _operational_result(workspace)
    return record_operational_result(run, operational), workspace


def test_feature_orchestrator_reaches_human_merge_gate_without_merging() -> None:
    run, _ = _run_through_ci()
    assert run.state is FeatureOrchestrationState.CI_PASSED
    assert run.work_branch == WORK_BRANCH
    assert run.commit_sha == COMMIT_SHA
    assert run.ci_run_id == 1001

    run = record_draft_pr_result(run, _draft_result())
    assert run.state is FeatureOrchestrationState.DRAFT_PR_CREATED
    assert run.pr_number == 70

    run = record_ready_for_review_result(run, _ready_result())
    assert run.state is FeatureOrchestrationState.HUMAN_MERGE_GATE
    assert run.review_report_sha256 is not None
    assert run.ready_result_sha256 is not None
    assert run.merge_performed is False
    assert run.human_merge_gate_required is True
    assert run.cisco_execution_allowed is False


def test_contract_proposal_and_approval_are_exactly_hash_bound() -> None:
    feature = _feature_request()
    proposal = _proposal(feature)
    run = begin_feature_orchestration(feature, run_id="run-0001", base_sha=BASE_SHA)
    run = record_contract_proposal(run, proposal)

    changed = proposal.model_copy(update={"objective": "Different objective"})
    approval = FeatureContractApproval(
        decision="CONTRACT_APPROVED",
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        proposal_sha256=feature_contract_proposal_sha256(changed),
        authorization=ImplementationAuthorization.WORK_BRANCH,
        authorized_by="human-operator",
        rationale="Attempt to approve a different proposal.",
    )
    with pytest.raises(FeatureOrchestrationError, match="does not match the run checkpoint"):
        record_contract_approval(run, changed, approval)


def test_operational_result_rejects_workspace_hash_mismatch() -> None:
    run, request = _approved_front()
    workspace = _workspace()
    run = record_workspace_validation(run, request, workspace)
    result = _operational_result(workspace)
    tampered_mutation = result.mutation.model_copy(
        update={"workspace_sha256": "0" * 64}
    )
    tampered = result.model_copy(update={"mutation": tampered_mutation})

    with pytest.raises(FeatureOrchestrationError, match="does not match the run checkpoint"):
        record_operational_result(run, tampered)


def test_draft_pr_base_drift_moves_run_to_needs_base_refresh() -> None:
    run, _ = _run_through_ci()
    run = record_draft_pr_result(run, _draft_result(base_after="new-base"))

    assert run.state is FeatureOrchestrationState.NEEDS_BASE_REFRESH
    assert run.pr_number == 70
    assert run.merge_performed is False
    assert run.cisco_execution_allowed is False


def test_review_rejection_blocks_before_human_merge_gate() -> None:
    run, _ = _run_through_ci()
    run = record_draft_pr_result(run, _draft_result())
    run = record_ready_for_review_result(run, _ready_result(approved=False))

    assert run.state is FeatureOrchestrationState.BLOCKED
    assert run.ready_result_sha256 is not None
    assert run.merge_performed is False
    assert run.cisco_execution_allowed is False


def test_transitions_fail_closed_when_called_out_of_order() -> None:
    feature = _feature_request()
    run = begin_feature_orchestration(feature, run_id="run-0001", base_sha=BASE_SHA)

    with pytest.raises(FeatureOrchestrationError, match="FEATURE_RECEIVED"):
        record_draft_pr_result(run, _draft_result())
