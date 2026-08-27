from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisco_assessment.devtools.human_merge_execution import (
    EXECUTION_SURFACE_ID,
    HumanMergeExecutionError,
    HumanMergeReviewRequestFileError,
    build_human_merge_operation_from_challenge,
    load_human_merge_review_request,
    prepare_human_merge_authorization_challenge,
    render_human_merge_authorization_challenge,
)
from cisco_assessment.devtools.pr_review.enums import ComponentId
from cisco_assessment.devtools.pr_review.models import ReviewRequest

REPOSITORY = "luciusblack2411-create/SCRIPTS"
PR_BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
LIVE_BASE_SHA = "c" * 40
HEAD_BRANCH = "feat/example"


class _ChallengeBackend:
    def __init__(
        self,
        pull_request: dict[str, object],
        branches: dict[str, dict[str, object] | None],
    ) -> None:
        self.pull_request = pull_request
        self.branches = branches
        self.reads: list[tuple[str, str | int]] = []

    def get_pull_request(self, repository: str, pr_number: int) -> dict[str, object]:
        self.reads.append((repository, pr_number))
        return self.pull_request

    def get_branch(self, repository: str, branch: str) -> dict[str, object] | None:
        self.reads.append((repository, branch))
        return self.branches.get(branch)


def _request() -> ReviewRequest:
    return ReviewRequest(
        repository=REPOSITORY,
        pr_number=71,
        expected_base_branch="main",
        objective="Approved feature",
        expected_components=(ComponentId.TESTING_FIXTURES,),
        prohibited_components=(ComponentId.COLLECTOR,),
        invariants=("No Cisco execution.",),
    )


def _pull_request(
    *,
    draft: bool = False,
    base_ref: str = "main",
    base_sha: str = PR_BASE_SHA,
    head_ref: str = HEAD_BRANCH,
    head_sha: str = HEAD_SHA,
) -> dict[str, object]:
    return {
        "number": 71,
        "state": "open",
        "draft": draft,
        "merged": False,
        "base": {"ref": base_ref, "sha": base_sha},
        "head": {"ref": head_ref, "sha": head_sha},
    }


def _backend(
    *,
    draft: bool = False,
    live_base_sha: str = LIVE_BASE_SHA,
    live_head_sha: str = HEAD_SHA,
) -> _ChallengeBackend:
    return _ChallengeBackend(
        _pull_request(draft=draft),
        {
            "main": {"commit": {"sha": live_base_sha}},
            HEAD_BRANCH: {"commit": {"sha": live_head_sha}},
        },
    )


def test_challenge_accepts_historical_snapshot_and_authorizes_live_base() -> None:
    challenge = prepare_human_merge_authorization_challenge(_request(), _backend())

    assert PR_BASE_SHA != LIVE_BASE_SHA
    assert challenge.execution_surface_id == EXECUTION_SURFACE_ID
    assert challenge.repository == REPOSITORY
    assert challenge.pr_number == 71
    assert challenge.base_branch == "main"
    assert challenge.base_sha == LIVE_BASE_SHA
    assert challenge.head_branch == HEAD_BRANCH
    assert challenge.head_sha == HEAD_SHA
    assert challenge.cisco_execution_allowed is False

    operation = build_human_merge_operation_from_challenge(
        challenge,
        decision="MERGE_APPROVED",
        authorized_by="human-operator",
        rationale="Exact live refs reviewed.",
    )

    assert operation.review_request == _request()
    assert operation.authorization.repository == challenge.repository
    assert operation.authorization.pr_number == challenge.pr_number
    assert operation.authorization.base_sha == LIVE_BASE_SHA
    assert operation.authorization.head_sha == HEAD_SHA
    assert operation.authorization.decision == "MERGE_APPROVED"
    assert operation.merge_method == "merge"

    rendered = render_human_merge_authorization_challenge(challenge)
    assert f"main@{LIVE_BASE_SHA}" in rendered
    assert f"{HEAD_BRANCH}@{HEAD_SHA}" in rendered
    assert f"main@{PR_BASE_SHA}" not in rendered
    assert "Cisco execution allowed: false" in rendered


def test_challenge_rejects_draft_or_live_head_drift() -> None:
    with pytest.raises(HumanMergeExecutionError, match="Ready for Review"):
        prepare_human_merge_authorization_challenge(_request(), _backend(draft=True))

    with pytest.raises(HumanMergeExecutionError, match="head branch HEAD"):
        prepare_human_merge_authorization_challenge(
            _request(),
            _backend(live_head_sha="d" * 40),
        )


def test_operation_requires_exact_merge_approved_text() -> None:
    challenge = prepare_human_merge_authorization_challenge(_request(), _backend())

    with pytest.raises(HumanMergeExecutionError, match="exact decision MERGE_APPROVED"):
        build_human_merge_operation_from_challenge(
            challenge,
            decision="yes",
            authorized_by="human-operator",
            rationale="Not sufficient.",
        )


def test_review_request_file_is_strict(tmp_path: Path) -> None:
    request = _request()
    path = tmp_path / "review-request.json"
    path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    assert load_human_merge_review_request(path) == request

    payload = json.loads(request.model_dump_json())
    payload["unexpected"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HumanMergeReviewRequestFileError, match="invalid human merge review request"):
        load_human_merge_review_request(path)
