from __future__ import annotations

import base64

import pytest

from cisco_assessment.devtools.implementation.github_rest import (
    GitHubImplementationReadBackend,
    ImplementationGitHubRestError,
)
from cisco_assessment.devtools.pr_review.github_rest import GitHubRestError


class FakeTransport:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.json_calls: list[str] = []

    def get_json(self, path: str) -> object:
        self.json_calls.append(path)
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    def get_text(self, path: str, *, accept: str) -> str:
        raise AssertionError(f"unexpected text request: {path} {accept}")


def test_backend_observes_exact_branch_tree_and_blob_bytes() -> None:
    commit_sha = "a" * 40
    tree_sha = "b" * 40
    blob_sha = "c" * 40
    content = b"line one\r\nline two\n"
    transport = FakeTransport(
        {
            "/repos/owner/repo/branches/main": {
                "name": "main",
                "commit": {"sha": commit_sha},
            },
            f"/repos/owner/repo/git/commits/{commit_sha}": {
                "sha": commit_sha,
                "tree": {"sha": tree_sha},
            },
            f"/repos/owner/repo/git/trees/{tree_sha}?recursive=1": {
                "truncated": False,
                "tree": [
                    {
                        "path": "src/example.py",
                        "type": "blob",
                        "sha": blob_sha,
                        "size": len(content),
                    }
                ],
            },
            f"/repos/owner/repo/git/blobs/{blob_sha}": {
                "sha": blob_sha,
                "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
                "size": len(content),
            },
        }
    )
    backend = GitHubImplementationReadBackend(transport=transport)

    assert backend.get_branch("owner/repo", "main") == {
        "name": "main",
        "commit": {"sha": commit_sha},
    }
    assert tuple(backend.list_tree("owner/repo", commit_sha)) == (
        {
            "path": "src/example.py",
            "type": "blob",
            "sha": blob_sha,
            "size": len(content),
        },
    )
    assert backend.get_blob("owner/repo", blob_sha) == content
    assert transport.json_calls == [
        "/repos/owner/repo/branches/main",
        f"/repos/owner/repo/git/commits/{commit_sha}",
        f"/repos/owner/repo/git/trees/{tree_sha}?recursive=1",
        f"/repos/owner/repo/git/blobs/{blob_sha}",
    ]


def test_backend_returns_none_only_for_missing_branch() -> None:
    transport = FakeTransport(
        {
            "/repos/owner/repo/branches/missing": GitHubRestError(
                "not found",
                status_code=404,
            ),
        }
    )
    backend = GitHubImplementationReadBackend(transport=transport)

    assert backend.get_branch("owner/repo", "missing") is None


def test_backend_rejects_truncated_recursive_tree() -> None:
    commit_sha = "a" * 40
    tree_sha = "b" * 40
    transport = FakeTransport(
        {
            f"/repos/owner/repo/git/commits/{commit_sha}": {
                "sha": commit_sha,
                "tree": {"sha": tree_sha},
            },
            f"/repos/owner/repo/git/trees/{tree_sha}?recursive=1": {
                "truncated": True,
                "tree": [],
            },
        }
    )
    backend = GitHubImplementationReadBackend(transport=transport)

    with pytest.raises(ImplementationGitHubRestError, match="truncated"):
        backend.list_tree("owner/repo", commit_sha)


def test_backend_rejects_blob_identity_or_size_mismatch() -> None:
    blob_sha = "c" * 40
    transport = FakeTransport(
        {
            f"/repos/owner/repo/git/blobs/{blob_sha}": {
                "sha": "d" * 40,
                "encoding": "base64",
                "content": base64.b64encode(b"abc").decode("ascii"),
                "size": 3,
            },
        }
    )
    backend = GitHubImplementationReadBackend(transport=transport)

    with pytest.raises(ImplementationGitHubRestError, match="identity"):
        backend.get_blob("owner/repo", blob_sha)

    transport.responses[f"/repos/owner/repo/git/blobs/{blob_sha}"] = {
        "sha": blob_sha,
        "encoding": "base64",
        "content": base64.b64encode(b"abc").decode("ascii"),
        "size": 4,
    }
    with pytest.raises(ImplementationGitHubRestError, match="byte size"):
        backend.get_blob("owner/repo", blob_sha)
