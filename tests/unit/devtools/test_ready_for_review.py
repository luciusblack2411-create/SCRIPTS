from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.pr_review.enums import ComponentId, ReviewDecision
from cisco_assessment.devtools.pr_review.models import ReviewReport, ReviewRequest
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewAuthorization,
    ReadyForReviewDecision,
    ReadyForReviewError,
    ReadyForReviewOperation,
    execute_ready_for_review,
)

REPOSITORY = "luciusblack2411-create/SCRIPTS"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class FakeReviewBackend:
    pass


class FakeTransitionBackend:
    def __init__(
        self,
        *,
        base_sha: str = BASE_SHA,
        head_sha: str = HEAD_SHA,
        post_base_sha: str | None = None,
    ) -> None:
        self.base_sha = base_sha
        self.head_sha = head_sha
        self.post_base_sha = post_base_sha
        self.ready = False
        self.mark_calls = 0

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert pr_number == 61
        return {
            "state": "open",
            "draft": not self.ready,
            "merged": False,
            "base": {"ref": "main", "sha": BASE_SHA},
            "head": {"ref": "agent/implementation/example", "sha": HEAD_SHA},
        }

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        assert repository == REPOSITORY
        if branch == "main":
            sha = (
                self.post_base_sha
                if self.ready and self.post_base_sha is not None
                else self.base_sha
            )
            return {"commit": {"sha": sha}}
        if branch == "agent/implementation/example":
            return {"commit": {"sha": self.head_sha}}
        return None

    def mark_pull_request_ready(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert pr_number == 61
        self.mark_calls += 1
        self.ready = True
        return {"isDraft": False}


def _request() -> ReviewRequest:
    return ReviewRequest(
        repository=REPOSITORY,
        pr_number=61,
        objective="Validate review handoff.",
        expected_components=(ComponentId.TESTING_FIXTURES,),
    )


def _report(decision: ReviewDecision = ReviewDecision.APPROVE) -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=61,
        base_branch="main",
        base_sha=BASE_SHA,
        base_branch_head_sha=BASE_SHA,
        head_branch="agent/implementation/example",
        head_sha=HEAD_SHA,
        mergeable=True,
        objective="Validate review handoff.",
        detected_components=(ComponentId.TESTING_FIXTURES,),
        checks=(),
        findings=(),
        contracts_changed=(),
        contracts_verified_stable=(),
        residual_risks=(),
        decision=decision,
        decision_reason="test",
    )


def _operation() -> ReadyForReviewOperation:
    return ReadyForReviewOperation(
        review_request=_request(),
        authorization=ReadyForReviewAuthorization.READY_FOR_REVIEW,
    )


def _reviewer(report: ReviewReport):
    def execute(request: ReviewRequest, backend: object) -> ReviewReport:
        assert request == _request()
        assert isinstance(backend, FakeReviewBackend)
        return report

    return execute


def test_approve_marks_draft_ready_and_stops_before_merge() -> None:
    backend = FakeTransitionBackend()
    result = execute_ready_for_review(
        _operation(),
        review_backend=FakeReviewBackend(),
        transition_backend=backend,
        reviewer=_reviewer(_report()),
    )

    assert result.decision is ReadyForReviewDecision.READY_FOR_REVIEW
    assert result.ready_for_review is True
    assert result.review_report.decision is ReviewDecision.APPROVE
    assert result.review_executed is True
    assert result.merge_performed is False
    assert result.human_merge_gate_required is True
    assert result.cisco_execution_allowed is False
    assert backend.mark_calls == 1


def test_non_approve_never_mutates_pull_request() -> None:
    backend = FakeTransitionBackend()
    result = execute_ready_for_review(
        _operation(),
        review_backend=FakeReviewBackend(),
        transition_backend=backend,
        reviewer=_reviewer(_report(ReviewDecision.REQUEST_CHANGES)),
    )

    assert result.decision is ReadyForReviewDecision.REVIEW_NOT_APPROVED
    assert result.ready_for_review is False
    assert backend.mark_calls == 0


def test_stale_base_never_mutates_pull_request() -> None:
    backend = FakeTransitionBackend(base_sha="c" * 40)
    result = execute_ready_for_review(
        _operation(),
        review_backend=FakeReviewBackend(),
        transition_backend=backend,
        reviewer=_reviewer(_report()),
    )

    assert result.decision is ReadyForReviewDecision.NEEDS_BASE_REFRESH
    assert result.ready_for_review is False
    assert backend.mark_calls == 0


def test_head_drift_never_mutates_pull_request() -> None:
    backend = FakeTransitionBackend(head_sha="d" * 40)
    result = execute_ready_for_review(
        _operation(),
        review_backend=FakeReviewBackend(),
        transition_backend=backend,
        reviewer=_reviewer(_report()),
    )

    assert result.decision is ReadyForReviewDecision.NEEDS_BASE_REFRESH
    assert result.ready_for_review is False
    assert backend.mark_calls == 0


def test_post_transition_base_drift_is_reported_without_merge() -> None:
    backend = FakeTransitionBackend(post_base_sha="e" * 40)
    result = execute_ready_for_review(
        _operation(),
        review_backend=FakeReviewBackend(),
        transition_backend=backend,
        reviewer=_reviewer(_report()),
    )

    assert result.decision is ReadyForReviewDecision.NEEDS_BASE_REFRESH
    assert result.ready_for_review is True
    assert result.base_fresh_after_transition is False
    assert result.merge_performed is False
    assert backend.mark_calls == 1


def test_pull_request_must_still_be_draft() -> None:
    backend = FakeTransitionBackend()
    backend.ready = True

    with pytest.raises(ReadyForReviewError, match="must still be Draft"):
        execute_ready_for_review(
            _operation(),
            review_backend=FakeReviewBackend(),
            transition_backend=backend,
            reviewer=_reviewer(_report()),
        )
