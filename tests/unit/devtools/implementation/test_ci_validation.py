from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from cisco_assessment.devtools.implementation import (
    ImplementationCiStatus,
    ImplementationCiValidationError,
    ImplementationFileChangeKind,
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
    ImplementationOperationalDecision,
    validate_work_branch_ci,
)

BASE_SHA = "base-123"
COMMIT_SHA = "commit-456"
WORK_BRANCH = "agent/implementation/example-v0-1"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeCiBackend:
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, str, str]] = []
        self.runs: tuple[Mapping[str, object], ...] = ()
        self.jobs: tuple[Mapping[str, object], ...] = (
            {"id": 11, "name": "quality (3.11)", "status": "completed", "conclusion": "success"},
            {"id": 12, "name": "quality (3.12)", "status": "completed", "conclusion": "success"},
        )
        self.base_sha = BASE_SHA

    def dispatch_workflow(self, repository: str, workflow_file: str, ref: str) -> None:
        self.dispatched.append((repository, workflow_file, ref))

    def list_workflow_runs(
        self,
        repository: str,
        workflow_file: str,
        *,
        branch: str,
        head_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        del repository, workflow_file, branch, head_sha
        return self.runs

    def list_workflow_jobs(
        self, repository: str, run_id: int
    ) -> Sequence[Mapping[str, object]]:
        del repository, run_id
        return self.jobs

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        del repository, branch
        return {"commit": {"sha": self.base_sha}}


def _mutation(*, base_after: str = BASE_SHA) -> ImplementationMutationResult:
    return ImplementationMutationResult(
        repository="owner/repo",
        base_branch="main",
        base_sha=BASE_SHA,
        workspace_sha256="a" * 64,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        tree_sha="tree-789",
        changes=(
            ImplementationMutationChangeResult(
                ordinal=1,
                change_id="impl-change:0001",
                kind=ImplementationFileChangeKind.CREATE,
                path="tests/unit/devtools/implementation/test_generated.py",
                published_blob_sha="blob-new",
                proposed_content_sha256="b" * 64,
            ),
        ),
        base_head_after_publish=base_after,
        base_fresh_after_publish=base_after == BASE_SHA,
    )


def _completed_run(*, conclusion: str = "success") -> Mapping[str, object]:
    return {
        "id": 101,
        "event": "workflow_dispatch",
        "head_branch": WORK_BRANCH,
        "head_sha": COMMIT_SHA,
        "status": "completed",
        "conclusion": conclusion,
    }


def test_ci_success_is_ready_for_draft_pr_when_base_remains_fresh() -> None:
    backend = FakeCiBackend()
    backend.runs = (_completed_run(),)

    result = validate_work_branch_ci(_mutation(), backend)

    assert backend.dispatched == [("owner/repo", "ci.yml", WORK_BRANCH)]
    assert result.ci_status is ImplementationCiStatus.PASSED
    assert result.decision is ImplementationOperationalDecision.READY_FOR_DRAFT_PR
    assert result.base_fresh_after_ci is True
    assert tuple(job.name for job in result.jobs) == ("quality (3.11)", "quality (3.12)")


def test_ci_success_requires_base_refresh_when_main_advanced() -> None:
    backend = FakeCiBackend()
    backend.runs = (_completed_run(),)
    backend.base_sha = "advanced-main"

    result = validate_work_branch_ci(_mutation(), backend)

    assert result.ci_status is ImplementationCiStatus.PASSED
    assert result.decision is ImplementationOperationalDecision.NEEDS_BASE_REFRESH
    assert result.base_fresh_after_ci is False


def test_failed_workflow_returns_ci_failed() -> None:
    backend = FakeCiBackend()
    backend.runs = (_completed_run(conclusion="failure"),)
    backend.jobs = (
        {"id": 11, "name": "quality (3.11)", "status": "completed", "conclusion": "failure"},
    )

    result = validate_work_branch_ci(_mutation(), backend)

    assert result.ci_status is ImplementationCiStatus.FAILED
    assert result.decision is ImplementationOperationalDecision.CI_FAILED


def test_ci_timeout_is_structured_without_claiming_run_evidence() -> None:
    backend = FakeCiBackend()
    clock = FakeClock()

    result = validate_work_branch_ci(
        _mutation(),
        backend,
        timeout_seconds=1.0,
        poll_interval_seconds=1.0,
        sleeper=clock.sleep,
        clock=clock,
    )

    assert result.ci_status is ImplementationCiStatus.TIMED_OUT
    assert result.decision is ImplementationOperationalDecision.CI_TIMEOUT
    assert result.run_id is None
    assert result.jobs == ()


def test_multiple_exact_runs_are_rejected_as_ambiguous() -> None:
    backend = FakeCiBackend()
    backend.runs = (_completed_run(), _completed_run())

    with pytest.raises(ImplementationCiValidationError, match="multiple"):
        validate_work_branch_ci(_mutation(), backend)


def test_stale_post_publish_base_prevents_ci_dispatch() -> None:
    backend = FakeCiBackend()

    with pytest.raises(ImplementationCiValidationError, match="stale"):
        validate_work_branch_ci(_mutation(base_after="advanced-main"), backend)

    assert backend.dispatched == []
