"""CI/test validation gate for published Implementation Agent work branches."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .mutation import ImplementationMutationResult

APPROVED_CI_WORKFLOW_FILE: Literal["ci.yml"] = "ci.yml"
WORK_BRANCH_PREFIX = "agent/implementation/"


class ImplementationCiValidationError(RuntimeError):
    """Raised when work-branch CI evidence cannot be validated safely."""


class ImplementationCiStatus(StrEnum):
    """Observed outcome of the exact work-branch CI run."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class ImplementationOperationalDecision(StrEnum):
    """Next-step decision after repository mutation and CI validation."""

    READY_FOR_DRAFT_PR = "READY_FOR_DRAFT_PR"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"
    CI_FAILED = "CI_FAILED"
    CI_TIMEOUT = "CI_TIMEOUT"


class ImplementationCiBackend(Protocol):
    """Minimal GitHub Actions evidence/control needed by the CI gate."""

    def dispatch_workflow(self, repository: str, workflow_file: str, ref: str) -> None:
        """Dispatch the approved CI workflow against one exact work branch."""
        ...

    def list_workflow_runs(
        self,
        repository: str,
        workflow_file: str,
        *,
        branch: str,
        head_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        """Return workflow-dispatch runs filtered to one branch and commit."""
        ...

    def list_workflow_jobs(
        self, repository: str, run_id: int
    ) -> Sequence[Mapping[str, object]]:
        """Return all jobs for one exact workflow run."""
        ...

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Observe one branch for post-CI freshness evidence."""
        ...


class ImplementationCiJobResult(FrozenImplementationModel):
    """One completed job belonging to the exact validation workflow run."""

    job_id: int = Field(gt=0)
    name: str = Field(min_length=1)
    status: Literal["completed"] = "completed"
    conclusion: str = Field(min_length=1)


class ImplementationCiValidationResult(FrozenImplementationModel):
    """Canonical CI and base-freshness evidence for a published work branch."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    workflow_file: Literal["ci.yml"] = "ci.yml"
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    run_id: int | None = Field(default=None, gt=0)
    ci_status: ImplementationCiStatus
    workflow_conclusion: str | None = None
    jobs: tuple[ImplementationCiJobResult, ...] = ()
    base_head_after_ci: str = Field(min_length=1)
    base_fresh_after_ci: bool
    decision: ImplementationOperationalDecision
    pull_request_created: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_canonical_ci_result(self) -> ImplementationCiValidationResult:
        if not self.work_branch.startswith(WORK_BRANCH_PREFIX):
            raise ValueError("CI validation work branch must use agent/implementation/ namespace")
        expected_fresh = self.base_head_after_ci == self.base_sha
        if self.base_fresh_after_ci is not expected_fresh:
            raise ValueError("base_fresh_after_ci must match observed base head evidence")

        if self.ci_status is ImplementationCiStatus.TIMED_OUT:
            if self.run_id is not None or self.jobs or self.workflow_conclusion is not None:
                raise ValueError("timed-out CI result must not claim completed run evidence")
            if self.decision is not ImplementationOperationalDecision.CI_TIMEOUT:
                raise ValueError("timed-out CI result requires CI_TIMEOUT decision")
            return self

        if self.run_id is None or not self.jobs or self.workflow_conclusion is None:
            raise ValueError("completed CI result requires run, conclusion, and job evidence")
        job_ids = tuple(job.job_id for job in self.jobs)
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("CI job IDs must be unique")

        all_success = self.workflow_conclusion == "success" and all(
            job.conclusion == "success" for job in self.jobs
        )
        if self.ci_status is ImplementationCiStatus.PASSED:
            if not all_success:
                raise ValueError("PASSED CI result requires successful workflow and jobs")
            expected_decision = (
                ImplementationOperationalDecision.READY_FOR_DRAFT_PR
                if self.base_fresh_after_ci
                else ImplementationOperationalDecision.NEEDS_BASE_REFRESH
            )
            if self.decision is not expected_decision:
                raise ValueError("PASSED CI decision must reflect post-CI base freshness")
        else:
            if all_success:
                raise ValueError("FAILED CI result cannot claim all-success evidence")
            if self.decision is not ImplementationOperationalDecision.CI_FAILED:
                raise ValueError("FAILED CI result requires CI_FAILED decision")
        return self


def validate_work_branch_ci(
    mutation: ImplementationMutationResult,
    backend: ImplementationCiBackend,
    *,
    workflow_file: str = APPROVED_CI_WORKFLOW_FILE,
    timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 5.0,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ImplementationCiValidationResult:
    """Dispatch and wait for CI on the exact published work-branch commit."""
    mutation = ImplementationMutationResult.model_validate(mutation.model_dump(mode="python"))
    if not mutation.base_fresh_after_publish:
        raise ImplementationCiValidationError(
            "cannot dispatch CI because implementation base was stale immediately after publish"
        )
    if workflow_file != APPROVED_CI_WORKFLOW_FILE:
        raise ImplementationCiValidationError(
            f"implementation CI gate only permits {APPROVED_CI_WORKFLOW_FILE!r}"
        )
    if not mutation.work_branch.startswith(WORK_BRANCH_PREFIX):
        raise ImplementationCiValidationError(
            f"implementation CI gate only permits {WORK_BRANCH_PREFIX!r} branches"
        )
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ImplementationCiValidationError("CI timeout and poll interval must be positive")

    backend.dispatch_workflow(mutation.repository, workflow_file, mutation.work_branch)
    deadline = clock() + timeout_seconds

    while True:
        runs = tuple(
            backend.list_workflow_runs(
                mutation.repository,
                workflow_file,
                branch=mutation.work_branch,
                head_sha=mutation.commit_sha,
            )
        )
        matching = tuple(
            run for run in runs if _run_matches(run, mutation.work_branch, mutation.commit_sha)
        )
        if len(matching) > 1:
            raise ImplementationCiValidationError(
                "multiple workflow-dispatch runs match the exact work branch and commit"
            )
        if matching:
            run = matching[0]
            status = _required_string(run, "status", "workflow run")
            if status == "completed":
                return _completed_result(mutation, backend, run)

        if clock() >= deadline:
            base_after = _observed_branch_sha(
                backend.get_branch(mutation.repository, mutation.base_branch), mutation.base_branch
            )
            return ImplementationCiValidationResult(
                repository=mutation.repository,
                workflow_file=APPROVED_CI_WORKFLOW_FILE,
                base_branch=mutation.base_branch,
                base_sha=mutation.base_sha,
                work_branch=mutation.work_branch,
                commit_sha=mutation.commit_sha,
                ci_status=ImplementationCiStatus.TIMED_OUT,
                base_head_after_ci=base_after,
                base_fresh_after_ci=base_after == mutation.base_sha,
                decision=ImplementationOperationalDecision.CI_TIMEOUT,
            )
        sleeper(poll_interval_seconds)


def _completed_result(
    mutation: ImplementationMutationResult,
    backend: ImplementationCiBackend,
    run: Mapping[str, object],
) -> ImplementationCiValidationResult:
    run_id = _required_int(run, "id", "workflow run")
    conclusion = _required_string(run, "conclusion", "completed workflow run")
    raw_jobs = tuple(backend.list_workflow_jobs(mutation.repository, run_id))
    if not raw_jobs:
        raise ImplementationCiValidationError("completed workflow run has no job evidence")

    jobs: list[ImplementationCiJobResult] = []
    for job in raw_jobs:
        status = _required_string(job, "status", "workflow job")
        if status != "completed":
            raise ImplementationCiValidationError("completed workflow contains non-completed job")
        jobs.append(
            ImplementationCiJobResult(
                job_id=_required_int(job, "id", "workflow job"),
                name=_required_string(job, "name", "workflow job"),
                conclusion=_required_string(job, "conclusion", "completed workflow job"),
            )
        )
    jobs_tuple = tuple(sorted(jobs, key=lambda item: (item.name, item.job_id)))
    all_success = conclusion == "success" and all(job.conclusion == "success" for job in jobs_tuple)

    base_after = _observed_branch_sha(
        backend.get_branch(mutation.repository, mutation.base_branch), mutation.base_branch
    )
    base_fresh = base_after == mutation.base_sha
    ci_status = ImplementationCiStatus.PASSED if all_success else ImplementationCiStatus.FAILED
    if all_success:
        decision = (
            ImplementationOperationalDecision.READY_FOR_DRAFT_PR
            if base_fresh
            else ImplementationOperationalDecision.NEEDS_BASE_REFRESH
        )
    else:
        decision = ImplementationOperationalDecision.CI_FAILED

    return ImplementationCiValidationResult(
        repository=mutation.repository,
        workflow_file=APPROVED_CI_WORKFLOW_FILE,
        base_branch=mutation.base_branch,
        base_sha=mutation.base_sha,
        work_branch=mutation.work_branch,
        commit_sha=mutation.commit_sha,
        run_id=run_id,
        ci_status=ci_status,
        workflow_conclusion=conclusion,
        jobs=jobs_tuple,
        base_head_after_ci=base_after,
        base_fresh_after_ci=base_fresh,
        decision=decision,
    )


def _run_matches(run: Mapping[str, object], work_branch: str, commit_sha: str) -> bool:
    return (
        run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == work_branch
        and run.get("head_sha") == commit_sha
    )


def _observed_branch_sha(branch: Mapping[str, object] | None, branch_name: str) -> str:
    if branch is None:
        raise ImplementationCiValidationError(f"cannot observe branch {branch_name!r}")
    commit_value = branch.get("commit")
    if not isinstance(commit_value, Mapping):
        raise ImplementationCiValidationError(f"branch {branch_name!r} has no commit object")
    return _required_string(cast(Mapping[str, object], commit_value), "sha", "branch commit")


def _required_string(value: Mapping[str, object], key: str, context: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ImplementationCiValidationError(f"{context} has no valid {key}")
    return raw


def _required_int(value: Mapping[str, object], key: str, context: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ImplementationCiValidationError(f"{context} has no valid {key}")
    return raw
