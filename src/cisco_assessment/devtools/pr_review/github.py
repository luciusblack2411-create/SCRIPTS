"""Read-only GitHub boundary and typed pull-request context acquisition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitHubContextError(ValueError):
    """Raised when GitHub read data cannot satisfy the internal context contract."""


class GitHubContextModel(BaseModel):
    """Strict immutable base model for GitHub review context."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GitHubChangedFile(GitHubContextModel):
    """One file reported as changed by a pull request."""

    path: str = Field(min_length=1)
    status: str = Field(min_length=1)
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changes: int = Field(ge=0)
    previous_path: str | None = None


class GitHubCommit(GitHubContextModel):
    """Minimal commit metadata required by PR review."""

    sha: str = Field(min_length=1)
    message: str


class GitHubCheckoutProvenance(GitHubContextModel):
    """Observed checkout of a pull-request merge ref inside one CI workflow run."""

    ref: str = Field(min_length=1)
    sha: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)


class GitHubWorkflowRun(GitHubContextModel):
    """Workflow-run state and optional pull-request checkout provenance."""

    run_id: int = Field(gt=0)
    name: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    status: str = Field(min_length=1)
    conclusion: str | None = None
    event: str | None = None
    pull_request_number: int | None = Field(default=None, gt=0)
    pull_request_base_sha: str | None = None
    pull_request_head_sha: str | None = None
    checkout: GitHubCheckoutProvenance | None = None


class PullRequestContext(GitHubContextModel):
    """Canonical read-only GitHub context consumed by later review checks."""

    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    title: str = Field(min_length=1)
    body: str | None = None
    state: str = Field(min_length=1)
    draft: bool
    mergeable: bool | None
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    base_branch_head_sha: str | None = None
    head_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    changed_files: tuple[GitHubChangedFile, ...]
    commits: tuple[GitHubCommit, ...]
    diff_text: str
    workflow_runs: tuple[GitHubWorkflowRun, ...]

    @field_validator("repository")
    @classmethod
    def validate_repository_name(cls, value: str) -> str:
        """Require the closed owner/name form used by the GitHub boundary."""
        owner, separator, name = value.partition("/")
        if separator != "/" or not owner or not name or "/" in name:
            raise ValueError("repository must use owner/name form")
        return value


class GitHubReadBackend(Protocol):
    """Read-only backend contract hidden behind the project-owned GitHub adapter."""

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        """Return one pull-request payload."""
        ...

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Return current branch metadata, or None when the branch cannot be observed."""
        ...

    def list_pull_request_files(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        """Return all changed-file payloads for the pull request."""
        ...

    def list_pull_request_commits(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        """Return all commit payloads for the pull request."""
        ...

    def get_pull_request_diff(self, repository: str, pr_number: int) -> str:
        """Return the complete effective PR diff text."""
        ...

    def list_commit_workflow_runs(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        """Return workflow runs associated with the requested commit SHA."""
        ...

    def get_workflow_checkout_provenance(
        self,
        repository: str,
        run_id: int,
    ) -> Mapping[str, object] | None:
        """Return observed merge-ref checkout provenance for one workflow run, if provable."""
        ...


class GitHubReadAdapter:
    """Convert external GitHub read payloads into project-owned typed context."""

    def __init__(self, backend: GitHubReadBackend) -> None:
        self._backend = backend

    def load_pull_request_context(self, repository: str, pr_number: int) -> PullRequestContext:
        """Acquire all read-only GitHub evidence required for a later PR review."""
        _validate_repository(repository)
        if pr_number <= 0:
            raise GitHubContextError("pr_number must be greater than zero")

        pull_request = self._backend.get_pull_request(repository, pr_number)
        observed_pr_number = _required_int(pull_request, "number")
        if observed_pr_number != pr_number:
            raise GitHubContextError(
                f"pull-request number mismatch: requested {pr_number}, got {observed_pr_number}"
            )

        base = _required_mapping(pull_request, "base")
        head = _required_mapping(pull_request, "head")
        base_branch = _required_str(base, "ref")
        head_sha = _required_str(head, "sha")
        branch_payload = self._backend.get_branch(repository, base_branch)
        base_branch_head_sha = (
            None if branch_payload is None else _branch_head_sha(branch_payload)
        )

        changed_files = tuple(
            self._parse_changed_file(item)
            for item in self._backend.list_pull_request_files(repository, pr_number)
        )
        commits = tuple(
            self._parse_commit(item)
            for item in self._backend.list_pull_request_commits(repository, pr_number)
        )
        diff_text = self._backend.get_pull_request_diff(repository, pr_number)
        workflow_runs = tuple(
            self._load_workflow_run(repository, pr_number, item)
            for item in self._backend.list_commit_workflow_runs(repository, head_sha)
        )

        mismatched_runs = tuple(run for run in workflow_runs if run.head_sha != head_sha)
        if mismatched_runs:
            observed = ", ".join(run.head_sha for run in mismatched_runs)
            raise GitHubContextError(
                f"workflow run head SHA mismatch: expected {head_sha}, observed {observed}"
            )

        return PullRequestContext(
            repository=repository,
            pr_number=pr_number,
            title=_required_str(pull_request, "title"),
            body=_optional_str(pull_request, "body"),
            state=_required_str(pull_request, "state"),
            draft=_required_bool(pull_request, "draft"),
            mergeable=_optional_bool(pull_request, "mergeable"),
            base_branch=base_branch,
            base_sha=_required_str(base, "sha"),
            base_branch_head_sha=base_branch_head_sha,
            head_branch=_required_str(head, "ref"),
            head_sha=head_sha,
            changed_files=changed_files,
            commits=commits,
            diff_text=diff_text,
            workflow_runs=workflow_runs,
        )

    @staticmethod
    def _parse_changed_file(payload: Mapping[str, object]) -> GitHubChangedFile:
        return GitHubChangedFile(
            path=_required_str(payload, "filename"),
            status=_required_str(payload, "status"),
            additions=_required_int(payload, "additions"),
            deletions=_required_int(payload, "deletions"),
            changes=_required_int(payload, "changes"),
            previous_path=_optional_str(payload, "previous_filename"),
        )

    @staticmethod
    def _parse_commit(payload: Mapping[str, object]) -> GitHubCommit:
        commit = _required_mapping(payload, "commit")
        return GitHubCommit(
            sha=_required_str(payload, "sha"),
            message=_required_str(commit, "message"),
        )

    def _load_workflow_run(
        self,
        repository: str,
        pr_number: int,
        payload: Mapping[str, object],
    ) -> GitHubWorkflowRun:
        run_id = _required_int(payload, "id")
        checkout_payload = self._backend.get_workflow_checkout_provenance(repository, run_id)
        pull_request_number, pull_request_base_sha, pull_request_head_sha = (
            _workflow_pull_request_context(payload, pr_number)
        )
        checkout = (
            None
            if checkout_payload is None
            else GitHubCheckoutProvenance(
                ref=_required_str(checkout_payload, "ref"),
                sha=_required_str(checkout_payload, "sha"),
                base_sha=_required_str(checkout_payload, "base_sha"),
                head_sha=_required_str(checkout_payload, "head_sha"),
            )
        )
        return GitHubWorkflowRun(
            run_id=run_id,
            name=_required_str(payload, "name"),
            head_sha=_required_str(payload, "head_sha"),
            status=_required_str(payload, "status"),
            conclusion=_optional_str(payload, "conclusion"),
            event=_optional_str(payload, "event"),
            pull_request_number=pull_request_number,
            pull_request_base_sha=pull_request_base_sha,
            pull_request_head_sha=pull_request_head_sha,
            checkout=checkout,
        )


def _workflow_pull_request_context(
    payload: Mapping[str, object],
    pr_number: int,
) -> tuple[int | None, str | None, str | None]:
    pull_requests = payload.get("pull_requests")
    if pull_requests is None:
        return None, None, None
    if isinstance(pull_requests, (str, bytes)) or not isinstance(pull_requests, Sequence):
        raise GitHubContextError("GitHub field 'pull_requests' must be an array")

    for item in pull_requests:
        if not isinstance(item, Mapping):
            raise GitHubContextError("GitHub pull_requests entries must be objects")
        item_mapping = cast(Mapping[str, object], item)
        if _required_int(item_mapping, "number") != pr_number:
            continue
        base = _required_mapping(item_mapping, "base")
        head = _required_mapping(item_mapping, "head")
        return (
            pr_number,
            _required_str(base, "sha"),
            _required_str(head, "sha"),
        )
    return None, None, None


def _branch_head_sha(payload: Mapping[str, object]) -> str:
    commit = _required_mapping(payload, "commit")
    return _required_str(commit, "sha")


def _validate_repository(repository: str) -> None:
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise GitHubContextError("repository must use owner/name form")


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise GitHubContextError(f"GitHub field {key!r} must be an object")
    return cast(Mapping[str, object], value)


def _required_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise GitHubContextError(f"GitHub field {key!r} must be a string")
    return value


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitHubContextError(f"GitHub field {key!r} must be a string or null")
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GitHubContextError(f"GitHub field {key!r} must be an integer")
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise GitHubContextError(f"GitHub field {key!r} must be a boolean")
    return value


def _optional_bool(payload: Mapping[str, object], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise GitHubContextError(f"GitHub field {key!r} must be a boolean or null")
    return value
