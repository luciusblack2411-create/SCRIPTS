from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.implementation import (
    GitHubImplementationCiBackend,
    ImplementationGitHubCiError,
)


class FakeCiTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Mapping[str, object]]] = []
        self.responses: dict[str, object] = {}

    def get_json(self, path: str) -> object:
        return self.responses[path]

    def get_text(self, path: str, *, accept: str) -> str:
        del path, accept
        raise AssertionError("text endpoint is not used by CI backend")

    def post_no_content(self, path: str, payload: Mapping[str, object]) -> None:
        self.posts.append((path, payload))


def test_dispatch_is_restricted_to_exact_workflow_and_ref() -> None:
    transport = FakeCiTransport()
    backend = GitHubImplementationCiBackend(transport=transport)

    backend.dispatch_workflow("owner/repo", "ci.yml", "agent/implementation/example")

    assert transport.posts == [
        (
            "/repos/owner/repo/actions/workflows/ci.yml/dispatches",
            {"ref": "agent/implementation/example"},
        )
    ]


def test_list_runs_uses_exact_dispatch_branch_and_head_filters() -> None:
    transport = FakeCiTransport()
    path = (
        "/repos/owner/repo/actions/workflows/ci.yml/runs"
        "?event=workflow_dispatch&branch=agent%2Fimplementation%2Fexample&head_sha=abc123"
        "&per_page=100&page=1"
    )
    transport.responses[path] = {
        "workflow_runs": [
            {
                "id": 101,
                "event": "workflow_dispatch",
                "head_branch": "agent/implementation/example",
                "head_sha": "abc123",
                "status": "completed",
                "conclusion": "success",
            }
        ]
    }
    backend = GitHubImplementationCiBackend(transport=transport)

    runs = backend.list_workflow_runs(
        "owner/repo",
        "ci.yml",
        branch="agent/implementation/example",
        head_sha="abc123",
    )

    assert len(runs) == 1
    assert runs[0]["id"] == 101


def test_list_jobs_preserves_all_job_evidence() -> None:
    transport = FakeCiTransport()
    path = "/repos/owner/repo/actions/runs/101/jobs?per_page=100&page=1"
    transport.responses[path] = {
        "jobs": [
            {"id": 11, "name": "quality (3.11)", "status": "completed", "conclusion": "success"},
            {"id": 12, "name": "quality (3.12)", "status": "completed", "conclusion": "success"},
        ]
    }
    backend = GitHubImplementationCiBackend(transport=transport)

    jobs = backend.list_workflow_jobs("owner/repo", 101)

    assert tuple(job["id"] for job in jobs) == (11, 12)


def test_get_branch_reuses_strict_read_backend() -> None:
    transport = FakeCiTransport()
    transport.responses["/repos/owner/repo/branches/main"] = {"commit": {"sha": "base-123"}}
    backend = GitHubImplementationCiBackend(transport=transport)

    assert backend.get_branch("owner/repo", "main") == {"commit": {"sha": "base-123"}}


def test_malformed_workflow_runs_payload_is_rejected() -> None:
    transport = FakeCiTransport()
    path = (
        "/repos/owner/repo/actions/workflows/ci.yml/runs"
        "?event=workflow_dispatch&branch=agent%2Fimplementation%2Fexample&head_sha=abc123"
        "&per_page=100&page=1"
    )
    transport.responses[path] = {"workflow_runs": "not-an-array"}
    backend = GitHubImplementationCiBackend(transport=transport)

    with pytest.raises(ImplementationGitHubCiError, match="array"):
        backend.list_workflow_runs(
            "owner/repo",
            "ci.yml",
            branch="agent/implementation/example",
            head_sha="abc123",
        )
