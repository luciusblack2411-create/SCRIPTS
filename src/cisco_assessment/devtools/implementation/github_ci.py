"""Production GitHub Actions backend for Implementation Agent CI validation."""

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


class ImplementationGitHubCiError(GitHubRestError):
    """Raised when exact GitHub Actions CI evidence cannot be acquired or dispatched."""


class GitHubImplementationCiHttpTransport(GitHubHttpTransport, Protocol):
    """HTTP seam that adds only workflow-dispatch POST to the existing read surface."""

    def post_no_content(self, path: str, payload: Mapping[str, object]) -> None:
        """POST one JSON request that must return HTTP 204 with no body."""
        ...


class UrllibGitHubImplementationCiTransport:
    """Minimal stdlib transport restricted to GitHub reads and workflow dispatch."""

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

    def post_no_content(self, path: str, payload: Mapping[str, object]) -> None:
        if not path.startswith("/"):
            raise ImplementationGitHubCiError("GitHub REST path must start with '/'")
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
                status_value: object = response.getcode()
                data: object = response.read()
        except HTTPError as exc:
            raise ImplementationGitHubCiError(
                f"GitHub REST POST {path!r} failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise ImplementationGitHubCiError(
                f"GitHub REST POST {path!r} failed: {exc.reason}"
            ) from exc
        if not isinstance(status_value, int) or status_value != 204:
            raise ImplementationGitHubCiError(
                f"GitHub workflow dispatch returned unexpected HTTP {status_value!r}"
            )
        if not isinstance(data, bytes) or data:
            raise ImplementationGitHubCiError("GitHub workflow dispatch must return an empty body")


class GitHubImplementationCiBackend:
    """GitHub Actions implementation of the project-owned CI validation contract."""

    def __init__(
        self,
        transport: GitHubImplementationCiHttpTransport | None = None,
    ) -> None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._transport = transport or UrllibGitHubImplementationCiTransport(token=token)
        self._reader = GitHubImplementationReadBackend(transport=self._transport)

    def dispatch_workflow(self, repository: str, workflow_file: str, ref: str) -> None:
        self._transport.post_no_content(
            f"{_repo_path(repository)}/actions/workflows/{quote(workflow_file, safe='')}/dispatches",
            {"ref": ref},
        )

    def list_workflow_runs(
        self,
        repository: str,
        workflow_file: str,
        *,
        branch: str,
        head_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        payload = _require_mapping(
            self._get_json(
                f"{_repo_path(repository)}/actions/workflows/{quote(workflow_file, safe='')}/runs"
                f"?event=workflow_dispatch&branch={quote(branch, safe='')}&head_sha={quote(head_sha, safe='')}"
                "&per_page=100&page=1"
            ),
            "workflow runs",
        )
        return _mapping_array(payload.get("workflow_runs"), "workflow_runs")

    def list_workflow_jobs(
        self, repository: str, run_id: int
    ) -> Sequence[Mapping[str, object]]:
        jobs: list[Mapping[str, object]] = []
        page = 1
        while True:
            payload = _require_mapping(
                self._get_json(
                    f"{_repo_path(repository)}/actions/runs/{run_id}/jobs?per_page=100&page={page}"
                ),
                "workflow jobs",
            )
            page_jobs = _mapping_array(payload.get("jobs"), "jobs")
            jobs.extend(page_jobs)
            if len(page_jobs) < 100:
                break
            page += 1
        return tuple(jobs)

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        try:
            return self._reader.get_branch(repository, branch)
        except ImplementationGitHubRestError as exc:
            raise ImplementationGitHubCiError(str(exc), status_code=exc.status_code) from exc

    def _get_json(self, path: str) -> object:
        try:
            return self._transport.get_json(path)
        except GitHubRestError as exc:
            raise ImplementationGitHubCiError(str(exc), status_code=exc.status_code) from exc


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationGitHubCiError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationGitHubCiError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _mapping_array(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ImplementationGitHubCiError(f"GitHub {label} payload must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ImplementationGitHubCiError(f"GitHub {label} entries must be objects")
        result.append(cast(Mapping[str, object], item))
    return tuple(result)
