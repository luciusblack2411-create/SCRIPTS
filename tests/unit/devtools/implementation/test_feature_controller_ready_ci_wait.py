from __future__ import annotations

from cisco_assessment.devtools.implementation.feature_controller import (
    _execute_ready_for_review_with_ci_wait,
    _is_transient_ready_ci_pending,
)
from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.enums import (
    ComponentId,
    ReviewCheckStatus,
    ReviewDecision,
)
from cisco_assessment.devtools.pr_review.models import ReviewCheck, ReviewReport, ReviewRequest
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewAuthorization,
    ReadyForReviewDecision,
    ReadyForReviewOperation,
    ReadyForReviewResult,
)
from cisco_assessment.devtools.ready_for_review_control_plane import (
    ReadyForReviewControlPlaneResult,
)

REPOSITORY = "owner/repo"
BASE_SHA = "base-123"
HEAD_SHA = "head-123"
HEAD_BRANCH = "agent/implementation/controller-run-0001"
PR_NUMBER = 88
OBJECTIVE = "Wait only for transient pull-request CI before Ready review."


def _check(check_id: ReviewCheckId, status: ReviewCheckStatus) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id,
        name=f"check {check_id.value}",
        category="CI" if check_id.value.startswith("CI-") else "SCOPE",
        status=status,
        applicable=True,
        summary=f"{check_id.value} is {status.value}",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _report(
    *,
    decision: ReviewDecision,
    checks: tuple[ReviewCheck, ...] = (),
) -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        base_branch="main",
        base_sha=BASE_SHA,
        base_branch_head_sha=BASE_SHA,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
        mergeable=True,
        objective=OBJECTIVE,
        detected_components=(ComponentId.TESTING_FIXTURES,),
        checks=checks,
        findings=(),
        contracts_changed=(),
        contracts_verified_stable=(),
        residual_risks=(),
        decision=decision,
        decision_reason=f"review decision {decision.value}",
    )


def _ready_result(
    *,
    report: ReviewReport,
    decision: ReadyForReviewDecision,
    ready: bool,
) -> ReadyForReviewResult:
    return ReadyForReviewResult(
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        pr_url=f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}",
        base_branch="main",
        base_sha=BASE_SHA,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
        review_report=report,
        base_head_after_transition=BASE_SHA,
        base_fresh_after_transition=True,
        decision=decision,
        ready_for_review=ready,
    )


def _operation() -> ReadyForReviewOperation:
    return ReadyForReviewOperation(
        review_request=ReviewRequest(
            repository=REPOSITORY,
            pr_number=PR_NUMBER,
            objective=OBJECTIVE,
            expected_components=(ComponentId.TESTING_FIXTURES,),
            require_ci_success=True,
        ),
        authorization=ReadyForReviewAuthorization.READY_FOR_REVIEW,
    )


def _control(result: ReadyForReviewResult) -> ReadyForReviewControlPlaneResult:
    return ReadyForReviewControlPlaneResult(ready_for_review=result)


def test_transient_current_head_ci_block_is_retryable() -> None:
    pending = _ready_result(
        report=_report(
            decision=ReviewDecision.BLOCKED,
            checks=(
                _check(ReviewCheckId.CI_001, ReviewCheckStatus.UNKNOWN),
                _check(ReviewCheckId.CI_002, ReviewCheckStatus.UNKNOWN),
                _check(ReviewCheckId.CI_003, ReviewCheckStatus.UNKNOWN),
            ),
        ),
        decision=ReadyForReviewDecision.REVIEW_NOT_APPROVED,
        ready=False,
    )

    assert _is_transient_ready_ci_pending(pending) is True


def test_ready_wait_retries_transient_ci_then_returns_approved_result() -> None:
    pending = _ready_result(
        report=_report(
            decision=ReviewDecision.BLOCKED,
            checks=(
                _check(ReviewCheckId.CI_002, ReviewCheckStatus.UNKNOWN),
                _check(ReviewCheckId.CI_003, ReviewCheckStatus.UNKNOWN),
            ),
        ),
        decision=ReadyForReviewDecision.REVIEW_NOT_APPROVED,
        ready=False,
    )
    approved = _ready_result(
        report=_report(decision=ReviewDecision.APPROVE),
        decision=ReadyForReviewDecision.READY_FOR_REVIEW,
        ready=True,
    )
    controls = iter((_control(pending), _control(approved)))
    calls: list[ReadyForReviewOperation] = []
    delays: list[float] = []
    clock_values = iter((0.0, 0.5))

    def executor(operation: ReadyForReviewOperation) -> ReadyForReviewControlPlaneResult:
        calls.append(operation)
        return next(controls)

    result = _execute_ready_for_review_with_ci_wait(
        _operation(),
        executor,
        timeout_seconds=30.0,
        poll_interval_seconds=5.0,
        sleeper=delays.append,
        clock=lambda: next(clock_values),
    )

    assert result == approved
    assert len(calls) == 2
    assert delays == [5.0]
    assert result.merge_performed is False
    assert result.human_merge_gate_required is True
    assert result.cisco_execution_allowed is False


def test_ready_wait_does_not_retry_non_ci_blocked_review() -> None:
    blocked = _ready_result(
        report=_report(
            decision=ReviewDecision.BLOCKED,
            checks=(_check(ReviewCheckId.SCOPE_001, ReviewCheckStatus.UNKNOWN),),
        ),
        decision=ReadyForReviewDecision.REVIEW_NOT_APPROVED,
        ready=False,
    )
    calls = 0
    delays: list[float] = []

    def executor(operation: ReadyForReviewOperation) -> ReadyForReviewControlPlaneResult:
        nonlocal calls
        calls += 1
        return _control(blocked)

    result = _execute_ready_for_review_with_ci_wait(
        _operation(),
        executor,
        timeout_seconds=30.0,
        poll_interval_seconds=5.0,
        sleeper=delays.append,
        clock=lambda: 0.0,
    )

    assert result == blocked
    assert calls == 1
    assert delays == []


def test_ready_wait_times_out_fail_closed_on_persistent_ci_pending() -> None:
    pending = _ready_result(
        report=_report(
            decision=ReviewDecision.BLOCKED,
            checks=(_check(ReviewCheckId.CI_002, ReviewCheckStatus.UNKNOWN),),
        ),
        decision=ReadyForReviewDecision.REVIEW_NOT_APPROVED,
        ready=False,
    )
    calls = 0
    delays: list[float] = []
    clock_values = iter((0.0, 10.0))

    def executor(operation: ReadyForReviewOperation) -> ReadyForReviewControlPlaneResult:
        nonlocal calls
        calls += 1
        return _control(pending)

    result = _execute_ready_for_review_with_ci_wait(
        _operation(),
        executor,
        timeout_seconds=5.0,
        poll_interval_seconds=1.0,
        sleeper=delays.append,
        clock=lambda: next(clock_values),
    )

    assert result == pending
    assert calls == 1
    assert delays == []
