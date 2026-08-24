from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.implementation.github_mutation import (
    GitHubImplementationMutationBackend,
    ImplementationGitHubMutationError,
)
from cisco_assessment.devtools.implementation.mutation import ImplementationMutationTreeEntry
from cisco_assessment.devtools.pr_review.github_rest import GitHubRestError


class FakeMutationTransport:
    def __init__(self) -> None:
        self.get_responses: dict[str, object] = {}
        self.post_responses: dict[str, object] = {}
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, Mapping[str, object]]] = []

    def get_json(self, path: str) -> object:
        self.get_calls.append(path)
        value = self.get_responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    def get_text(self, path: str, *, accept: str) -> str:
        del path, accept
        raise AssertionError("text reads are not expected in mutation backend tests")

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        self.post_calls.append((path, payload))
        value = self.post_responses[path]
        if isinstance(value, Exception):
            raise value
        return value


def test_backend_reads_exact_commit_tree_sha() -> None:
    transport = FakeMutationTransport()
    path = "/repos/owner/repo/git/commits/base-sha"
    transport.get_responses[path] = {
        "sha": "base-sha",
        "tree": {"sha": "tree-sha"},
    }
    backend = GitHubImplementationMutationBackend(transport=transport)

    assert backend.get_commit_tree_sha("owner/repo", "base-sha") == "tree-sha"
    assert transport.get_calls == [path]


def test_backend_rejects_commit_identity_mismatch() -> None:
    transport = FakeMutationTransport()
    path = "/repos/owner/repo/git/commits/base-sha"
    transport.get_responses[path] = {
        "sha": "other-sha",
        "tree": {"sha": "tree-sha"},
    }
    backend = GitHubImplementationMutationBackend(transport=transport)

    with pytest.raises(ImplementationGitHubMutationError, match="commit identity"):
        backend.get_commit_tree_sha("owner/repo", "base-sha")


def test_backend_creates_utf8_blob_with_exact_payload() -> None:
    transport = FakeMutationTransport()
    path = "/repos/owner/repo/git/blobs"
    transport.post_responses[path] = {"sha": "blob-new"}
    backend = GitHubImplementationMutationBackend(transport=transport)

    assert backend.create_utf8_blob("owner/repo", "x = 1\n") == "blob-new"
    assert transport.post_calls == [
        (path, {"content": "x = 1\n", "encoding": "utf-8"})
    ]


def test_backend_creates_tree_and_commit_with_single_parent() -> None:
    transport = FakeMutationTransport()
    tree_path = "/repos/owner/repo/git/trees"
    commit_path = "/repos/owner/repo/git/commits"
    transport.post_responses[tree_path] = {"sha": "tree-new"}
    transport.post_responses[commit_path] = {"sha": "commit-new"}
    backend = GitHubImplementationMutationBackend(transport=transport)

    tree_sha = backend.create_tree(
        "owner/repo",
        "tree-base",
        (ImplementationMutationTreeEntry(path="src/example.py", blob_sha="blob-new"),),
    )
    commit_sha = backend.create_commit(
        "owner/repo",
        message="feat: approved change",
        tree_sha=tree_sha,
        parent_sha="base-sha",
    )

    assert tree_sha == "tree-new"
    assert commit_sha == "commit-new"
    assert transport.post_calls == [
        (
            tree_path,
            {
                "base_tree": "tree-base",
                "tree": [
                    {
                        "path": "src/example.py",
                        "mode": "100644",
                        "type": "blob",
                        "sha": "blob-new",
                    }
                ],
            },
        ),
        (
            commit_path,
            {
                "message": "feat: approved change",
                "tree": "tree-new",
                "parents": ["base-sha"],
            },
        ),
    ]


def test_backend_publishes_only_new_branch_ref_and_verifies_identity() -> None:
    transport = FakeMutationTransport()
    path = "/repos/owner/repo/git/refs"
    transport.post_responses[path] = {
        "ref": "refs/heads/agent/implementation/example",
        "object": {"sha": "commit-new"},
    }
    backend = GitHubImplementationMutationBackend(transport=transport)

    backend.create_branch(
        "owner/repo",
        "agent/implementation/example",
        "commit-new",
    )

    assert transport.post_calls == [
        (
            path,
            {
                "ref": "refs/heads/agent/implementation/example",
                "sha": "commit-new",
            },
        )
    ]


def test_backend_rejects_malformed_created_branch_identity() -> None:
    transport = FakeMutationTransport()
    path = "/repos/owner/repo/git/refs"
    transport.post_responses[path] = {
        "ref": "refs/heads/other",
        "object": {"sha": "commit-new"},
    }
    backend = GitHubImplementationMutationBackend(transport=transport)

    with pytest.raises(ImplementationGitHubMutationError, match="branch ref"):
        backend.create_branch(
            "owner/repo",
            "agent/implementation/example",
            "commit-new",
        )


def test_backend_preserves_404_branch_semantics_and_wraps_other_read_errors() -> None:
    transport = FakeMutationTransport()
    branch_path = "/repos/owner/repo/branches/missing"
    transport.get_responses[branch_path] = GitHubRestError("missing", status_code=404)
    backend = GitHubImplementationMutationBackend(transport=transport)

    assert backend.get_branch("owner/repo", "missing") is None

    transport.get_responses[branch_path] = GitHubRestError("boom", status_code=500)
    with pytest.raises(ImplementationGitHubMutationError, match="boom"):
        backend.get_branch("owner/repo", "missing")
