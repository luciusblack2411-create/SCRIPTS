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


def _evidence(evidence_id: str = "CI-003:ev:001") -> ReviewEvidence:
    return ReviewEvidence(
        evidence_id=evidence_id,
        kind=ReviewEvidenceKind.CI_CHECK,
        description="Current live base and head merge checkout was proved by CI.",
        check_id=ReviewCheckId.CI_003,
    )


def _ci_003(
    status: ReviewCheckStatus = ReviewCheckStatus.PASS,
    *,
    evidence: tuple[ReviewEvidence, ...] | None = None,
) -> ReviewCheck:
    applicable = status is not ReviewCheckStatus.NOT_APPLICABLE
    if evidence is None:
        evidence = (_evidence(),) if applicable else ()
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
        checks=(_ci_003(),) if checks is None else checks,
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
        "rationale": "Explicitly approved after reviewing the current live refs.",
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
        return {
            "merged": True,
            "sha": MERGE_SHA,
            "message": "Pull Request successfully merged",
        }


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


def test_historical_pr_snapshot_different_from_live_base_allows_verified_merge() -> None:
    backend = FakeMergeBackend()

    result = _execute(backend)

    assert PR_BASE_SHA != LIVE_BASE_SHA
    assert result.decision is HumanMergeDecision.MERGED
    assert result.merge_performed is True
    assert result.base_sha == LIVE_BASE_SHA
    assert result.merge_commit_sha == MERGE_SHA
    assert result.main_head_after_merge == MERGE_SHA
    assert backend.get_commit(REPOSITORY, MERGE_SHA)["parents"][0] == {"sha": LIVE_BASE_SHA}
    assert backend.get_commit(REPOSITORY, MERGE_SHA)["parents"][0] != {"sha": PR_BASE_SHA}
    assert backend.merge_calls == [(REPOSITORY, 71, HEAD_SHA, "merge")]


def test_non_approve_review_never_mutates() -> None:
    backend = FakeMergeBackend()

    result = _execute(backend, report=_report(ReviewDecision.NEEDS_HUMAN_REVIEW))

    assert result.decision is HumanMergeDecision.REVIEW_NOT_APPROVED
    assert result.merge_performed is False
    assert backend.merge_calls == []


@pytest.mark.parametrize(
    ("backend", "message"),
    (
        (FakeMergeBackend(pr_base_ref="release"), "pull request base ref/SHA"),
        (FakeMergeBackend(pr_base_sha="e" * 40), "pull request base ref/SHA"),
        (FakeMergeBackend(pr_head_ref="agent/implementation/other"), "pull request head ref/SHA"),
        (FakeMergeBackend(pr_head_sha="e" * 40), "pull request head ref/SHA"),
    ),
    ids=("base-ref", "base-sha", "head-ref", "head-sha"),
)
def test_invalid_historical_pr_binding_fails_closed(
    backend: FakeMergeBackend,
    message: str,
) -> None:
    with pytest.raises(HumanMergeError, match=message):
        _execute(backend)

    assert backend.merge_calls == []


@pytest.mark.parametrize(
    "backend",
    (
        FakeMergeBackend(live_base_sha="e" * 40),
        FakeMergeBackend(live_head_sha="e" * 40),
    ),
    ids=("live-base", "live-head"),
)
def test_actual_live_ref_drift_requires_base_refresh(backend: FakeMergeBackend) -> None:
    result = _execute(backend)

    assert result.decision is HumanMergeDecision.NEEDS_BASE_REFRESH
    assert result.merge_performed is False
    assert backend.merge_calls == []


def test_stale_live_base_human_authorization_fails_closed() -> None:
    backend = FakeMergeBackend()

    with pytest.raises(HumanMergeError, match="authorization base SHA"):
        _execute(backend, authorization=_authorization(base_sha=PR_BASE_SHA))

    assert backend.merge_calls == []


@pytest.mark.parametrize(
    "checks",
    (
        (),
        (_ci_003(), _ci_003(evidence=(_evidence("CI-003:ev:002"),))),
    ),
    ids=("zero", "duplicate"),
)
def test_approve_requires_exactly_one_ci_003(checks: tuple[ReviewCheck, ...]) -> None:
    backend = FakeMergeBackend()

    with pytest.raises(HumanMergeError, match="exactly one CI-003"):
        _execute(backend, report=_report(checks=checks))

    assert backend.merge_calls == []


@pytest.mark.parametrize(
    "ci_check",
    (
        _ci_003(ReviewCheckStatus.FAIL),
        _ci_003(ReviewCheckStatus.NOT_APPLICABLE),
        _ci_003(ReviewCheckStatus.PASS, evidence=()),
    ),
    ids=("fail", "not-applicable", "missing-evidence"),
)
def test_single_ci_003_requires_pass_evidence(ci_check: ReviewCheck) -> None:
    backend = FakeMergeBackend()

    with pytest.raises(HumanMergeError, match="CI-003 PASS evidence"):
        _execute(backend, report=_report(checks=(ci_check,)))

    assert backend.merge_calls == []


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


def test_merge_parent_verification_rejects_historical_snapshot_parent() -> None:
    class HistoricalSnapshotParentBackend(FakeMergeBackend):
        def get_commit(
            self,
            repository: str,
            commit_sha: str,
        ) -> Mapping[str, object]:
            assert repository == REPOSITORY
            assert commit_sha == MERGE_SHA
            return {
                "parents": [
                    {"sha": PR_BASE_SHA},
                    {"sha": HEAD_SHA},
                ]
            }

    backend = HistoricalSnapshotParentBackend()

    with pytest.raises(HumanMergeError, match="merge commit parents"):
        _execute(backend)

    # Parent verification is post-merge evidence verification, so exactly
    # one authorized merge call occurred before the invalid parent was detected.
    assert backend.merge_calls == [
        (REPOSITORY, 71, HEAD_SHA, "merge")
    ]
