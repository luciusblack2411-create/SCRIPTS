"""Dedicated GitHub transport/backend for existing Draft PR amendment authority."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..pr_review.github_rest import UrllibGitHubTransport
from .draft_pr_amendment import ImplementationDraftPrAmendmentError
from .github_mutation import (
    GitHubImplementationMutationBackend,
    UrllibGitHubImplementationMutationTransport,
)
from .mutation import ImplementationMutationTreeEntry


class UrllibGitHubDraftPrAmendmentTransport(UrllibGitHubImplementationMutationTransport):
    """Transport whose only PATCH operation always performs a non-force ref update."""

    def patch_ref_fast_forward(self, path: str, commit_sha: str) -> None:
        body = json.dumps({"sha": commit_sha, "force": False}, separators=(",", ":")).encode()
        request = Request(f"{self._api_base_url}{path}", data=body, headers={"Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "cisco-switch-assessment-implementation-agent-v0.1", "X-GitHub-Api-Version": "2022-11-28"}, method="PATCH")
        if self._token:
            request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response.read()
        except HTTPError as exc:
            raise ImplementationDraftPrAmendmentError(f"GitHub ref PATCH failed with HTTP {exc.code}") from exc
        except URLError as exc:
            raise ImplementationDraftPrAmendmentError(f"GitHub ref PATCH failed: {exc.reason}") from exc


class GitHubImplementationDraftPrAmendmentBackend:
    def __init__(self, *, token: str) -> None:
        self._transport = UrllibGitHubDraftPrAmendmentTransport(token=token)
        self._reader = UrllibGitHubTransport(token=token)
        self._objects = GitHubImplementationMutationBackend(transport=self._transport)

    def _repo(self, repository: str) -> str:
        owner, separator, name = repository.partition("/")
        if separator != "/" or not owner or not name or "/" in name:
            raise ImplementationDraftPrAmendmentError("repository must use owner/name form")
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None:
        try:
            value = self._reader.get_json(f"{self._repo(repository)}/pulls/{pr_number}")
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return None
            raise ImplementationDraftPrAmendmentError(str(exc)) from exc
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError("GitHub PR payload must be an object")
        return cast(Mapping[str, object], value)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        return self._objects.get_branch(repository, branch)

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        return self._objects.list_tree(repository, commit_sha)

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        return self._objects.get_commit_tree_sha(repository, commit_sha)

    def create_utf8_blob(self, repository: str, content: str) -> str:
        return self._objects.create_utf8_blob(repository, content)

    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[ImplementationMutationTreeEntry]) -> str:
        return self._objects.create_tree(repository, base_tree_sha, entries)

    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str:
        return self._objects.create_commit(repository, message=message, tree_sha=tree_sha, parent_sha=parent_sha)

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        value = self._reader.get_json(f"{self._repo(repository)}/git/commits/{quote(commit_sha, safe='')}")
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError("GitHub commit payload must be an object")
        return cast(Mapping[str, object], value)

    def update_existing_ref_fast_forward(self, repository: str, branch: str, commit_sha: str) -> None:
        self._transport.patch_ref_fast_forward(f"{self._repo(repository)}/git/refs/heads/{quote(branch, safe='')}", commit_sha)

    def dispatch_amendment_ci(self, repository: str, workflow_file: str, branch: str) -> None:
        if workflow_file != "ci.yml":
            raise ImplementationDraftPrAmendmentError("amendment backend permits only ci.yml")
        self._transport.post_json(f"{self._repo(repository)}/actions/workflows/ci.yml/dispatches", {"ref": branch})

    def list_amendment_ci_runs(self, repository: str, workflow_file: str, *, branch: str, head_sha: str) -> Sequence[Mapping[str, object]]:
        if workflow_file != "ci.yml":
            raise ImplementationDraftPrAmendmentError("amendment backend permits only ci.yml")
        value = self._reader.get_json(f"{self._repo(repository)}/actions/workflows/ci.yml/runs?event=workflow_dispatch&branch={quote(branch, safe='')}&head_sha={quote(head_sha, safe='')}&per_page=100&page=1")
        if not isinstance(value, Mapping) or not isinstance(value.get("workflow_runs"), Sequence):
            raise ImplementationDraftPrAmendmentError("invalid amendment CI runs payload")
        return tuple(cast(Sequence[Mapping[str, object]], value["workflow_runs"]))

    def list_amendment_ci_jobs(self, repository: str, run_id: int) -> Sequence[Mapping[str, object]]:
        value = self._reader.get_json(f"{self._repo(repository)}/actions/runs/{run_id}/jobs?per_page=100&page=1")
        if not isinstance(value, Mapping) or not isinstance(value.get("jobs"), Sequence):
            raise ImplementationDraftPrAmendmentError("invalid amendment CI jobs payload")
        return tuple(cast(Sequence[Mapping[str, object]], value["jobs"]))
