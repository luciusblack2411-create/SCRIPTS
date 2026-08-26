"""Dedicated GitHub backend for controlled existing Draft PR amendments."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..pr_review.github_rest import GitHubHttpTransport, GitHubRestError, UrllibGitHubTransport
from .draft_pr_amendment import ImplementationDraftPrAmendmentError
from .github_mutation import GitHubImplementationMutationBackend
from .mutation import ImplementationMutationTreeEntry


class GitHubDraftPrAmendmentTransport(GitHubHttpTransport, Protocol):
    def post_json(self, path: str, payload: Mapping[str, object]) -> object: ...
    def patch_ref_fast_forward(self, path: str, new_sha: str) -> object: ...
    def post_no_content(self, path: str, payload: Mapping[str, object]) -> None: ...


class UrllibGitHubDraftPrAmendmentTransport:
    """HTTP transport with separate JSON-object, non-force PATCH, and 204 POST contracts."""

    def __init__(self, *, token: str, api_base_url: str = "https://api.github.com", timeout_seconds: float = 20.0) -> None:
        self._token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reader = UrllibGitHubTransport(token=token, api_base_url=api_base_url, timeout_seconds=timeout_seconds)

    def get_json(self, path: str) -> object:
        return self._reader.get_json(path)

    def get_text(self, path: str, *, accept: str) -> str:
        return self._reader.get_text(path, accept=accept)

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        return self._json_request("POST", path, payload)

    def patch_ref_fast_forward(self, path: str, new_sha: str) -> object:
        return self._json_request("PATCH", path, {"sha": new_sha, "force": False})

    def post_no_content(self, path: str, payload: Mapping[str, object]) -> None:
        status, data = self._request("POST", path, payload)
        if status != 204 or data != b"":
            raise ImplementationDraftPrAmendmentError(
                f"workflow dispatch expected HTTP 204 empty body, got {status!r}"
            )

    def _json_request(self, method: str, path: str, payload: Mapping[str, object]) -> object:
        _status, data = self._request(method, path, payload)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImplementationDraftPrAmendmentError(
                f"GitHub returned invalid JSON for {method} {path!r}"
            ) from exc

    def _request(self, method: str, path: str, payload: Mapping[str, object]) -> tuple[int, bytes]:
        if not path.startswith("/"):
            raise ImplementationDraftPrAmendmentError("GitHub REST path must start with '/'")
        request = Request(
            f"{self._api_base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "cisco-switch-assessment-draft-pr-amendment-v0.1.2",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method=method,
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                status = response.getcode()
                data = response.read()
        except HTTPError as exc:
            raise ImplementationDraftPrAmendmentError(
                f"GitHub REST {method} {path!r} failed with HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise ImplementationDraftPrAmendmentError(
                f"GitHub REST {method} {path!r} failed: {exc.reason}"
            ) from exc
        if not isinstance(status, int) or not isinstance(data, bytes):
            raise ImplementationDraftPrAmendmentError("GitHub returned invalid HTTP evidence")
        return status, data


class GitHubImplementationDraftPrAmendmentBackend:
    def __init__(self, *, token: str, transport: GitHubDraftPrAmendmentTransport | None = None) -> None:
        self._transport = transport or UrllibGitHubDraftPrAmendmentTransport(token=token)
        self._objects = GitHubImplementationMutationBackend(transport=self._transport)

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None:
        try:
            return _mapping(self._transport.get_json(f"{_repo(repository)}/pulls/{pr_number}"), "pull request")
        except GitHubRestError as exc:
            if exc.status_code == 404:
                return None
            raise ImplementationDraftPrAmendmentError(str(exc)) from exc

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
        return _mapping(
            self._transport.get_json(f"{_repo(repository)}/git/commits/{quote(commit_sha, safe='')}"),
            "commit",
        )

    def update_existing_ref_fast_forward(self, repository: str, branch: str, old_sha: str, new_sha: str) -> None:
        observed = _branch_sha(self.get_branch(repository, branch), branch)
        if observed != old_sha:
            raise ImplementationDraftPrAmendmentError(
                f"branch {branch!r} moved before PATCH: expected {old_sha}, observed {observed}"
            )
        payload = _mapping(
            self._transport.patch_ref_fast_forward(
                f"{_repo(repository)}/git/refs/heads/{quote(branch, safe='')}", new_sha
            ),
            "updated ref",
        )
        object_value = _mapping(payload.get("object"), "updated ref object")
        if payload.get("ref") != f"refs/heads/{branch}" or object_value.get("sha") != new_sha:
            raise ImplementationDraftPrAmendmentError("updated ref response is inconsistent")

    def dispatch_amendment_ci(self, repository: str, workflow_file: str, branch: str) -> None:
        _require_workflow(workflow_file)
        self._transport.post_no_content(
            f"{_repo(repository)}/actions/workflows/ci.yml/dispatches", {"ref": branch}
        )

    def list_amendment_ci_runs(self, repository: str, workflow_file: str, *, branch: str, head_sha: str) -> Sequence[Mapping[str, object]]:
        _require_workflow(workflow_file)
        payload = _mapping(
            self._transport.get_json(
                f"{_repo(repository)}/actions/workflows/ci.yml/runs"
                f"?event=workflow_dispatch&branch={quote(branch, safe='')}&head_sha={quote(head_sha, safe='')}"
                "&per_page=100&page=1"
            ),
            "workflow runs",
        )
        return _array(payload.get("workflow_runs"), "workflow runs")

    def list_amendment_ci_jobs(self, repository: str, run_id: int) -> Sequence[Mapping[str, object]]:
        jobs: list[Mapping[str, object]] = []
        page = 1
        while True:
            payload = _mapping(
                self._transport.get_json(
                    f"{_repo(repository)}/actions/runs/{run_id}/jobs?per_page=100&page={page}"
                ),
                "workflow jobs",
            )
            page_jobs = _array(payload.get("jobs"), "workflow jobs")
            jobs.extend(page_jobs)
            if len(page_jobs) < 100:
                return tuple(jobs)
            page += 1


def _repo(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ImplementationDraftPrAmendmentError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_workflow(workflow_file: str) -> None:
    if workflow_file != "ci.yml":
        raise ImplementationDraftPrAmendmentError("amendment backend permits only ci.yml")


def _branch_sha(value: Mapping[str, object] | None, branch: str) -> str:
    if value is None or not isinstance(value.get("commit"), Mapping):
        raise ImplementationDraftPrAmendmentError(f"cannot observe branch {branch!r}")
    sha = cast(Mapping[str, object], value["commit"]).get("sha")
    if not isinstance(sha, str) or not sha:
        raise ImplementationDraftPrAmendmentError(f"cannot observe branch {branch!r}")
    return sha


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationDraftPrAmendmentError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ImplementationDraftPrAmendmentError(f"GitHub {label} payload must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ImplementationDraftPrAmendmentError(f"GitHub {label} entry must be an object")
        result.append(cast(Mapping[str, object], item))
    return tuple(result)
