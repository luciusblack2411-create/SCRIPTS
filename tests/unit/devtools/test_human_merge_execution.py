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
        repository="luciusblack2411-create/SCRIPTS",
        pr_number=71,
        expected_base_branch="main",
        objective="Approved feature",
        expected_components=(ComponentId.TESTING_FIXTURES,),
        prohibited_components=(ComponentId.COLLECTOR,),
        invariants=("No Cisco execution.",),
    )


def _pull_request(*, draft: bool = False) -> dict[str, object]:
    return {
        "number": 71,
        "state": "open",
        "draft": draft,
        "merged": False,
        "base": {"ref": "main", "sha": "a" * 40},
        "head": {"ref": "feat/example", "sha": "b" * 40},
    }


def _backend(*, draft: bool = False, base_head_sha: str | None = None) -> _ChallengeBackend:
    return _ChallengeBackend(
        _pull_request(draft=draft),
        {
            "main": {"commit": {"sha": base_head_sha or "a" * 40}},
            "feat/example": {"commit": {"sha": "b" * 40}},
        },
    )


def test_challenge_binds_live_refs_and_builds_existing_operation_contract() -> None:
    challenge = prepare_human_merge_authorization_challenge(_request(), _backend())

    assert challenge.execution_surface_id == EXECUTION_SURFACE_ID
    assert challenge.repository == "luciusblack2411-create/SCRIPTS"
    assert challenge.pr_number == 71
    assert challenge.base_branch == "main"
    assert challenge.base_sha == "a" * 40
    assert challenge.head_branch == "feat/example"
    assert challenge.head_sha == "b" * 40
    assert challenge.cisco_execution_allowed is False

    operation = build_human_merge_operation_from_challenge(
        challenge,
        decision="MERGE_APPROVED",
        authorized_by="human-operator",
        rationale="Exact refs reviewed.",
    )

    assert operation.review_request == _request()
    assert operation.authorization.repository == challenge.repository
    assert operation.authorization.pr_number == challenge.pr_number
    assert operation.authorization.base_sha == challenge.base_sha
    assert operation.authorization.head_sha == challenge.head_sha
    assert operation.authorization.decision == "MERGE_APPROVED"
    assert operation.merge_method == "merge"

    rendered = render_human_merge_authorization_challenge(challenge)
    assert f"main@{'a' * 40}" in rendered
    assert f"feat/example@{'b' * 40}" in rendered
    assert "Cisco execution allowed: false" in rendered


def test_challenge_fails_closed_for_draft_or_stale_base() -> None:
    with pytest.raises(HumanMergeExecutionError, match="Ready for Review"):
        prepare_human_merge_authorization_challenge(_request(), _backend(draft=True))

    with pytest.raises(HumanMergeExecutionError, match="base branch HEAD"):
        prepare_human_merge_authorization_challenge(
            _request(),
            _backend(base_head_sha="c" * 40),
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
