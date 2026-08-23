"""Production GitHub backend for controlled Implementation Agent work-branch writes."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..pr_review.github_rest import GitHubHttpTransport, GitHubRestError, UrllibGitHubTransport
from .github_rest import GitHubImplementationReadBackend, ImplementationGitHubRestError
from .mutation import ImplementationMutationTreeEntry


class ImplementationGitHubMutationError(GitHubRestError):
    """Raised when a GitHub mutation operation cannot be completed safely."""


class GitHubImplementationMutationHttpTransport(GitHubHttpTransport, Protocol):
    """HTTP seam that adds POST only for the implementation mutation backend."""

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        """POST one JSON object to GitHub and decode the JSON response."""
        ...


class UrllibGitHubImplementationMutationTransport:
    """Minimal stdlib transport whose write surface is intentionally POST-only."""

    def __init__(
        self,
        *,
        token: str | None = None,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reader = UrllibGitHubTransport(
            token=token,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
        )

    def get_json(self, path: str) -> object:
        return self._reader.get_json(path)

    def get_text(self, path: str, *, accept: str) -> str:
        return self._reader.get_text(path, accept=accept)

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        if not path.startswith("/"):
            raise ImplementationGitHubMutationError("GitHub REST path must start with '/'")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "cisco-switch-assessment-implementation-agent-v0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        request = Request(
            f"{self._api_base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        if self._token:
            request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data: object = response.read()
        except HTTPError as exc:
            raise ImplementationGitHubMutationError(
                f"GitHub REST POST {path!r} failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise ImplementationGitHubMutationError(
                f"GitHub REST POST {path!r} failed: {exc.reason}"
            ) from exc
        if not isinstance(data, bytes):
            raise ImplementationGitHubMutationError(
                f"GitHub REST POST {path!r} returned non-bytes response data"
            )
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImplementationGitHubMutationError(
                f"GitHub returned invalid JSON for POST {path!r}"
            ) from exc
        return value


class GitHubImplementationMutationBackend:
    """GitHub Git Data backend that can publish only a newly-created work branch ref."""

    def __init__(
        self,
        transport: GitHubImplementationMutationHttpTransport | None = None,
    ) -> None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._transport = transport or UrllibGitHubImplementationMutationTransport(token=token)
        self._reader = GitHubImplementationReadBackend(transport=self._transport)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        try:
            return self._reader.get_branch(repository, branch)
        except ImplementationGitHubRestError as exc:
            raise _mutation_error(exc) from exc

    def list_tree(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        try:
            return self._reader.list_tree(repository, commit_sha)
        except ImplementationGitHubRestError as exc:
            raise _mutation_error(exc) from exc

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        try:
            return self._reader.get_blob(repository, blob_sha)
        except ImplementationGitHubRestError as exc:
            raise _mutation_error(exc) from exc

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        payload = _require_mapping(
            self._get_json(
                f"{_repo_path(repository)}/git/commits/{quote(commit_sha, safe='')}"
            ),
            "commit",
        )
        observed_sha = _required_string(payload, "sha", "commit")
        if observed_sha != commit_sha:
            raise ImplementationGitHubMutationError(
                "GitHub commit identity does not match requested implementation base"
            )
        tree_value = payload.get("tree")
        if not isinstance(tree_value, Mapping):
            raise ImplementationGitHubMutationError("GitHub commit payload has no tree object")
        return _required_string(cast(Mapping[str, object], tree_value), "sha", "commit tree")

    def create_utf8_blob(self, repository: str, content: str) -> str:
        payload = _require_mapping(
            self._post_json(
                f"{_repo_path(repository)}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            ),
            "created blob",
        )
        return _required_string(payload, "sha", "created blob")

    def create_tree(
        self,
        repository: str,
        base_tree_sha: str,
        entries: Sequence[ImplementationMutationTreeEntry],
    ) -> str:
        tree_items: list[object] = []
        for entry in entries:
            tree_items.append(
                {
                    "path": entry.path,
                    "mode": entry.mode,
                    "type": "blob",
                    "sha": entry.blob_sha,
                }
            )
        payload = _require_mapping(
            self._post_json(
                f"{_repo_path(repository)}/git/trees",
                {"base_tree": base_tree_sha, "tree": tree_items},
            ),
            "created tree",
        )
        return _required_string(payload, "sha", "created tree")

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str:
        payload = _require_mapping(
            self._post_json(
                f"{_repo_path(repository)}/git/commits",
                {"message": message, "tree": tree_sha, "parents": [parent_sha]},
            ),
            "created commit",
        )
        return _required_string(payload, "sha", "created commit")

    def create_branch(self, repository: str, branch: str, commit_sha: str) -> None:
        payload = _require_mapping(
            self._post_json(
                f"{_repo_path(repository)}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": commit_sha},
            ),
            "created branch ref",
        )
        observed_ref = _required_string(payload, "ref", "created branch ref")
        observed_sha_value = payload.get("object")
        if not isinstance(observed_sha_value, Mapping):
            raise ImplementationGitHubMutationError(
                "GitHub created branch ref has no object metadata"
            )
        observed_sha = _required_string(
            cast(Mapping[str, object], observed_sha_value), "sha", "created branch ref object"
        )
        if observed_ref != f"refs/heads/{branch}" or observed_sha != commit_sha:
            raise ImplementationGitHubMutationError(
                "GitHub created branch ref does not match requested branch identity"
            )

    def _get_json(self, path: str) -> object:
        try:
            return self._transport.get_json(path)
        except GitHubRestError as exc:
            raise _mutation_error(exc) from exc

    def _post_json(self, path: str, payload: Mapping[str, object]) -> object:
        try:
            return self._transport.post_json(path, payload)
        except GitHubRestError as exc:
            raise _mutation_error(exc) from exc


def _mutation_error(exc: GitHubRestError) -> ImplementationGitHubMutationError:
    return ImplementationGitHubMutationError(str(exc), status_code=exc.status_code)


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationGitHubMutationError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationGitHubMutationError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _required_string(payload: Mapping[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ImplementationGitHubMutationError(
            f"GitHub {context} field {key!r} must be a non-empty string"
        )
    return value
