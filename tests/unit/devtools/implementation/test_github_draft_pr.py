from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.implementation.github_draft_pr import (
    GitHubImplementationDraftPrBackend,
    ImplementationGitHubDraftPrError,
)


class FakeDraftPrTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Mapping[str, object]]] = []
        self.responses: dict[str, object] = {}
        self.post_response: object = {}

    def get_json(self, path: str) -> object:
        return self.responses[path]

    def get_text(self, path: str, *, accept: str) -> str:
        del path, accept
        raise AssertionError("text endpoint is not used by Draft PR backend")

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        self.posts.append((path, payload))
        return self.post_response


def test_create_draft_pr_uses_exact_closed_payload() -> None:
    transport = FakeDraftPrTransport()
    transport.post_response = {"number": 57}
    backend = GitHubImplementationDraftPrBackend(transport=transport)

    payload = backend.create_draft_pull_request(
        "owner/repo",
        title="feat: example",
        body="body",
        base_branch="main",
        head_branch="agent/implementation/example",
    )

    assert payload == {"number": 57}
    assert transport.posts == [
        (
            "/repos/owner/repo/pulls",
            {
                "title": "feat: example",
                "body": "body",
                "head": "agent/implementation/example",
                "base": "main",
                "draft": True,
                "maintainer_can_modify": False,
            },
        )
    ]


def test_create_draft_pr_rejects_non_agent_branch() -> None:
    transport = FakeDraftPrTransport()
    backend = GitHubImplementationDraftPrBackend(transport=transport)

    with pytest.raises(ImplementationGitHubDraftPrError, match="only permits"):
        backend.create_draft_pull_request(
            "owner/repo",
            title="feat: example",
            body="body",
            base_branch="main",
            head_branch="feature/example",
        )

    assert transport.posts == []


def test_list_open_prs_filters_exact_base_and_head() -> None:
    transport = FakeDraftPrTransport()
    path = (
        "/repos/owner/repo/pulls?state=open&base=main"
        "&head=owner%3Aagent%2Fimplementation%2Fexample&per_page=100&page=1"
    )
    transport.responses[path] = [{"number": 57, "draft": True}]
    backend = GitHubImplementationDraftPrBackend(transport=transport)

    prs = backend.list_open_pull_requests(
        "owner/repo",
        base_branch="main",
        head_branch="agent/implementation/example",
    )

    assert tuple(item["number"] for item in prs) == (57,)


def test_get_pr_and_branch_use_read_surface() -> None:
    transport = FakeDraftPrTransport()
    transport.responses["/repos/owner/repo/branches/main"] = {"commit": {"sha": "base-123"}}
    transport.responses["/repos/owner/repo/pulls/57"] = {"number": 57, "draft": True}
    backend = GitHubImplementationDraftPrBackend(transport=transport)

    assert backend.get_branch("owner/repo", "main") == {"commit": {"sha": "base-123"}}
    assert backend.get_pull_request("owner/repo", 57) == {"number": 57, "draft": True}


def test_malformed_open_pr_payload_is_rejected() -> None:
    transport = FakeDraftPrTransport()
    path = (
        "/repos/owner/repo/pulls?state=open&base=main"
        "&head=owner%3Aagent%2Fimplementation%2Fexample&per_page=100&page=1"
    )
    transport.responses[path] = "not-an-array"
    backend = GitHubImplementationDraftPrBackend(transport=transport)

    with pytest.raises(ImplementationGitHubDraftPrError, match="array"):
        backend.list_open_pull_requests(
            "owner/repo",
            base_branch="main",
            head_branch="agent/implementation/example",
        )
