"""Fail-closed amendment of one exact same-repository Draft PR head."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from ..pr_review import classify_changed_path
from ..pr_review.enums import ComponentId
from .enums import ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .mutation import ImplementationMutationTreeEntry

WORKFLOW_FILE: Literal["ci.yml"] = "ci.yml"


class ImplementationDraftPrAmendmentError(RuntimeError):
    """Raised when exact amendment evidence cannot be established safely."""


class AmendmentCiStatus(StrEnum):
    PASSED = "PASSED"


class AmendmentDecision(StrEnum):
    READY_FOR_DRAFT_PR = "READY_FOR_DRAFT_PR"


class ImplementationDraftPrAmendmentChange(FrozenImplementationModel):
    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    proposed_content: str
    component: ComponentId


class ImplementationDraftPrAmendmentRequest(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    expected_pr_base_sha: str | None = Field(default=None, min_length=1)
    work_branch: str = Field(min_length=1)
    expected_head_sha: str = Field(min_length=1)
    commit_message: str = Field(min_length=1)
    authorized_components: tuple[ComponentId, ...] = Field(min_length=1)
    prohibited_components: tuple[ComponentId, ...] = ()
    changes: tuple[ImplementationDraftPrAmendmentChange, ...] = Field(min_length=1)
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_contract(self) -> ImplementationDraftPrAmendmentRequest:
        branch = self.work_branch
        if branch == self.base_branch:
            raise ValueError("amendment work branch must differ from base branch")
        if (
            branch.startswith("/")
            or branch.endswith(("/", "."))
            or ".." in branch
            or "//" in branch
            or any(character.isspace() for character in branch)
        ):
            raise ValueError("work_branch syntax is not canonical")
        if not self.commit_message.strip():
            raise ValueError("commit_message must not be blank")
        paths = tuple(change.path for change in self.changes)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("amendment paths must be unique and lexically ordered")
        return self


class ImplementationDraftPrAmendmentCiJob(FrozenImplementationModel):
    job_id: int = Field(gt=0)
    name: str = Field(min_length=1)
    status: Literal["completed"] = "completed"
    conclusion: Literal["success"] = "success"


class ImplementationDraftPrAmendmentCiResult(FrozenImplementationModel):
    workflow_file: Literal["ci.yml"] = WORKFLOW_FILE
    work_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    run_id: int = Field(gt=0)
    jobs: tuple[ImplementationDraftPrAmendmentCiJob, ...] = Field(min_length=1)
    ci_status: Literal[AmendmentCiStatus.PASSED] = AmendmentCiStatus.PASSED
    base_head_after_ci: str = Field(min_length=1)
    base_fresh_after_ci: Literal[True] = True
    decision: Literal[AmendmentDecision.READY_FOR_DRAFT_PR] = AmendmentDecision.READY_FOR_DRAFT_PR


class ImplementationDraftPrAmendmentResult(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    pr_base_sha_before: str = Field(min_length=1)
    pr_base_sha_after: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    old_head_sha: str = Field(min_length=1)
    new_head_sha: str = Field(min_length=1)
    tree_sha: str = Field(min_length=1)
    ci: ImplementationDraftPrAmendmentCiResult
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


class ImplementationDraftPrAmendmentBackend(Protocol):
    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None: ...
    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None: ...
    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]: ...
    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str: ...
    def create_utf8_blob(self, repository: str, content: str) -> str: ...
    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[ImplementationMutationTreeEntry]) -> str: ...
    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str: ...
    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]: ...
    def update_existing_ref_fast_forward(self, repository: str, branch: str, old_sha: str, new_sha: str) -> None: ...
    def dispatch_amendment_ci(self, repository: str, workflow_file: str, branch: str) -> None: ...
    def list_amendment_ci_runs(self, repository: str, workflow_file: str, *, branch: str, head_sha: str) -> Sequence[Mapping[str, object]]: ...
    def list_amendment_ci_jobs(self, repository: str, run_id: int) -> Sequence[Mapping[str, object]]: ...


def execute_draft_pr_amendment(
    request: ImplementationDraftPrAmendmentRequest,
    backend: ImplementationDraftPrAmendmentBackend,
    *,
    timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 5.0,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> ImplementationDraftPrAmendmentResult:
    request = ImplementationDraftPrAmendmentRequest.model_validate(request.model_dump(mode="python"))
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ImplementationDraftPrAmendmentError("CI timeout and poll interval must be positive")
    pr = backend.get_pull_request(request.repository, request.pr_number)
    if pr is None:
        raise ImplementationDraftPrAmendmentError("pull request is missing")
    pr_base_sha_before = _require_pr(
        pr,
        request,
        request.expected_head_sha,
        allowed_base_shas=(_expected_pr_base_sha(request),),
    )
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _require_branch(backend, request.repository, request.work_branch, request.expected_head_sha)

    source = _blob_map(backend.list_tree(request.repository, request.expected_head_sha))
    allowed = set(request.authorized_components)
    prohibited = set(request.prohibited_components)
    entries: list[ImplementationMutationTreeEntry] = []
    for change in request.changes:
        component = classify_changed_path(change.path)
        if component is not change.component or component not in allowed or component in prohibited:
            raise ImplementationDraftPrAmendmentError(f"unauthorized amendment path {change.path!r}")
        present = source.get(change.path)
        if change.kind is ImplementationFileChangeKind.CREATE and present is not None:
            raise ImplementationDraftPrAmendmentError(f"CREATE path {change.path!r} already exists")
        if change.kind is ImplementationFileChangeKind.UPDATE and (
            present is None or present[1] != "100644"
        ):
            raise ImplementationDraftPrAmendmentError(
                f"UPDATE path {change.path!r} is not a regular non-executable file"
            )
        blob_sha = backend.create_utf8_blob(request.repository, change.proposed_content)
        entries.append(ImplementationMutationTreeEntry(path=change.path, blob_sha=blob_sha))

    old_tree_sha = backend.get_commit_tree_sha(request.repository, request.expected_head_sha)
    tree_sha = backend.create_tree(request.repository, old_tree_sha, tuple(entries))
    new_head_sha = backend.create_commit(
        request.repository,
        message=request.commit_message,
        tree_sha=tree_sha,
        parent_sha=request.expected_head_sha,
    )
    _require_commit(backend.get_commit(request.repository, new_head_sha), new_head_sha, tree_sha, request.expected_head_sha)

    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _require_branch(backend, request.repository, request.work_branch, request.expected_head_sha)
    backend.update_existing_ref_fast_forward(
        request.repository, request.work_branch, request.expected_head_sha, new_head_sha
    )
    _require_branch(backend, request.repository, request.work_branch, new_head_sha)
    observed_pr = backend.get_pull_request(request.repository, request.pr_number)
    if observed_pr is None:
        raise ImplementationDraftPrAmendmentError("pull request disappeared after amendment")
    pr_base_sha_after = _require_pr(
        observed_pr,
        request,
        new_head_sha,
        allowed_base_shas=tuple(
            dict.fromkeys(
                (_expected_pr_base_sha(request), request.base_sha)
            )
        ),
    )

    ci = validate_draft_pr_amendment_ci(
        request,
        new_head_sha,
        backend,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        clock=clock,
        sleeper=sleeper,
    )
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    return ImplementationDraftPrAmendmentResult(
        repository=request.repository,
        pr_number=request.pr_number,
        base_branch=request.base_branch,
        base_sha=request.base_sha,
        pr_base_sha_before=pr_base_sha_before,
        pr_base_sha_after=pr_base_sha_after,
        work_branch=request.work_branch,
        old_head_sha=request.expected_head_sha,
        new_head_sha=new_head_sha,
        tree_sha=tree_sha,
        ci=ci,
    )


def validate_draft_pr_amendment_ci(
    request: ImplementationDraftPrAmendmentRequest,
    new_head_sha: str,
    backend: ImplementationDraftPrAmendmentBackend,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> ImplementationDraftPrAmendmentCiResult:
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    before = backend.list_amendment_ci_runs(
        request.repository, WORKFLOW_FILE, branch=request.work_branch, head_sha=new_head_sha
    )
    existing_run_ids_before_dispatch = {
        _run_id(run) for run in before if _run_matches(run, request.work_branch, new_head_sha)
    }
    backend.dispatch_amendment_ci(request.repository, WORKFLOW_FILE, request.work_branch)
    deadline = clock() + timeout_seconds
    while True:
        runs = backend.list_amendment_ci_runs(
            request.repository, WORKFLOW_FILE, branch=request.work_branch, head_sha=new_head_sha
        )
        fresh = tuple(
            run
            for run in runs
            if _run_matches(run, request.work_branch, new_head_sha)
            and _run_id(run) not in existing_run_ids_before_dispatch
        )
        if len(fresh) > 1:
            raise ImplementationDraftPrAmendmentError("multiple fresh exact-head CI runs found")
        if fresh:
            run = fresh[0]
            status = _required_string(run, "status", "workflow run")
            if status == "completed":
                if run.get("conclusion") != "success":
                    raise ImplementationDraftPrAmendmentError("amendment CI workflow failed")
                run_id = _run_id(run)
                raw_jobs = tuple(backend.list_amendment_ci_jobs(request.repository, run_id))
                if not raw_jobs:
                    raise ImplementationDraftPrAmendmentError("amendment CI has no job evidence")
                jobs: list[ImplementationDraftPrAmendmentCiJob] = []
                for job in raw_jobs:
                    if job.get("status") != "completed" or job.get("conclusion") != "success":
                        raise ImplementationDraftPrAmendmentError("amendment CI job failed")
                    jobs.append(
                        ImplementationDraftPrAmendmentCiJob(
                            job_id=_required_int(job, "id", "workflow job"),
                            name=_required_string(job, "name", "workflow job"),
                        )
                    )
                base_after = _branch_sha(
                    backend.get_branch(request.repository, request.base_branch), request.base_branch
                )
                if base_after != request.base_sha:
                    raise ImplementationDraftPrAmendmentError("base drifted during amendment CI")
                return ImplementationDraftPrAmendmentCiResult(
                    work_branch=request.work_branch,
                    commit_sha=new_head_sha,
                    run_id=run_id,
                    jobs=tuple(sorted(jobs, key=lambda job: (job.name, job.job_id))),
                    base_head_after_ci=base_after,
                )
            if status not in {"queued", "in_progress", "waiting", "requested", "pending"}:
                raise ImplementationDraftPrAmendmentError(
                    f"unexpected amendment CI workflow status {status!r}"
                )
        if clock() >= deadline:
            raise ImplementationDraftPrAmendmentError("timed out waiting for fresh exact-head CI")
        sleeper(poll_interval_seconds)


def _expected_pr_base_sha(
    request: ImplementationDraftPrAmendmentRequest,
) -> str:
    return request.expected_pr_base_sha or request.base_sha


def _require_pr(
    pr: Mapping[str, object],
    request: ImplementationDraftPrAmendmentRequest,
    head_sha: str,
    *,
    allowed_base_shas: tuple[str, ...],
) -> str:
    if pr.get("number") != request.pr_number:
        raise ImplementationDraftPrAmendmentError(
            "pull request number is inconsistent"
        )
    if (
        pr.get("state") != "open"
        or pr.get("draft") is not True
        or pr.get("merged") is not False
    ):
        raise ImplementationDraftPrAmendmentError(
            "pull request must be open, Draft, and unmerged"
        )
    base = _mapping(pr.get("base"), "pull request base")
    head = _mapping(pr.get("head"), "pull request head")
    head_repo = _mapping(
        head.get("repo"),
        "pull request head repository",
    )
    base_repo = _mapping(
        base.get("repo"),
        "pull request base repository",
    )
    observed_base_sha = _required_string(
        base,
        "sha",
        "pull request base",
    )
    if (
        base.get("ref") != request.base_branch
        or observed_base_sha not in allowed_base_shas
        or head.get("ref") != request.work_branch
        or head.get("sha") != head_sha
        or head_repo.get("full_name") != request.repository
        or base_repo.get("full_name") != request.repository
    ):
        raise ImplementationDraftPrAmendmentError(
            "pull request binding is stale or cross-repository"
        )
    return observed_base_sha


def _require_commit(commit: Mapping[str, object], sha: str, tree_sha: str, parent_sha: str) -> None:
    tree = _mapping(commit.get("tree"), "commit tree")
    parents = commit.get("parents")
    if (
        commit.get("sha") != sha
        or tree.get("sha") != tree_sha
        or isinstance(parents, (str, bytes))
        or not isinstance(parents, Sequence)
        or len(parents) != 1
        or not isinstance(parents[0], Mapping)
        or parents[0].get("sha") != parent_sha
    ):
        raise ImplementationDraftPrAmendmentError("created commit tree or sole parent is inconsistent")


def _require_branch(backend: ImplementationDraftPrAmendmentBackend, repository: str, branch: str, sha: str) -> None:
    observed = _branch_sha(backend.get_branch(repository, branch), branch)
    if observed != sha:
        raise ImplementationDraftPrAmendmentError(
            f"branch {branch!r} moved: expected {sha}, observed {observed}"
        )


def _branch_sha(value: Mapping[str, object] | None, branch: str) -> str:
    if value is None:
        raise ImplementationDraftPrAmendmentError(f"cannot observe branch {branch!r}")
    commit = _mapping(value.get("commit"), f"branch {branch!r} commit")
    return _required_string(commit, "sha", f"branch {branch!r} commit")


def _run_matches(run: Mapping[str, object], branch: str, sha: str) -> bool:
    return run.get("event") == "workflow_dispatch" and run.get("head_branch") == branch and run.get("head_sha") == sha


def _run_id(run: Mapping[str, object]) -> int:
    return _required_int(run, "id", "workflow run")


def _blob_map(entries: Sequence[Mapping[str, object]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if entry.get("type") != "blob":
            continue
        path = _required_string(entry, "path", "tree entry")
        result[path] = (
            _required_string(entry, "sha", f"tree entry {path!r}"),
            _required_string(entry, "mode", f"tree entry {path!r}"),
        )
    return result


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationDraftPrAmendmentError(f"{context} is missing")
    return cast(Mapping[str, object], value)


def _required_string(value: Mapping[str, object], key: str, context: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ImplementationDraftPrAmendmentError(f"{context} has no valid {key}")
    return raw


def _required_int(value: Mapping[str, object], key: str, context: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ImplementationDraftPrAmendmentError(f"{context} has no valid {key}")
    return raw
