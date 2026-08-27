from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.github_return_to_draft import (
    GitHubReturnToDraftBackend,
    GitHubReturnToDraftError,
    UrllibGitHubReturnToDraftTransport,
)

REPOSITORY = "luciusblack2411-create/SCRIPTS"


class Transport:
    def __init__(self, response: object | None = None) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def get_json(self, path: str) -> object:
        assert path.endswith("/pulls/61")
        return {"node_id": "PR_node_61"}

    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        self.calls.append((query, variables))
        if self.response is not None:
            return self.response
        return {
            "data": {
                "convertPullRequestToDraft": {
                    "pullRequest": {"number": 61, "isDraft": True, "url": "https://example.test"}
                }
            }
        }


def test_backend_performs_exactly_one_convert_mutation() -> None:
    transport = Transport()
    result = GitHubReturnToDraftBackend(transport=transport).convert_pull_request_to_draft(
        REPOSITORY, 61
    )
    assert result["isDraft"] is True
    assert len(transport.calls) == 1
    query, variables = transport.calls[0]
    assert "convertPullRequestToDraft" in query
    assert "mergePullRequest" not in query
    assert variables == {"pullRequestId": "PR_node_61"}


def test_transport_rejects_every_other_mutation_before_network() -> None:
    transport = UrllibGitHubReturnToDraftTransport(token="test-secret")
    with pytest.raises(GitHubReturnToDraftError, match="permits only"):
        transport.post_graphql("mutation { mergePullRequest(input: {}) { clientMutationId } }", {})


def test_graphql_errors_fail_closed() -> None:
    response = {"errors": [{"message": "forbidden"}], "data": None}
    with pytest.raises(GitHubReturnToDraftError, match="rejected: forbidden"):
        GitHubReturnToDraftBackend(transport=Transport(response)).convert_pull_request_to_draft(
            REPOSITORY, 61
        )


@pytest.mark.parametrize(
    "response,match",
    [
        ({"errors": "bad"}, "errors payload must be an array"),
        ({"data": None}, "data payload must be an object"),
        ({"data": {"convertPullRequestToDraft": None}}, "convertPullRequestToDraft payload"),
    ],
)
def test_malformed_graphql_responses_fail_closed(response: object, match: str) -> None:
    with pytest.raises(GitHubReturnToDraftError, match=match):
        GitHubReturnToDraftBackend(transport=Transport(response)).convert_pull_request_to_draft(
            REPOSITORY, 61
        )


def test_backend_requires_explicit_token() -> None:
    with pytest.raises(GitHubReturnToDraftError, match="explicitly injected token"):
        GitHubReturnToDraftBackend()
