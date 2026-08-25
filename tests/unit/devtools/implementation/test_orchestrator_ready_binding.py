from __future__ import annotations

import pytest

from cisco_assessment.devtools.implementation.orchestrator import (
    FeatureOrchestrationError,
    FeatureOrchestrationRun,
    FeatureOrchestrationState,
    record_ready_for_review_result,
)
from cisco_assessment.devtools.pr_review.enums import ComponentId, ReviewDecision
from cisco_assessment.devtools.pr_review.models import ReviewReport
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewDecision,
    ReadyForReviewResult,
)

REPOSITORY = "owner/repo"
BASE_BRANCH = "main"
BASE_SHA = "base-123"
HEAD_BRANCH = "agent/implementation/run-0001"
HEAD_SHA = "commit-123"
OBJECTIVE = "Implement one approved Agent-First pilot change."
PR_NUMBER = 88
PR_URL = f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}"


def _run() -> FeatureOrchestrationRun:
    return FeatureOrchestrationRun(
        run_id="run-0001",
        repository=REPOSITORY,
        base_branch=BASE_BRANCH,
        base_sha=BASE_SHA,
        request_text="Implement the bounded pilot change.",
        objective=OBJECTIVE,
        state=FeatureOrchestrationState.DRAFT_PR_CREATED,
        feature_request_sha256="0" * 64,
        pr_number=PR_NUMBER,
        pr_url=PR_URL,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
    )


def _review_report() -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        base_branch=BASE_BRANCH,
        base_sha=BASE_SHA,
        base_branch_head_sha=BASE_SHA,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
        mergeable=True,
        objective=OBJECTIVE,
        detected_components=(ComponentId.CI_TOOLING,),
        checks=(),
        findings=(),
        contracts_changed=(),
        contracts_verified_stable=(),
        residual_risks=(),
        decision=ReviewDecision.APPROVE,
        decision_reason="Exact reviewed evidence is approved.",
    )


def _ready_result(*, review_report: ReviewReport | None = None) -> ReadyForReviewResult:
    return ReadyForReviewResult(
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        pr_url=PR_URL,
        base_branch=BASE_BRANCH,
        base_sha=BASE_SHA,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
        review_report=review_report or _review_report(),
        base_head_after_transition=BASE_SHA,
        base_fresh_after_transition=True,
        decision=ReadyForReviewDecision.READY_FOR_REVIEW,
        ready_for_review=True,
    )


def test_ready_review_exact_binding_reaches_human_merge_gate() -> None:
    advanced = record_ready_for_review_result(_run(), _ready_result())

    assert advanced.state is FeatureOrchestrationState.HUMAN_MERGE_GATE
    assert advanced.review_report_sha256 is not None
    assert advanced.ready_result_sha256 is not None
    assert advanced.merge_performed is False
    assert advanced.cisco_execution_allowed is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository", "other/repo"),
        ("pr_number", 99),
        ("base_branch", "other-base"),
        ("base_sha", "other-base-sha"),
        ("head_branch", "agent/implementation/other"),
        ("head_sha", "other-head-sha"),
        ("objective", "Different objective"),
    ),
)
def test_ready_review_rejects_nested_report_not_bound_to_run(
    field: str,
    value: object,
) -> None:
    tampered_report = _review_report().model_copy(update={field: value})

    with pytest.raises(
        FeatureOrchestrationError,
        match="nested review report does not match the run checkpoint",
    ):
        record_ready_for_review_result(
            _run(),
            _ready_result(review_report=tampered_report),
        )


def test_ready_review_requires_exact_post_transition_base_sha() -> None:
    tampered = _ready_result().model_copy(
        update={"base_head_after_transition": "other-base-sha"}
    )

    with pytest.raises(FeatureOrchestrationError, match="base evidence does not match the run"):
        record_ready_for_review_result(_run(), tampered)


def test_ready_review_requires_approve_report_from_current_base() -> None:
    report = _review_report().model_copy(
        update={"base_branch_head_sha": "other-base-sha"}
    )

    with pytest.raises(FeatureOrchestrationError, match="APPROVE review base evidence"):
        record_ready_for_review_result(
            _run(),
            _ready_result(review_report=report),
        )
