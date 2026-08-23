"""Production GitHub backend for the controlled Ready-for-Review transition."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .pr_review.github_rest import GitHubRestError, UrllibGitHubTransport

_MARK_READY_MUTATION = """mutation MarkPullRequestReadyForReview($pullRequestId: ID!) {
  markPullRequestReadyForReview(input: {pullRequestId: $pullRequestId}) {
    pullRequest { number isDraft url }
  }
}"""


class GitHubReadyForReviewError(GitHubRestError):
    """Raised when GitHub Ready-for-Review evidence or transition fails."""


class GitHubReadyForReviewHttpTransport(Protocol):
    """HTTP seam exposing reads plus one GraphQL POST surface."""

    def get_json(self, path: str) -> object:
        """GET one GitHub API resource."""
        ...

    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        """POST one GraphQL operation."""
        ...


class UrllibGitHubReadyForReviewTransport:
    """Minimal stdlib transport with explicit token injection and one GraphQL POST."""

    def __init__(
        self,
        *,
        token: str,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not token.strip():
            raise GitHubReadyForReviewError("Ready-for-Review token must not be empty")
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

    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        if query != _MARK_READY_MUTATION:
            raise GitHubReadyForReviewError(
                "Ready-for-Review transport permits only markPullRequestReadyForReview"
            )
        body = json.dumps(
            {"query": query, "variables": dict(variables)},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "cisco-switch-assessment-ready-for-review-v0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        request = Request(
            f"{self._api_base_url}/graphql",
            data=body,
            headers=headers,
            method="POST",
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data: object = response.read()
        except HTTPError as exc:
            raise GitHubReadyForReviewError(
                f"GitHub GraphQL mark Ready-for-Review failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise GitHubReadyForReviewError(
                f"GitHub GraphQL mark Ready-for-Review failed: {exc.reason}"
            ) from exc
        if not isinstance(data, bytes):
            raise GitHubReadyForReviewError("GitHub GraphQL returned non-bytes response data")
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubReadyForReviewError("GitHub GraphQL returned invalid JSON") from exc
        return value


class GitHubReadyForReviewBackend:
    """GitHub implementation of the controlled Ready-for-Review backend contract."""

    def __init__(
        self,
        transport: GitHubReadyForReviewHttpTransport | None = None,
        *,
        token: str | None = None,
    ) -> None:
        if transport is None:
            if token is None:
                raise GitHubReadyForReviewError(
                    "Ready-for-Review backend requires an explicitly injected token"
                )
            transport = UrllibGitHubReadyForReviewTransport(token=token)
        self._transport = transport

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        if pr_number <= 0:
            raise GitHubReadyForReviewError("pull request number must be positive")
        return _require_mapping(
            self._get_json(f"{_repo_path(repository)}/pulls/{pr_number}"),
            "pull request",
        )

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        if not branch:
            raise GitHubReadyForReviewError("branch must not be empty")
        path = f"{_repo_path(repository)}/branches/{quote(branch, safe='')}"
        try:
            return _require_mapping(self._get_json(path), "branch")
        except GitHubReadyForReviewError as exc:
            if exc.status_code == 404:
                return None
            raise

    def mark_pull_request_ready(
        self,
        repository: str,
        pr_number: int,
    ) -> Mapping[str, object]:
        current = self.get_pull_request(repository, pr_number)
        node_id = _require_str(current, "node_id")
        payload = _require_mapping(
            self._post_graphql(
                _MARK_READY_MUTATION,
                {"pullRequestId": node_id},
            ),
            "GraphQL response",
        )
        errors = payload.get("errors")
        if errors is not None:
            raise GitHubReadyForReviewError("GitHub GraphQL returned errors for Ready-for-Review")
        data = _require_mapping(payload.get("data"), "data")
        mutation = _require_mapping(
            data.get("markPullRequestReadyForReview"),
            "markPullRequestReadyForReview",
        )
        pull_request = _require_mapping(mutation.get("pullRequest"), "pullRequest")
        if _require_bool(pull_request, "isDraft") is not False:
            raise GitHubReadyForReviewError("GraphQL did not confirm Ready-for-Review state")
        return pull_request

    def _get_json(self, path: str) -> object:
        try:
            return self._transport.get_json(path)
        except GitHubRestError as exc:
            raise GitHubReadyForReviewError(str(exc), status_code=exc.status_code) from exc

    def _post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        if query != _MARK_READY_MUTATION:
            raise GitHubReadyForReviewError(
                "Ready-for-Review backend POST surface is restricted to one GraphQL mutation"
            )
        try:
            return self._transport.post_graphql(query, variables)
        except GitHubRestError as exc:
            raise GitHubReadyForReviewError(str(exc), status_code=exc.status_code) from exc


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise GitHubReadyForReviewError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GitHubReadyForReviewError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GitHubReadyForReviewError(f"GitHub field {key!r} must be a non-empty string")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise GitHubReadyForReviewError(f"GitHub field {key!r} must be a boolean")
    return value
