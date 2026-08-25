"""Productive GitHub backend for exact, non-force Draft PR amendments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from urllib.parse import quote

from ..pr_review.github_rest import GitHubHttpTransport, GitHubRestError
from .draft_pr_amendment import ImplementationDraftPrAmendmentBackend, ImplementationDraftPrAmendmentError
from .github_mutation import GitHubImplementationMutationBackend, GitHubImplementationMutationHttpTransport
from .mutation import ImplementationMutationTreeEntry


class GitHubDraftPrAmendmentTransport(GitHubImplementationMutationHttpTransport, Protocol):
    def patch_json(self, path: str, payload: Mapping[str, object]) -> object: ...


class GitHubImplementationDraftPrAmendmentBackend(ImplementationDraftPrAmendmentBackend):
    """Existing-ref authority whose public API has no force parameter."""

    def __init__(self, transport: GitHubDraftPrAmendmentTransport) -> None:
        self._transport = transport
        self._objects = GitHubImplementationMutationBackend(transport=transport)

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None:
        try:
            value = self._transport.get_json(f"{_repo(repository)}/pulls/{pr_number}")
        except GitHubRestError as exc:
            if exc.status_code == 404:
                return None
            raise ImplementationDraftPrAmendmentError(str(exc)) from exc
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError("GitHub pull request payload must be an object")
        return cast(Mapping[str, object], value)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        return self._objects.get_branch(repository, branch)

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        return self._objects.list_tree(repository, commit_sha)

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        value = self._transport.get_json(f"{_repo(repository)}/git/commits/{quote(commit_sha, safe='')}")
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError("GitHub commit payload must be an object")
        return cast(Mapping[str, object], value)

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        return self._objects.get_commit_tree_sha(repository, commit_sha)

    def create_utf8_blob(self, repository: str, content: str) -> str:
        return self._objects.create_utf8_blob(repository, content)

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        return self._objects.get_blob(repository, blob_sha)

    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[ImplementationMutationTreeEntry]) -> str:
        return self._objects.create_tree(repository, base_tree_sha, entries)

    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str:
        return self._objects.create_commit(repository, message=message, tree_sha=tree_sha, parent_sha=parent_sha)

    def advance_branch(self, repository: str, branch: str, *, old_sha: str, new_sha: str) -> None:
        current = self.get_branch(repository, branch)
        if current is None or not isinstance(current.get("commit"), Mapping) or current["commit"].get("sha") != old_sha:
            raise ImplementationDraftPrAmendmentError("work branch lost compare-and-swap precondition")
        path = f"{_repo(repository)}/git/refs/heads/{quote(branch, safe='')}"
        try:
            value = self._transport.patch_json(path, {"sha": new_sha, "force": False})
        except GitHubRestError as exc:
            raise ImplementationDraftPrAmendmentError("non-force ref update failed closed") from exc
        if not isinstance(value, Mapping) or value.get("ref") != f"refs/heads/{branch}" or not isinstance(value.get("object"), Mapping) or value["object"].get("sha") != new_sha:
            raise ImplementationDraftPrAmendmentError("updated GitHub ref identity is inconsistent")


def _repo(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationDraftPrAmendmentError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
