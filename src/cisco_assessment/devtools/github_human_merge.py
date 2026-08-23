"""Production GitHub backend restricted to one protected pull-request merge."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .pr_review.github_rest import GitHubRestError, UrllibGitHubTransport


class GitHubHumanMergeError(GitHubRestError):
    """Raised when GitHub human-merge evidence or mutation fails."""


class GitHubHumanMergeHttpTransport(Protocol):
    """HTTP seam exposing reads plus one merge-specific PUT."""

    def get_json(self, path: str) -> object:
        """GET one GitHub API resource."""
        ...

    def put_merge(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        merge_method: Literal["merge"],
    ) -> object:
        """PUT exactly one pull-request merge request."""
        ...


class UrllibGitHubHumanMergeTransport:
    """Minimal transport with explicit token injection and no generic write surface."""

    def __init__(
        self,
        *,
        token: str,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not token.strip():
            raise GitHubHumanMergeError("Human-merge token must not be empty")
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

    def put_merge(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        merge_method: Literal["merge"],
    ) -> object:
        if pr_number <= 0:
            raise GitHubHumanMergeError("pull request number must be positive")
        if not expected_head_sha:
            raise GitHubHumanMergeError("expected head SHA must not be empty")
        body = json.dumps(
            {"sha": expected_head_sha, "merge_method": merge_method},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            f"{self._api_base_url}{_repo_path(repository)}/pulls/{pr_number}/merge",
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "cisco-switch-assessment-human-merge-v0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="PUT",
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data: object = response.read()
        except HTTPError as exc:
            raise GitHubHumanMergeError(
                f"GitHub merge failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise GitHubHumanMergeError(f"GitHub merge failed: {exc.reason}") from exc
        if not isinstance(data, bytes):
            raise GitHubHumanMergeError("GitHub merge returned non-bytes response data")
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubHumanMergeError("GitHub merge returned invalid JSON") from exc


class GitHubHumanMergeBackend:
    """GitHub implementation of the controlled human merge backend contract."""

    def __init__(
        self,
        transport: GitHubHumanMergeHttpTransport | None = None,
        *,
        token: str | None = None,
    ) -> None:
        if transport is None:
            if token is None:
                raise GitHubHumanMergeError(
                    "Human-merge backend requires an explicitly injected token"
                )
            transport = UrllibGitHubHumanMergeTransport(token=token)
        self._transport = transport

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        if pr_number <= 0:
            raise GitHubHumanMergeError("pull request number must be positive")
        return _require_mapping(
            self._get_json(f"{_repo_path(repository)}/pulls/{pr_number}"),
            "pull request",
        )

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        if not branch:
            raise GitHubHumanMergeError("branch must not be empty")
        path = f"{_repo_path(repository)}/branches/{quote(branch, safe='')}"
        try:
            return _require_mapping(self._get_json(path), "branch")
        except GitHubHumanMergeError as exc:
            if exc.status_code == 404:
                return None
            raise

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        if not commit_sha:
            raise GitHubHumanMergeError("commit SHA must not be empty")
        return _require_mapping(
            self._get_json(f"{_repo_path(repository)}/commits/{quote(commit_sha, safe='')}"),
            "commit",
        )

    def merge_pull_request(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        merge_method: Literal["merge"],
    ) -> Mapping[str, object]:
        try:
            payload = self._transport.put_merge(
                repository,
                pr_number,
                expected_head_sha=expected_head_sha,
                merge_method=merge_method,
            )
        except GitHubRestError as exc:
            raise GitHubHumanMergeError(str(exc), status_code=exc.status_code) from exc
        return _require_mapping(payload, "merge response")

    def _get_json(self, path: str) -> object:
        try:
            return self._transport.get_json(path)
        except GitHubRestError as exc:
            raise GitHubHumanMergeError(str(exc), status_code=exc.status_code) from exc


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise GitHubHumanMergeError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GitHubHumanMergeError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)
