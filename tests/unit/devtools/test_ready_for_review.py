from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.enums import (
    ComponentId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewEvidenceKind,
)
from cisco_assessment.devtools.pr_review.models import (
    ReviewCheck,
    ReviewEvidence,
    ReviewReport,
    ReviewRequest,
)
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewAuthorization,
    ReadyForReviewDecision,
    ReadyForReviewError,
    ReadyForReviewOperation,
    execute_ready_for_review,
)

REPOSITORY = "luciusblack2411-create/SCRIPTS"
PR_BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
LIVE_BASE_SHA = "c" * 40


class FakeReviewBackend:
    pass


class FakeTransitionBackend:
    def __init__(
        self,
        *,
        base_sha: str = LIVE_BASE_SHA,
        head_sha: str = HEAD_SHA,
        post_base_sha: str | None = None,
        pr_base_ref: str = "main",
        pr_base_sha: str = PR_BASE_SHA,
        pr_head_ref: str = "agent/implementation/example",
        pr_head_sha: str = HEAD_SHA,
    ) -> None:
        self.base_sha = base_sha
        self.head_sha = head_sha
        self.post_base_sha = post_base_sha
        self.pr_base_ref = pr_base_ref
        self.pr_base_sha = pr_base_sha
        self.pr_head_ref = pr_head_ref
        self.pr_head_sha = pr_head_sha
        self.ready = False
        self.mark_calls = 0

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert pr_number == 61
        return {
            "state": "open",
            "draft": not self.ready,
            "merged": False,
            "base": {"ref": self.pr_base_ref, "sha": self.pr_base_sha},
            "head": {"ref": self.pr_head_ref, "sha": self.pr_head_sha},
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


def _ci_003(
    status: ReviewCheckStatus = ReviewCheckStatus.PASS,
) -> ReviewCheck:
    applicable = status is not ReviewCheckStatus.NOT_APPLICABLE
    evidence = (
        (
            ReviewEvidence(
                evidence_id="CI-003:ev:001",
                kind=ReviewEvidenceKind.CI_CHECK,
                description="Current base/head merge checkout was proved by CI.",
                check_id=ReviewCheckId.CI_003,
            ),
        )
        if status is ReviewCheckStatus.PASS
        else ()
    )
    return ReviewCheck(
        check_id=ReviewCheckId.CI_003,
        name="Successful CI proves the current pull-request merge checkout",
        category="CI",
        status=status,
        applicable=applicable,
        summary="test CI provenance",
        evidence=evidence,
        findings=(),
        blocking=True,
    )


def _report(
    decision: ReviewDecision = ReviewDecision.APPROVE,
    *,
    ci_status: ReviewCheckStatus = ReviewCheckStatus.PASS,
) -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=61,
        base_branch="main",
        base_sha=PR_BASE_SHA,
        base_branch_head_sha=LIVE_BASE_SHA,
        head_branch="agent/implementation/example",
        head_sha=HEAD_SHA,
        mergeable=True,
        objective="Validate review handoff.",
        detected_components=(ComponentId.TESTING_FIXTURES,),
        checks=(_ci_003(ci_status),),
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


def test_approve_accepts_historical_pr_snapshot_and_marks_ready() -> None:
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
    assert result.base_sha == PR_BASE_SHA
    assert result.base_head_after_transition == LIVE_BASE_SHA
    assert result.base_fresh_after_transition is True
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


def test_live_base_drift_never_mutates_pull_request() -> None:
    backend = FakeTransitionBackend(base_sha="d" * 40)
    result = execute_ready_for_review(
        _operation(),
        review_backend=FakeReviewBackend(),
        transition_backend=backend,
        reviewer=_reviewer(_report()),
    )

    assert result.decision is ReadyForReviewDecision.NEEDS_BASE_REFRESH
    assert result.ready_for_review is False
    assert backend.mark_calls == 0


def test_invalid_pr_snapshot_binding_never_mutates_pull_request() -> None:
    backend = FakeTransitionBackend(pr_base_sha="d" * 40)

    with pytest.raises(
        ReadyForReviewError,
        match="pull request base ref/SHA no longer matches reviewed evidence",
    ):
        execute_ready_for_review(
            _operation(),
            review_backend=FakeReviewBackend(),
            transition_backend=backend,
            reviewer=_reviewer(_report()),
        )

    assert backend.mark_calls == 0


def test_approve_requires_ci_003_pass_evidence() -> None:
    backend = FakeTransitionBackend()

    with pytest.raises(
        ReadyForReviewError,
        match="CI-003 PASS evidence",
    ):
        execute_ready_for_review(
            _operation(),
            review_backend=FakeReviewBackend(),
            transition_backend=backend,
            reviewer=_reviewer(
                _report(ci_status=ReviewCheckStatus.NOT_APPLICABLE)
            ),
        )

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
