"""Production GitHub backend for controlled Implementation Agent Draft PR creation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..pr_review.github_rest import GitHubHttpTransport, GitHubRestError, UrllibGitHubTransport
from .draft_pr import WORK_BRANCH_PREFIX
from .github_rest import GitHubImplementationReadBackend, ImplementationGitHubRestError


class ImplementationGitHubDraftPrError(GitHubRestError):
    """Raised when controlled GitHub Draft PR evidence or creation fails."""


class GitHubImplementationDraftPrHttpTransport(GitHubHttpTransport, Protocol):
    """HTTP seam that adds only Draft PR POST to the existing read surface."""

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        """POST one JSON object and decode the response."""
        ...


class UrllibGitHubImplementationDraftPrTransport:
    """Minimal stdlib transport restricted to GitHub reads and JSON POST."""

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
            raise ImplementationGitHubDraftPrError("GitHub REST path must start with '/'")
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
            raise ImplementationGitHubDraftPrError(
                f"GitHub REST POST {path!r} failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise ImplementationGitHubDraftPrError(
                f"GitHub REST POST {path!r} failed: {exc.reason}"
            ) from exc
        if not isinstance(data, bytes):
            raise ImplementationGitHubDraftPrError(
                f"GitHub REST POST {path!r} returned non-bytes response data"
            )
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImplementationGitHubDraftPrError(
                f"GitHub returned invalid JSON for POST {path!r}"
            ) from exc
        return value


class GitHubImplementationDraftPrBackend:
    """GitHub implementation of the project-owned Draft PR preparation contract."""

    def __init__(
        self,
        transport: GitHubImplementationDraftPrHttpTransport | None = None,
    ) -> None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._transport = transport or UrllibGitHubImplementationDraftPrTransport(token=token)
        self._reader = GitHubImplementationReadBackend(transport=self._transport)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        try:
            return self._reader.get_branch(repository, branch)
        except ImplementationGitHubRestError as exc:
            raise _draft_pr_error(exc) from exc

    def list_open_pull_requests(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> Sequence[Mapping[str, object]]:
        _validate_head_branch(head_branch)
        owner, _, _ = _repo_parts(repository)
        payload = self._get_json(
            f"{_repo_path(repository)}/pulls?state=open"
            f"&base={quote(base_branch, safe='')}"
            f"&head={quote(f'{owner}:{head_branch}', safe='')}"
            "&per_page=100&page=1"
        )
        return _mapping_array(payload, "open pull requests")

    def create_draft_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
    ) -> Mapping[str, object]:
        _validate_head_branch(head_branch)
        payload = _require_mapping(
            self._post_json(
                f"{_repo_path(repository)}/pulls",
                {
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                    "draft": True,
                    "maintainer_can_modify": False,
                },
            ),
            "created pull request",
        )
        return payload

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        if pr_number <= 0:
            raise ImplementationGitHubDraftPrError("pull request number must be positive")
        return _require_mapping(
            self._get_json(f"{_repo_path(repository)}/pulls/{pr_number}"),
            "pull request",
        )

    def _get_json(self, path: str) -> object:
        try:
            return self._transport.get_json(path)
        except GitHubRestError as exc:
            raise _draft_pr_error(exc) from exc

    def _post_json(self, path: str, payload: Mapping[str, object]) -> object:
        if not path.endswith("/pulls"):
            raise ImplementationGitHubDraftPrError(
                "Draft PR backend POST surface is restricted to pull request creation"
            )
        try:
            return self._transport.post_json(path, payload)
        except GitHubRestError as exc:
            raise _draft_pr_error(exc) from exc


def _validate_head_branch(head_branch: str) -> None:
    if not head_branch.startswith(WORK_BRANCH_PREFIX):
        raise ImplementationGitHubDraftPrError(
            f"Draft PR backend only permits {WORK_BRANCH_PREFIX!r} branches"
        )


def _repo_parts(repository: str) -> tuple[str, str, str]:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationGitHubDraftPrError("repository must use owner/name form")
    return owner, separator, name


def _repo_path(repository: str) -> str:
    owner, _, name = _repo_parts(repository)
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _draft_pr_error(
    exc: GitHubRestError | ImplementationGitHubRestError,
) -> ImplementationGitHubDraftPrError:
    return ImplementationGitHubDraftPrError(str(exc), status_code=exc.status_code)


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationGitHubDraftPrError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _mapping_array(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ImplementationGitHubDraftPrError(f"GitHub {label} payload must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ImplementationGitHubDraftPrError(f"GitHub {label} entries must be objects")
        result.append(cast(Mapping[str, object], item))
    return tuple(result)
