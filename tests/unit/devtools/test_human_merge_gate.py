from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import pytest

from cisco_assessment.devtools.human_merge_gate import (
    HumanMergeAuthorization,
    HumanMergeDecision,
    HumanMergeError,
    HumanMergeOperation,
    execute_human_merge,
)
from cisco_assessment.devtools.pr_review.enums import ComponentId, ReviewDecision
from cisco_assessment.devtools.pr_review.models import ReviewReport, ReviewRequest

REPOSITORY = "luciusblack2411-create/SCRIPTS"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40
HEAD_BRANCH = "agent/implementation/example"


def _request() -> ReviewRequest:
    return ReviewRequest(
        repository=REPOSITORY,
        pr_number=71,
        objective="Implement one approved feature.",
        expected_components=(ComponentId.TESTING_FIXTURES,),
    )


def _report(decision: ReviewDecision = ReviewDecision.APPROVE) -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=71,
        base_branch="main",
        base_sha=BASE_SHA,
        base_branch_head_sha=BASE_SHA,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
        mergeable=True,
        objective="Implement one approved feature.",
        detected_components=(ComponentId.TESTING_FIXTURES,),
        checks=(),
        findings=(),
        contracts_changed=(),
        contracts_verified_stable=(),
        residual_risks=(),
        decision=decision,
        decision_reason="test decision",
    )


def _authorization(**updates: object) -> HumanMergeAuthorization:
    values: dict[str, object] = {
        "decision": "MERGE_APPROVED",
        "repository": REPOSITORY,
        "pr_number": 71,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "authorized_by": "human-operator",
        "rationale": "Explicitly approved after review.",
    }
    values.update(updates)
    return HumanMergeAuthorization.model_validate(values)


class FakeMergeBackend:
    def __init__(self) -> None:
        self.merged = False
        self.merge_calls: list[tuple[str, int, str, str]] = []
        self.base_sha = BASE_SHA

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert pr_number == 71
        return {
            "state": "closed" if self.merged else "open",
            "draft": False,
            "merged": self.merged,
            "base": {"ref": "main", "sha": self.base_sha},
            "head": {"ref": HEAD_BRANCH, "sha": HEAD_SHA},
        }

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        assert repository == REPOSITORY
        if branch == "main":
            return {"commit": {"sha": MERGE_SHA if self.merged else self.base_sha}}
        if branch == HEAD_BRANCH:
            return {"commit": {"sha": HEAD_SHA}}
        return None

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert commit_sha == MERGE_SHA
        return {"parents": [{"sha": BASE_SHA}, {"sha": HEAD_SHA}]}

    def merge_pull_request(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        merge_method: Literal["merge"],
    ) -> Mapping[str, object]:
        self.merge_calls.append((repository, pr_number, expected_head_sha, merge_method))
        self.merged = True
        return {"merged": True, "sha": MERGE_SHA, "message": "Pull Request successfully merged"}


def test_exact_human_authorization_allows_one_verified_merge() -> None:
    backend = FakeMergeBackend()
    operation = HumanMergeOperation(
        review_request=_request(),
        authorization=_authorization(),
    )

    result = execute_human_merge(
        operation,
        review_backend=object(),  # type: ignore[arg-type]
        merge_backend=backend,
        reviewer=lambda request, backend: _report(),
    )

    assert result.decision is HumanMergeDecision.MERGED
    assert result.merge_performed is True
    assert result.merge_commit_sha == MERGE_SHA
    assert result.main_head_after_merge == MERGE_SHA
    assert backend.merge_calls == [(REPOSITORY, 71, HEAD_SHA, "merge")]


def test_non_approve_review_never_mutates() -> None:
    backend = FakeMergeBackend()
    operation = HumanMergeOperation(review_request=_request(), authorization=_authorization())

    result = execute_human_merge(
        operation,
        review_backend=object(),  # type: ignore[arg-type]
        merge_backend=backend,
        reviewer=lambda request, backend: _report(ReviewDecision.NEEDS_HUMAN_REVIEW),
    )

    assert result.decision is HumanMergeDecision.REVIEW_NOT_APPROVED
    assert result.merge_performed is False
    assert backend.merge_calls == []


def test_authorization_must_bind_exact_reviewed_head() -> None:
    operation = HumanMergeOperation(
        review_request=_request(),
        authorization=_authorization(head_sha="d" * 40),
    )

    with pytest.raises(HumanMergeError, match="authorization head SHA"):
        execute_human_merge(
            operation,
            review_backend=object(),  # type: ignore[arg-type]
            merge_backend=FakeMergeBackend(),
            reviewer=lambda request, backend: _report(),
        )


def test_base_drift_stops_before_merge() -> None:
    backend = FakeMergeBackend()
    backend.base_sha = "d" * 40
    operation = HumanMergeOperation(review_request=_request(), authorization=_authorization())

    result = execute_human_merge(
        operation,
        review_backend=object(),  # type: ignore[arg-type]
        merge_backend=backend,
        reviewer=lambda request, backend: _report(),
    )

    assert result.decision is HumanMergeDecision.NEEDS_BASE_REFRESH
    assert backend.merge_calls == []


def test_draft_pr_is_rejected_before_merge() -> None:
    class DraftBackend(FakeMergeBackend):
        def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
            payload = dict(super().get_pull_request(repository, pr_number))
            payload["draft"] = True
            return payload

    with pytest.raises(HumanMergeError, match="Ready for Review"):
        execute_human_merge(
            HumanMergeOperation(review_request=_request(), authorization=_authorization()),
            review_backend=object(),  # type: ignore[arg-type]
            merge_backend=DraftBackend(),
            reviewer=lambda request, backend: _report(),
        )
