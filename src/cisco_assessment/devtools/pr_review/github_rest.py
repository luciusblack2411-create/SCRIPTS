"""Production read-only GitHub REST backend for PR Review Agent v0.1."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from time import sleep
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHubRestError(RuntimeError):
    """Raised when GitHub REST evidence cannot be acquired safely."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubHttpTransport(Protocol):
    """Small HTTP seam used to test the production GitHub backend offline."""

    def get_json(self, path: str) -> object:
        """GET one GitHub API resource and decode JSON."""
        ...

    def get_text(self, path: str, *, accept: str) -> str:
        """GET one GitHub API resource as UTF-8 text."""
        ...


class UrllibGitHubTransport:
    """Minimal stdlib HTTP transport for GitHub REST read operations."""

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

    def get_json(self, path: str) -> object:
        data = self._get_bytes(path, accept="application/vnd.github+json")
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubRestError(f"GitHub returned invalid JSON for {path!r}") from exc
        return value

    def get_text(self, path: str, *, accept: str) -> str:
        data = self._get_bytes(path, accept=accept)
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise GitHubRestError(f"GitHub returned non-UTF-8 text for {path!r}") from exc

    def _get_bytes(self, path: str, *, accept: str) -> bytes:
        if not path.startswith("/"):
            raise GitHubRestError("GitHub REST path must start with '/'")
        headers = {
            "Accept": accept,
            "User-Agent": "cisco-switch-assessment-pr-review-agent-v0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        request = Request(f"{self._api_base_url}{path}", headers=headers, method="GET")
        if self._token:
            # urllib copies normal headers onto redirects. Keep GitHub credentials on the
            # API request only so a cross-origin signed log URL never receives our token.
            request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data: object = response.read()
        except HTTPError as exc:
            raise GitHubRestError(
                f"GitHub REST GET {path!r} failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise GitHubRestError(f"GitHub REST GET {path!r} failed: {exc.reason}") from exc
        if not isinstance(data, bytes):
            raise GitHubRestError(f"GitHub REST GET {path!r} returned non-bytes response data")
        return data


_FETCH_MERGE_RE = re.compile(
    r"fetch\s+.*?\+([0-9a-f]{40}):(refs/(?:remotes/)?pull/\d+/merge)"
)
_CHECKOUT_MERGE_RE = re.compile(r"git checkout\s+.*?(refs/(?:remotes/)?pull/\d+/merge)")
_HEAD_MERGE_RE = re.compile(
    r"HEAD is now at [0-9a-f]+ Merge ([0-9a-f]{40}) into ([0-9a-f]{40})"
)
_WORKFLOW_LOG_READ_ATTEMPTS = 5
_WORKFLOW_LOG_RETRY_DELAY_SECONDS = 2.0


class GitHubRestReadBackend:
    """GitHub REST implementation of the project-owned read-only backend contract."""

    def __init__(self, transport: GitHubHttpTransport | None = None) -> None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._transport = transport or UrllibGitHubTransport(token=token)
        self._workflow_pr_context: dict[int, tuple[str, str]] = {}

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        path = f"{_repo_path(repository)}/pulls/{pr_number}"
        first = _require_mapping(self._transport.get_json(path), "pull request")
        if first.get("mergeable") is not False:
            return first

        second = _require_mapping(self._transport.get_json(path), "pull request")
        return second

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        path = f"{_repo_path(repository)}/branches/{quote(branch, safe='')}"
        try:
            return _require_mapping(self._transport.get_json(path), "branch")
        except GitHubRestError as exc:
            if exc.status_code == 404:
                return None
            raise

    def list_pull_request_files(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        return self._paginate_array(f"{_repo_path(repository)}/pulls/{pr_number}/files")

    def list_pull_request_commits(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        return self._paginate_array(f"{_repo_path(repository)}/pulls/{pr_number}/commits")

    def get_pull_request_diff(self, repository: str, pr_number: int) -> str:
        return self._transport.get_text(
            f"{_repo_path(repository)}/pulls/{pr_number}",
            accept="application/vnd.github.diff",
        )

    def list_commit_workflow_runs(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        runs: list[Mapping[str, object]] = []
        page = 1
        while True:
            payload = _require_mapping(
                self._transport.get_json(
                    f"{_repo_path(repository)}/actions/runs"
                    f"?event=pull_request&head_sha={quote(commit_sha, safe='')}&per_page=100&page={page}"
                ),
                "workflow runs",
            )
            page_runs = _mapping_array(payload.get("workflow_runs"), "workflow_runs")
            for run in page_runs:
                self._remember_workflow_pr_context(run)
            runs.extend(page_runs)
            if len(page_runs) < 100:
                break
            page += 1
        return tuple(runs)

    def get_workflow_checkout_provenance(
        self,
        repository: str,
        run_id: int,
    ) -> Mapping[str, object] | None:
        payload = _require_mapping(
            self._transport.get_json(
                f"{_repo_path(repository)}/actions/runs/{run_id}/jobs?per_page=100"
            ),
            "workflow jobs",
        )
        jobs = _mapping_array(payload.get("jobs"), "jobs")
        for job in jobs:
            job_id = _require_int(job, "id")
            logs = self._get_workflow_job_log(repository, job_id)
            observed = _parse_checkout_log(logs)
            if observed is None:
                continue
            merge_ref, merge_sha, log_head_sha, log_base_sha = observed
            cached = self._workflow_pr_context.get(run_id)
            head_sha, base_sha = (
                (log_head_sha, log_base_sha)
                if cached is None
                else (cached[1], cached[0])
            )
            if head_sha is None or base_sha is None:
                continue
            return {
                "ref": merge_ref,
                "sha": merge_sha,
                "base_sha": base_sha,
                "head_sha": head_sha,
            }
        return None

    def _get_workflow_job_log(self, repository: str, job_id: int) -> str:
        path = f"{_repo_path(repository)}/actions/jobs/{job_id}/logs"
        for attempt in range(_WORKFLOW_LOG_READ_ATTEMPTS):
            try:
                return self._transport.get_text(
                    path,
                    accept="application/vnd.github+json",
                )
            except GitHubRestError as exc:
                final_attempt = attempt == _WORKFLOW_LOG_READ_ATTEMPTS - 1
                if exc.status_code != 404 or final_attempt:
                    raise
                sleep(_WORKFLOW_LOG_RETRY_DELAY_SECONDS)
        raise AssertionError("unreachable workflow log retry state")

    def _paginate_array(self, path: str) -> tuple[Mapping[str, object], ...]:
        items: list[Mapping[str, object]] = []
        page = 1
        while True:
            payload = self._transport.get_json(f"{path}?per_page=100&page={page}")
            page_items = _mapping_array(payload, "paginated response")
            items.extend(page_items)
            if len(page_items) < 100:
                break
            page += 1
        return tuple(items)

    def _remember_workflow_pr_context(self, run: Mapping[str, object]) -> None:
        run_id = _require_int(run, "id")
        pull_requests = run.get("pull_requests")
        if not isinstance(pull_requests, Sequence) or isinstance(pull_requests, (str, bytes)):
            return
        if len(pull_requests) != 1:
            return
        item = pull_requests[0]
        if not isinstance(item, Mapping):
            return
        pr = cast(Mapping[str, object], item)
        base = pr.get("base")
        head = pr.get("head")
        if not isinstance(base, Mapping) or not isinstance(head, Mapping):
            return
        base_sha = base.get("sha")
        head_sha = head.get("sha")
        if isinstance(base_sha, str) and isinstance(head_sha, str):
            self._workflow_pr_context[run_id] = (base_sha, head_sha)


def _parse_checkout_log(logs: str) -> tuple[str, str, str | None, str | None] | None:
    fetch_match = _FETCH_MERGE_RE.search(logs)
    checkout_match = _CHECKOUT_MERGE_RE.search(logs)
    if fetch_match is None or checkout_match is None:
        return None
    merge_sha, fetched_ref = fetch_match.groups()
    checkout_ref = checkout_match.group(1)
    if fetched_ref != checkout_ref:
        return None
    head_match = _HEAD_MERGE_RE.search(logs)
    if head_match is None:
        return checkout_ref, merge_sha, None, None
    head_sha, base_sha = head_match.groups()
    return checkout_ref, merge_sha, head_sha, base_sha


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise GitHubRestError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GitHubRestError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _mapping_array(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GitHubRestError(f"GitHub {label} payload must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise GitHubRestError(f"GitHub {label} entries must be objects")
        result.append(cast(Mapping[str, object], item))
    return tuple(result)


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GitHubRestError(f"GitHub field {key!r} must be an integer")
    return value
