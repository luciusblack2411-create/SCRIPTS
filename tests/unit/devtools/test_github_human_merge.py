from __future__ import annotations

from typing import Literal

import pytest

from cisco_assessment.devtools.github_human_merge import (
    GitHubHumanMergeBackend,
    GitHubHumanMergeError,
)

REPOSITORY = "luciusblack2411-create/SCRIPTS"
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40


class FakeTransport:
    def __init__(self) -> None:
        self.merge_calls: list[tuple[str, int, str, str]] = []

    def get_json(self, path: str) -> object:
        if path.endswith("/pulls/71"):
            return {"state": "open"}
        if "/branches/" in path:
            return {"commit": {"sha": HEAD_SHA}}
        if "/commits/" in path:
            return {"parents": [{"sha": "a" * 40}, {"sha": HEAD_SHA}]}
        raise AssertionError(path)

    def put_merge(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        merge_method: Literal["merge"],
    ) -> object:
        self.merge_calls.append((repository, pr_number, expected_head_sha, merge_method))
        return {"sha": MERGE_SHA, "merged": True, "message": "merged"}


def test_backend_exposes_only_merge_specific_write_operation() -> None:
    transport = FakeTransport()
    backend = GitHubHumanMergeBackend(transport=transport)

    result = backend.merge_pull_request(
        REPOSITORY,
        71,
        expected_head_sha=HEAD_SHA,
        merge_method="merge",
    )

    assert result["merged"] is True
    assert transport.merge_calls == [(REPOSITORY, 71, HEAD_SHA, "merge")]


def test_backend_requires_explicit_token_without_test_transport() -> None:
    with pytest.raises(GitHubHumanMergeError, match="explicitly injected token"):
        GitHubHumanMergeBackend()


def test_invalid_repository_is_rejected_on_read() -> None:
    backend = GitHubHumanMergeBackend(transport=FakeTransport())

    with pytest.raises(GitHubHumanMergeError, match="owner/name"):
        backend.get_pull_request("invalid", 71)
