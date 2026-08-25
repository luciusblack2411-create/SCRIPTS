"""Dedicated productive GitHub backend for Draft PR amendment."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..pr_review.github_rest import GitHubRestError, UrllibGitHubTransport
from .draft_pr_amendment import ImplementationDraftPrAmendmentError
from .github_mutation import GitHubImplementationMutationBackend
from .mutation import ImplementationMutationTreeEntry


class UrllibGitHubDraftPrAmendmentTransport(UrllibGitHubTransport):
    """Concrete GET, Git-object POST, and non-force ref PATCH transport."""

    def __init__(
        self,
        *,
        token: str,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            token=token,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
        )
        self._amendment_token = token
        self._amendment_api_base_url = api_base_url.rstrip("/")
        self._amendment_timeout_seconds = timeout_seconds

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        return self._json_request("POST", path, payload)

    def patch_ref(self, path: str, sha: str) -> object:
        if not path.startswith("/repos/") or "/git/refs/heads/" not in path:
            raise ImplementationDraftPrAmendmentError(
                "PATCH target must be an exact heads ref"
            )
        return self._json_request("PATCH", path, {"sha": sha, "force": False})

    def _json_request(
        self, method: str, path: str, payload: Mapping[str, object]
    ) -> object:
        if not path.startswith("/"):
            raise ImplementationDraftPrAmendmentError(
                "GitHub REST path must start with '/'"
            )
        request = Request(
            f"{self._amendment_api_base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "cisco-switch-assessment-draft-pr-amendment-v1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method=method,
        )
        request.add_unredirected_header(
            "Authorization", f"Bearer {self._amendment_token}"
        )
        try:
            with urlopen(
                request, timeout=self._amendment_timeout_seconds
            ) as response:
                data: object = response.read()
        except HTTPError as exc:
            raise ImplementationDraftPrAmendmentError(
                f"GitHub REST {method} failed with HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise ImplementationDraftPrAmendmentError(
                f"GitHub REST {method} failed: {exc.reason}"
            ) from exc
        if not isinstance(data, bytes):
            raise ImplementationDraftPrAmendmentError(
                "GitHub amendment response must be bytes"
            )
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImplementationDraftPrAmendmentError(
                "GitHub returned invalid JSON"
            ) from exc


class GitHubImplementationDraftPrAmendmentBackend:
    """Backend whose only ref mutation is an exact, non-force work-head PATCH."""

    def __init__(self, transport: UrllibGitHubDraftPrAmendmentTransport) -> None:
        self._transport = transport
        self._objects = GitHubImplementationMutationBackend(transport=transport)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        return self._objects.get_branch(repository, branch)

    def get_pull_request(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object] | None:
        try:
            value = self._transport.get_json(f"{_repo(repository)}/pulls/{pr_number}")
        except GitHubRestError as exc:
            if exc.status_code == 404:
                return None
            raise ImplementationDraftPrAmendmentError(str(exc)) from exc
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError(
                "pull request payload must be an object"
            )
        return cast(Mapping[str, object], value)

    def list_tree(
        self, repository: str, commit_sha: str
    ) -> Sequence[Mapping[str, object]]:
        return self._objects.list_tree(repository, commit_sha)

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        return self._objects.get_blob(repository, blob_sha)

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        value = self._transport.get_json(
            f"{_repo(repository)}/git/commits/{quote(commit_sha, safe='')}"
        )
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError(
                "commit payload must be an object"
            )
        return cast(Mapping[str, object], value)

    def create_utf8_blob(self, repository: str, content: str) -> str:
        return self._objects.create_utf8_blob(repository, content)

    def create_tree(
        self,
        repository: str,
        base_tree_sha: str,
        entries: Sequence[ImplementationMutationTreeEntry],
    ) -> str:
        return self._objects.create_tree(repository, base_tree_sha, entries)

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str:
        return self._objects.create_commit(
            repository,
            message=message,
            tree_sha=tree_sha,
            parent_sha=parent_sha,
        )

    def update_work_branch(
        self,
        repository: str,
        branch: str,
        old_sha: str,
        new_sha: str,
    ) -> None:
        current = self.get_branch(repository, branch)
        if current is None:
            raise ImplementationDraftPrAmendmentError(
                "work-branch ref disappeared before PATCH"
            )
        commit = current.get("commit")
        if not isinstance(commit, Mapping) or commit.get("sha") != old_sha:
            raise ImplementationDraftPrAmendmentError(
                "work-branch ref raced before PATCH"
            )
        value = self._transport.patch_ref(
            f"{_repo(repository)}/git/refs/heads/{quote(branch, safe='')}",
            new_sha,
        )
        if not isinstance(value, Mapping):
            raise ImplementationDraftPrAmendmentError(
                "updated ref payload must be an object"
            )
        if value.get("ref") != f"refs/heads/{branch}":
            raise ImplementationDraftPrAmendmentError("updated ref identity mismatch")
        obj = value.get("object")
        if not isinstance(obj, Mapping) or obj.get("sha") != new_sha:
            raise ImplementationDraftPrAmendmentError("updated ref SHA mismatch")


def _repo(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationDraftPrAmendmentError(
            "repository must use owner/name form"
        )
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
