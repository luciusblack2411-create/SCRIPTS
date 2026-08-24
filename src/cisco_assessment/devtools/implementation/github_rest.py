"""Production read-only GitHub REST backend for Implementation Agent v0.1."""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

from ..pr_review.github_rest import GitHubHttpTransport, GitHubRestError, UrllibGitHubTransport


class ImplementationGitHubRestError(RuntimeError):
    """Raised when GitHub implementation evidence cannot be acquired safely."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubImplementationReadBackend:
    """GitHub REST backend for implementation context and exact source blobs."""

    def __init__(self, transport: GitHubHttpTransport | None = None) -> None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._transport = transport or UrllibGitHubTransport(token=token)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        path = f"{_repo_path(repository)}/branches/{quote(branch, safe='')}"
        try:
            return _require_mapping(self._transport.get_json(path), "branch")
        except GitHubRestError as exc:
            if exc.status_code == 404:
                return None
            raise _implementation_error(exc) from exc

    def list_tree(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        repo_path = _repo_path(repository)
        encoded_commit = quote(commit_sha, safe="")
        commit = self._get_mapping(
            f"{repo_path}/git/commits/{encoded_commit}",
            "commit",
        )
        observed_commit_sha = _required_string(commit, "sha", context="commit")
        if observed_commit_sha != commit_sha:
            raise ImplementationGitHubRestError(
                "GitHub commit identity does not match the requested implementation base SHA"
            )

        tree_value = commit.get("tree")
        if not isinstance(tree_value, Mapping):
            raise ImplementationGitHubRestError("GitHub commit payload has no tree object")
        tree = cast(Mapping[str, object], tree_value)
        tree_sha = _required_string(tree, "sha", context="commit tree")
        payload = self._get_mapping(
            f"{repo_path}/git/trees/{quote(tree_sha, safe='')}?recursive=1",
            "recursive tree",
        )
        truncated = payload.get("truncated")
        if not isinstance(truncated, bool):
            raise ImplementationGitHubRestError(
                "GitHub recursive tree payload has invalid truncated metadata"
            )
        if truncated:
            raise ImplementationGitHubRestError(
                "GitHub recursive tree is truncated; implementation context would be incomplete"
            )
        return _mapping_array(payload.get("tree"), "recursive tree entries")

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        payload = self._get_mapping(
            f"{_repo_path(repository)}/git/blobs/{quote(blob_sha, safe='')}",
            "blob",
        )
        observed_sha = _required_string(payload, "sha", context="blob")
        if observed_sha != blob_sha:
            raise ImplementationGitHubRestError(
                "GitHub blob identity does not match the requested source blob SHA"
            )
        encoding = _required_string(payload, "encoding", context="blob")
        if encoding != "base64":
            raise ImplementationGitHubRestError(
                f"GitHub blob encoding {encoding!r} is not supported"
            )
        encoded_content = _required_string(payload, "content", context="blob")
        compact_content = "".join(encoded_content.split())
        try:
            content = base64.b64decode(compact_content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImplementationGitHubRestError("GitHub blob content is not valid base64") from exc

        size = _required_int(payload, "size", context="blob")
        if len(content) != size:
            raise ImplementationGitHubRestError(
                "GitHub blob decoded byte size does not match blob metadata"
            )
        return content

    def _get_mapping(self, path: str, label: str) -> Mapping[str, object]:
        try:
            return _require_mapping(self._transport.get_json(path), label)
        except GitHubRestError as exc:
            raise _implementation_error(exc) from exc


def _implementation_error(exc: GitHubRestError) -> ImplementationGitHubRestError:
    return ImplementationGitHubRestError(str(exc), status_code=exc.status_code)


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationGitHubRestError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationGitHubRestError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _mapping_array(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ImplementationGitHubRestError(f"GitHub {label} payload must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ImplementationGitHubRestError(f"GitHub {label} entries must be objects")
        result.append(cast(Mapping[str, object], item))
    return tuple(result)


def _required_string(payload: Mapping[str, object], key: str, *, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ImplementationGitHubRestError(f"GitHub {context} field {key!r} must be a string")
    return value


def _required_int(payload: Mapping[str, object], key: str, *, context: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ImplementationGitHubRestError(
            f"GitHub {context} field {key!r} must be a non-negative integer"
        )
    return value
