from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.github_ready_for_review import (
    GitHubReadyForReviewBackend,
    GitHubReadyForReviewError,
    UrllibGitHubReadyForReviewTransport,
)

REPOSITORY = "luciusblack2411-create/SCRIPTS"


class FakeTransport:
    def __init__(self) -> None:
        self.graphql_calls: list[tuple[str, Mapping[str, object]]] = []

    def get_json(self, path: str) -> object:
        if path.endswith("/pulls/61"):
            return {
                "node_id": "PR_node_61",
                "state": "open",
                "draft": True,
                "merged": False,
                "base": {"ref": "main", "sha": "a" * 40},
                "head": {"ref": "agent/implementation/example", "sha": "b" * 40},
            }
        if "/branches/" in path:
            return {"commit": {"sha": "a" * 40}}
        raise AssertionError(path)

    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        self.graphql_calls.append((query, variables))
        return {
            "data": {
                "markPullRequestReadyForReview": {
                    "pullRequest": {
                        "number": 61,
                        "isDraft": False,
                        "url": "https://github.com/luciusblack2411-create/SCRIPTS/pull/61",
                    }
                }
            }
        }


class ErrorTransport(FakeTransport):
    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        self.graphql_calls.append((query, variables))
        return {
            "data": {"markPullRequestReadyForReview": None},
            "errors": [
                {
                    "message": "Resource not accessible by personal access token",
                    "extensions": {"type": "FORBIDDEN"},
                }
            ],
        }


class MalformedErrorTransport(FakeTransport):
    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        self.graphql_calls.append((query, variables))
        return {"errors": "not-an-array"}


def test_backend_marks_only_requested_pull_request_ready() -> None:
    transport = FakeTransport()
    backend = GitHubReadyForReviewBackend(transport=transport)

    result = backend.mark_pull_request_ready(REPOSITORY, 61)

    assert result["isDraft"] is False
    assert len(transport.graphql_calls) == 1
    query, variables = transport.graphql_calls[0]
    assert "markPullRequestReadyForReview" in query
    assert "mergePullRequest" not in query
    assert variables == {"pullRequestId": "PR_node_61"}


def test_backend_surfaces_sanitized_graphql_error_message_and_type() -> None:
    backend = GitHubReadyForReviewBackend(transport=ErrorTransport())

    with pytest.raises(
        GitHubReadyForReviewError,
        match=(
            "GitHub GraphQL Ready-for-Review rejected: "
            "FORBIDDEN: Resource not accessible by personal access token"
        ),
    ):
        backend.mark_pull_request_ready(REPOSITORY, 61)


def test_backend_rejects_malformed_graphql_errors_payload() -> None:
    backend = GitHubReadyForReviewBackend(transport=MalformedErrorTransport())

    with pytest.raises(GitHubReadyForReviewError, match="errors payload must be an array"):
        backend.mark_pull_request_ready(REPOSITORY, 61)


def test_backend_requires_explicit_token_without_test_transport() -> None:
    with pytest.raises(GitHubReadyForReviewError, match="explicitly injected token"):
        GitHubReadyForReviewBackend()


def test_transport_rejects_arbitrary_graphql_operations_before_network() -> None:
    transport = UrllibGitHubReadyForReviewTransport(token="secret-test-value")

    with pytest.raises(GitHubReadyForReviewError, match="permits only"):
        transport.post_graphql("mutation { mergePullRequest(input: {}) { clientMutationId } }", {})


def test_invalid_repository_is_rejected() -> None:
    backend = GitHubReadyForReviewBackend(transport=FakeTransport())

    with pytest.raises(GitHubReadyForReviewError, match="owner/name"):
        backend.get_pull_request("invalid", 61)
