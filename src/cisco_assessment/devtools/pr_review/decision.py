"""Deterministic decision engine for PR Review Agent v0.1."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .enums import ReviewCheckStatus, ReviewDecision, ReviewFindingSeverity
from .models import ReviewCheck, ReviewFinding


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """Decision plus canonical reason derived from structured review results."""

    decision: ReviewDecision
    reason: str


def derive_review_decision(
    checks: Sequence[ReviewCheck],
    findings: Sequence[ReviewFinding],
    *,
    required_review_data_available: bool = True,
) -> DecisionOutcome:
    """Derive the final decision without free-form model judgment."""
    if not required_review_data_available:
        return DecisionOutcome(
            decision=ReviewDecision.BLOCKED,
            reason="Required review data is unavailable.",
        )

    has_blocking_finding = any(
        finding.severity is ReviewFindingSeverity.BLOCKING for finding in findings
    )
    has_blocking_failed_check = any(
        check.blocking and check.status is ReviewCheckStatus.FAIL for check in checks
    )
    if has_blocking_finding or has_blocking_failed_check:
        return DecisionOutcome(
            decision=ReviewDecision.REQUEST_CHANGES,
            reason="At least one blocking finding or blocking failed check exists.",
        )

    if any(finding.requires_human_decision for finding in findings):
        return DecisionOutcome(
            decision=ReviewDecision.NEEDS_HUMAN_REVIEW,
            reason="At least one finding requires a human decision.",
        )

    has_blocking_unknown_or_error = any(
        check.blocking and check.status in {ReviewCheckStatus.UNKNOWN, ReviewCheckStatus.ERROR}
        for check in checks
    )
    if has_blocking_unknown_or_error:
        return DecisionOutcome(
            decision=ReviewDecision.BLOCKED,
            reason="At least one blocking check is UNKNOWN or ERROR.",
        )

    return DecisionOutcome(
        decision=ReviewDecision.APPROVE,
        reason="All applicable blocking checks passed with no blocking or human-review findings.",
    )
