from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.pr_review.github import (
    GitHubContextError,
    GitHubReadAdapter,
    PullRequestContext,
)


class FakeGitHubReadBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.pull_request: Mapping[str, object] = {
            "number": 36,
            "title": "feat(devtools): add PR review context",
            "body": "Read-only GitHub context.",
            "state": "open",
            "draft": False,
            "mergeable": True,
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        }
        self.branch: Mapping[str, object] | None = {
            "name": "main",
            "commit": {"sha": "base-sha"},
        }
        self.files: Sequence[Mapping[str, object]] = (
            {
                "filename": "src/cisco_assessment/devtools/pr_review/github.py",
                "status": "added",
                "additions": 10,
                "deletions": 0,
                "changes": 10,
                "previous_filename": None,
            },
        )
        self.commits: Sequence[Mapping[str, object]] = (
            {
                "sha": "commit-1",
                "commit": {"message": "feat(devtools): add context"},
            },
        )
        self.diff_text = "diff --git a/a b/a\n+exact diff text\n"
        self.workflow_runs: Sequence[Mapping[str, object]] = (
            {
                "id": 137,
                "name": "CI",
                "head_sha": "head-sha",
                "status": "completed",
                "conclusion": "success",
            },
        )

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        self.calls.append(f"pr:{repository}:{pr_number}")
        return self.pull_request

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        self.calls.append(f"branch:{repository}:{branch}")
        return self.branch

    def list_pull_request_files(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append(f"files:{repository}:{pr_number}")
        return self.files

    def list_pull_request_commits(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append(f"commits:{repository}:{pr_number}")
        return self.commits

    def get_pull_request_diff(self, repository: str, pr_number: int) -> str:
        self.calls.append(f"diff:{repository}:{pr_number}")
        return self.diff_text

    def list_commit_workflow_runs(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append(f"runs:{repository}:{commit_sha}")
        return self.workflow_runs


def test_load_pull_request_context_preserves_read_data_and_order() -> None:
    backend = FakeGitHubReadBackend()
    adapter = GitHubReadAdapter(backend)

    context = adapter.load_pull_request_context("owner/repo", 36)

    assert context.base_branch == "main"
    assert context.base_sha == "base-sha"
    assert context.base_branch_head_sha == "base-sha"
    assert context.head_branch == "feature"
    assert context.head_sha == "head-sha"
    assert context.diff_text == backend.diff_text
    assert [item.path for item in context.changed_files] == [
        "src/cisco_assessment/devtools/pr_review/github.py"
    ]
    assert [item.sha for item in context.commits] == ["commit-1"]
    assert [run.run_id for run in context.workflow_runs] == [137]
    assert backend.calls == [
        "pr:owner/repo:36",
        "branch:owner/repo:main",
        "files:owner/repo:36",
        "commits:owner/repo:36",
        "diff:owner/repo:36",
        "runs:owner/repo:head-sha",
    ]


def test_context_preserves_advanced_current_base_branch_head() -> None:
    backend = FakeGitHubReadBackend()
    backend.branch = {"name": "main", "commit": {"sha": "new-main-head"}}

    context = GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)

    assert context.base_sha == "base-sha"
    assert context.base_branch_head_sha == "new-main-head"


def test_context_allows_unavailable_current_base_branch_head() -> None:
    backend = FakeGitHubReadBackend()
    backend.branch = None

    context = GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)

    assert context.base_branch_head_sha is None


def test_context_rejects_malformed_observed_branch_head() -> None:
    backend = FakeGitHubReadBackend()
    backend.branch = {"name": "main", "commit": {}}

    with pytest.raises(GitHubContextError, match="field 'sha' must be a string"):
        GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)


def test_context_rejects_workflow_run_from_stale_head() -> None:
    backend = FakeGitHubReadBackend()
    backend.workflow_runs = (
        {
            "id": 138,
            "name": "CI",
            "head_sha": "stale-sha",
            "status": "completed",
            "conclusion": "success",
        },
    )

    with pytest.raises(GitHubContextError, match="workflow run head SHA mismatch"):
        GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)


def test_context_rejects_pull_request_number_mismatch() -> None:
    backend = FakeGitHubReadBackend()
    backend.pull_request = {**backend.pull_request, "number": 99}

    with pytest.raises(GitHubContextError, match="pull-request number mismatch"):
        GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)


def test_context_rejects_malformed_required_github_field() -> None:
    backend = FakeGitHubReadBackend()
    backend.pull_request = {**backend.pull_request, "base": "main"}

    with pytest.raises(GitHubContextError, match="field 'base' must be an object"):
        GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)


def test_context_requires_closed_repository_name_form() -> None:
    backend = FakeGitHubReadBackend()

    with pytest.raises(GitHubContextError, match="owner/name"):
        GitHubReadAdapter(backend).load_pull_request_context("https://github.com/owner/repo", 36)

    assert backend.calls == []


def test_pull_request_context_is_frozen_and_forbids_extra_fields() -> None:
    backend = FakeGitHubReadBackend()
    context = GitHubReadAdapter(backend).load_pull_request_context("owner/repo", 36)

    with pytest.raises(ValidationError):
        context.__setattr__("title", "changed")

    with pytest.raises(ValidationError):
        PullRequestContext.model_validate(
            {
                **context.model_dump(),
                "unexpected": True,
            }
        )
