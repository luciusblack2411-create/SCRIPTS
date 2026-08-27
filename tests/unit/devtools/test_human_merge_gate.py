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

REPOSITORY = "luciusblack2411-create/SCRIPTS"
PR_BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
LIVE_BASE_SHA = "c" * 40
MERGE_SHA = "d" * 40
HEAD_BRANCH = "agent/implementation/example"


def _request() -> ReviewRequest:
    return ReviewRequest(
        repository=REPOSITORY,
        pr_number=71,
        objective="Implement one approved feature.",
        expected_components=(ComponentId.TESTING_FIXTURES,),
    )


def _ci_003(
    *,
    status: ReviewCheckStatus = ReviewCheckStatus.PASS,
    applicable: bool = True,
    with_evidence: bool = True,
) -> ReviewCheck:
    evidence = (
        (
            ReviewEvidence(
                evidence_id="CI-003:ev:001",
                kind=ReviewEvidenceKind.CI_CHECK,
                description="Current base/head merge checkout was proved by CI.",
                check_id=ReviewCheckId.CI_003,
            ),
        )
        if with_evidence
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
    checks: tuple[ReviewCheck, ...] | None = None,
) -> ReviewReport:
    return ReviewReport(
        repository=REPOSITORY,
        pr_number=71,
        base_branch="main",
        base_sha=PR_BASE_SHA,
        base_branch_head_sha=LIVE_BASE_SHA,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
        mergeable=True,
        objective="Implement one approved feature.",
        detected_components=(ComponentId.TESTING_FIXTURES,),
        checks=checks if checks is not None else (_ci_003(),),
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
        "base_sha": LIVE_BASE_SHA,
        "head_sha": HEAD_SHA,
        "authorized_by": "human-operator",
        "rationale": "Explicitly approved after review.",
    }
    values.update(updates)
    return HumanMergeAuthorization.model_validate(values)


class FakeMergeBackend:
    def __init__(
        self,
        *,
        live_base_sha: str = LIVE_BASE_SHA,
        live_head_sha: str = HEAD_SHA,
        pr_base_ref: str = "main",
        pr_base_sha: str = PR_BASE_SHA,
        pr_head_ref: str = HEAD_BRANCH,
        pr_head_sha: str = HEAD_SHA,
    ) -> None:
        self.merged = False
        self.merge_calls: list[tuple[str, int, str, str]] = []
        self.live_base_sha = live_base_sha
        self.live_head_sha = live_head_sha
        self.pr_base_ref = pr_base_ref
        self.pr_base_sha = pr_base_sha
        self.pr_head_ref = pr_head_ref
        self.pr_head_sha = pr_head_sha

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert pr_number == 71
        return {
            "state": "closed" if self.merged else "open",
            "draft": False,
            "merged": self.merged,
            "base": {"ref": self.pr_base_ref, "sha": self.pr_base_sha},
            "head": {"ref": self.pr_head_ref, "sha": self.pr_head_sha},
        }

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        assert repository == REPOSITORY
        if branch == "main":
            return {"commit": {"sha": MERGE_SHA if self.merged else self.live_base_sha}}
        if branch == HEAD_BRANCH:
            return {"commit": {"sha": self.live_head_sha}}
        return None

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        assert repository == REPOSITORY
        assert commit_sha == MERGE_SHA
        return {"parents": [{"sha": LIVE_BASE_SHA}, {"sha": HEAD_SHA}]}

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


def _execute(
    backend: FakeMergeBackend,
    *,
    report: ReviewReport | None = None,
    authorization: HumanMergeAuthorization | None = None,
):
    operation = HumanMergeOperation(
        review_request=_request(),
        authorization=authorization or _authorization(),
    )
    return execute_human_merge(
        operation,
        review_backend=object(),  # type: ignore[arg-type]
        merge_backend=backend,
        reviewer=lambda request, review_backend: report or _report(),
    )


def test_historical_snapshot_can_differ_from_live_base_for_one_verified_merge() -> None:
    backend = FakeMergeBackend()

    result = _execute(backend)

    assert PR_BASE_SHA != LIVE_BASE_SHA
    assert result.decision is HumanMergeDecision.MERGED
    assert result.merge_performed is True
    assert result.merge_commit_sha == MERGE_SHA
    assert result.main_head_after_merge == MERGE_SHA
    assert result.base_sha == LIVE_BASE_SHA
    assert result.review_report.base_sha == PR_BASE_SHA
    assert result.review_report.base_branch_head_sha == LIVE_BASE_SHA
    assert backend.merge_calls == [(REPOSITORY, 71, HEAD_SHA, "merge")]


def test_non_approve_review_never_mutates() -> None:
    backend = FakeMergeBackend()

    result = _execute(backend, report=_report(ReviewDecision.NEEDS_HUMAN_REVIEW))

    assert result.decision is HumanMergeDecision.REVIEW_NOT_APPROVED
    assert result.merge_performed is False
    assert backend.merge_calls == []


def test_authorization_must_bind_reviewed_head_and_live_base() -> None:
    for authorization, message in (
        (_authorization(head_sha="e" * 40), "authorization head SHA"),
        (_authorization(base_sha=PR_BASE_SHA), "authorization base SHA"),
    ):
        backend = FakeMergeBackend()
        with pytest.raises(HumanMergeError, match=message):
            _execute(backend, authorization=authorization)
        assert backend.merge_calls == []


def test_live_base_or_head_drift_stops_before_merge() -> None:
    for backend in (
        FakeMergeBackend(live_base_sha="e" * 40),
        FakeMergeBackend(live_head_sha="e" * 40),
    ):
        result = _execute(backend)
        assert result.decision is HumanMergeDecision.NEEDS_BASE_REFRESH
        assert result.merge_performed is False
        assert backend.merge_calls == []


def test_pull_request_snapshot_and_head_binding_are_exact() -> None:
    backends = (
        FakeMergeBackend(pr_base_ref="release"),
        FakeMergeBackend(pr_base_sha="e" * 40),
        FakeMergeBackend(pr_head_ref="feat/other"),
        FakeMergeBackend(pr_head_sha="e" * 40),
    )
    for backend in backends:
        with pytest.raises(HumanMergeError, match="pull request .*ref/SHA"):
            _execute(backend)
        assert backend.merge_calls == []


def test_approve_requires_exactly_one_applicable_ci_003_pass_with_evidence() -> None:
    invalid_checks = (
        (),
        (_ci_003(status=ReviewCheckStatus.FAIL, with_evidence=False),),
        (_ci_003(applicable=False),),
        (_ci_003(with_evidence=False),),
        (_ci_003(), _ci_003()),
    )
    for checks in invalid_checks:
        backend = FakeMergeBackend()
        with pytest.raises(HumanMergeError, match="CI-003 PASS evidence"):
            _execute(backend, report=_report(checks=checks))
        assert backend.merge_calls == []


def test_merge_commit_first_parent_must_be_live_base() -> None:
    class WrongParentsBackend(FakeMergeBackend):
        def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
            return {"parents": [{"sha": PR_BASE_SHA}, {"sha": HEAD_SHA}]}

    backend = WrongParentsBackend()
    with pytest.raises(HumanMergeError, match="parents"):
        _execute(backend)

    assert backend.merge_calls == [(REPOSITORY, 71, HEAD_SHA, "merge")]


def test_draft_pr_is_rejected_before_merge() -> None:
    class DraftBackend(FakeMergeBackend):
        def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
            payload = dict(super().get_pull_request(repository, pr_number))
            payload["draft"] = True
            return payload

    backend = DraftBackend()
    with pytest.raises(HumanMergeError, match="Ready for Review"):
        _execute(backend)
    assert backend.merge_calls == []
