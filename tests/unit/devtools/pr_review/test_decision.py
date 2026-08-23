from __future__ import annotations

from cisco_assessment.devtools.pr_review import (
    ReviewCheck,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewFinding,
    ReviewFindingSeverity,
    derive_review_decision,
)


def _check(
    status: ReviewCheckStatus,
    *,
    blocking: bool = True,
    check_id: ReviewCheckId = ReviewCheckId.SCOPE_001,
) -> ReviewCheck:
    evidence = ()
    if blocking and status is ReviewCheckStatus.FAIL:
        evidence = (
            ReviewEvidence(
                evidence_id=f"{check_id.value}:ev-001",
                kind=ReviewEvidenceKind.DIFF,
                description="Synthetic failing-check evidence.",
                check_id=check_id,
            ),
        )
    return ReviewCheck(
        check_id=check_id,
        name="Scope check",
        category="SCOPE",
        status=status,
        applicable=status is not ReviewCheckStatus.NOT_APPLICABLE,
        summary="Synthetic decision-engine check.",
        evidence=evidence,
        findings=(),
        blocking=blocking,
    )


def _finding(
    severity: ReviewFindingSeverity,
    *,
    requires_human_decision: bool = False,
) -> ReviewFinding:
    evidence = ReviewEvidence(
        evidence_id="ev-001",
        kind=ReviewEvidenceKind.DIFF,
        description="Synthetic diff evidence.",
        check_id=ReviewCheckId.SCOPE_001,
    )
    return ReviewFinding(
        finding_id="SCOPE-001:001",
        check_id=ReviewCheckId.SCOPE_001,
        severity=severity,
        title="Synthetic finding",
        observation="Synthetic observation.",
        evidence=(evidence,),
        requires_human_decision=requires_human_decision,
    )


def test_missing_required_review_data_blocks_before_other_outcomes() -> None:
    outcome = derive_review_decision(
        checks=(_check(ReviewCheckStatus.FAIL),),
        findings=(_finding(ReviewFindingSeverity.BLOCKING),),
        required_review_data_available=False,
    )

    assert outcome.decision is ReviewDecision.BLOCKED


def test_blocking_finding_requests_changes() -> None:
    outcome = derive_review_decision(
        checks=(_check(ReviewCheckStatus.PASS),),
        findings=(_finding(ReviewFindingSeverity.BLOCKING),),
    )

    assert outcome.decision is ReviewDecision.REQUEST_CHANGES


def test_blocking_failed_check_requests_changes_even_without_finding() -> None:
    outcome = derive_review_decision(
        checks=(_check(ReviewCheckStatus.FAIL),),
        findings=(),
    )

    assert outcome.decision is ReviewDecision.REQUEST_CHANGES


def test_human_decision_finding_escalates() -> None:
    outcome = derive_review_decision(
        checks=(_check(ReviewCheckStatus.PASS),),
        findings=(
            _finding(
                ReviewFindingSeverity.WARNING,
                requires_human_decision=True,
            ),
        ),
    )

    assert outcome.decision is ReviewDecision.NEEDS_HUMAN_REVIEW


def test_blocking_unknown_or_error_blocks() -> None:
    unknown = derive_review_decision(
        checks=(_check(ReviewCheckStatus.UNKNOWN),),
        findings=(),
    )
    error = derive_review_decision(
        checks=(_check(ReviewCheckStatus.ERROR),),
        findings=(),
    )

    assert unknown.decision is ReviewDecision.BLOCKED
    assert error.decision is ReviewDecision.BLOCKED


def test_non_blocking_warning_does_not_prevent_approval() -> None:
    outcome = derive_review_decision(
        checks=(
            _check(ReviewCheckStatus.PASS),
            _check(
                ReviewCheckStatus.WARNING,
                blocking=False,
                check_id=ReviewCheckId.SCOPE_005,
            ),
        ),
        findings=(_finding(ReviewFindingSeverity.WARNING),),
    )

    assert outcome.decision is ReviewDecision.APPROVE
