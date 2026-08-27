"""Restricted GitHub backend for the controlled Return-to-Draft transition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .pr_review.github_rest import GitHubRestError, UrllibGitHubTransport

_CONVERT_TO_DRAFT_MUTATION = """mutation ConvertPullRequestToDraft($pullRequestId: ID!) {
  convertPullRequestToDraft(input: {pullRequestId: $pullRequestId}) {
    pullRequest { number isDraft url }
  }
}"""


class GitHubReturnToDraftError(GitHubRestError):
    """Raised when Return-to-Draft evidence or transition fails."""


class GitHubReturnToDraftHttpTransport(Protocol):
    def get_json(self, path: str) -> object: ...

    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object: ...


class UrllibGitHubReturnToDraftTransport:
    """HTTP transport exposing reads and exactly one GraphQL mutation."""

    def __init__(
        self,
        *,
        token: str,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not token.strip():
            raise GitHubReturnToDraftError("Return-to-Draft token must not be empty")
        self._token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reader = UrllibGitHubTransport(
            token=token, api_base_url=api_base_url, timeout_seconds=timeout_seconds
        )

    def get_json(self, path: str) -> object:
        return self._reader.get_json(path)

    def post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        if query != _CONVERT_TO_DRAFT_MUTATION:
            raise GitHubReturnToDraftError(
                "Return-to-Draft transport permits only convertPullRequestToDraft"
            )
        body = json.dumps(
            {"query": query, "variables": dict(variables)}, separators=(",", ":")
        ).encode("utf-8")
        request = Request(
            f"{self._api_base_url}/graphql",
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "cisco-switch-assessment-return-to-draft-v0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data: object = response.read()
        except HTTPError as exc:
            raise GitHubReturnToDraftError(
                f"GitHub GraphQL Return-to-Draft failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise GitHubReturnToDraftError(
                f"GitHub GraphQL Return-to-Draft failed: {exc.reason}"
            ) from exc
        if not isinstance(data, bytes):
            raise GitHubReturnToDraftError("GitHub GraphQL returned non-bytes response data")
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubReturnToDraftError("GitHub GraphQL returned invalid JSON") from exc
        return value


class GitHubReturnToDraftBackend:
    """GitHub backend exposing reads and one typed conversion method."""

    def __init__(
        self,
        transport: GitHubReturnToDraftHttpTransport | None = None,
        *,
        token: str | None = None,
    ) -> None:
        if transport is None:
            if token is None:
                raise GitHubReturnToDraftError(
                    "Return-to-Draft backend requires an explicitly injected token"
                )
            transport = UrllibGitHubReturnToDraftTransport(token=token)
        self._transport = transport

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        if pr_number <= 0:
            raise GitHubReturnToDraftError("pull request number must be positive")
        return _require_mapping(
            self._get_json(f"{_repo_path(repository)}/pulls/{pr_number}"), "pull request"
        )

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        if not branch:
            raise GitHubReturnToDraftError("branch must not be empty")
        try:
            return _require_mapping(
                self._get_json(
                    f"{_repo_path(repository)}/branches/{quote(branch, safe='')}"
                ),
                "branch",
            )
        except GitHubReturnToDraftError as exc:
            if exc.status_code == 404:
                return None
            raise

    def convert_pull_request_to_draft(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object]:
        node_id = _require_str(self.get_pull_request(repository, pr_number), "node_id")
        payload = _require_mapping(
            self._post_graphql(
                _CONVERT_TO_DRAFT_MUTATION, {"pullRequestId": node_id}
            ),
            "GraphQL response",
        )
        _raise_graphql_errors(payload.get("errors"))
        data = _require_mapping(payload.get("data"), "data")
        mutation = _require_mapping(
            data.get("convertPullRequestToDraft"), "convertPullRequestToDraft"
        )
        pull_request = _require_mapping(mutation.get("pullRequest"), "pullRequest")
        if _require_bool(pull_request, "isDraft") is not True:
            raise GitHubReturnToDraftError("GraphQL did not confirm Draft state")
        return pull_request

    def _get_json(self, path: str) -> object:
        try:
            return self._transport.get_json(path)
        except GitHubRestError as exc:
            raise GitHubReturnToDraftError(str(exc), status_code=exc.status_code) from exc

    def _post_graphql(self, query: str, variables: Mapping[str, object]) -> object:
        if query != _CONVERT_TO_DRAFT_MUTATION:
            raise GitHubReturnToDraftError(
                "Return-to-Draft backend POST surface is restricted to one mutation"
            )
        try:
            return self._transport.post_graphql(query, variables)
        except GitHubRestError as exc:
            raise GitHubReturnToDraftError(str(exc), status_code=exc.status_code) from exc


def _raise_graphql_errors(errors: object) -> None:
    if errors is None:
        return
    if isinstance(errors, (str, bytes)) or not isinstance(errors, Sequence):
        raise GitHubReturnToDraftError("GitHub GraphQL errors payload must be an array")
    if not errors:
        return
    summaries: list[str] = []
    for index, item in enumerate(errors):
        if not isinstance(item, Mapping):
            raise GitHubReturnToDraftError(f"GitHub GraphQL errors[{index}] must be an object")
        message = item.get("message")
        if not isinstance(message, str) or not message:
            raise GitHubReturnToDraftError(
                f"GitHub GraphQL errors[{index}].message must be a non-empty string"
            )
        summaries.append(message)
    raise GitHubReturnToDraftError(
        "GitHub GraphQL Return-to-Draft rejected: " + " | ".join(summaries)
    )


def _repo_path(repository: str) -> str:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise GitHubReturnToDraftError("repository must use owner/name form")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GitHubReturnToDraftError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GitHubReturnToDraftError(f"GitHub field {key!r} must be a non-empty string")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise GitHubReturnToDraftError(f"GitHub field {key!r} must be a boolean")
    return value
