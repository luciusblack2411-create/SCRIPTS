from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.return_to_draft import (
    ReturnToDraftAuthorization,
    ReturnToDraftDecision,
    ReturnToDraftError,
    ReturnToDraftOperation,
    execute_return_to_draft,
)

REPOSITORY = "luciusblack2411-create/SCRIPTS"
PR_BASE = "a" * 40
LIVE_BASE = "b" * 40
HEAD = "c" * 40


def operation() -> ReturnToDraftOperation:
    return ReturnToDraftOperation(
        repository=REPOSITORY,
        pr_number=61,
        base_branch="main",
        historical_pr_base_sha=PR_BASE,
        expected_live_base_sha=LIVE_BASE,
        head_branch="agent/implementation/example",
        head_sha=HEAD,
        authorization=ReturnToDraftAuthorization.RETURN_TO_DRAFT,
    )


class Backend:
    def __init__(self) -> None:
        self.draft = False
        self.state = "open"
        self.merged = False
        self.pr_base = PR_BASE
        self.pr_head = HEAD
        self.live_base = LIVE_BASE
        self.live_head = HEAD
        self.calls = 0
        self.ref_reads = 0
        self.drift_on_second_barrier = False
        self.invalid_after = False

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert (repository, pr_number) == (REPOSITORY, 61)
        draft = False if self.invalid_after and self.calls else self.draft
        return {
            "state": self.state,
            "draft": draft,
            "merged": self.merged,
            "base": {"ref": "main", "sha": self.pr_base},
            "head": {"ref": "agent/implementation/example", "sha": self.pr_head},
        }

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        assert repository == REPOSITORY
        self.ref_reads += 1
        if branch == "main":
            sha = "d" * 40 if self.drift_on_second_barrier and self.ref_reads >= 3 else self.live_base
            return {"commit": {"sha": sha}}
        return {"commit": {"sha": self.live_head}}

    def convert_pull_request_to_draft(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object]:
        assert (repository, pr_number) == (REPOSITORY, 61)
        self.calls += 1
        self.draft = True
        return {"isDraft": True}


def run(backend: Backend):
    return execute_return_to_draft(operation(), read_backend=backend, transition_backend=backend)


def test_exact_success_performs_one_transition() -> None:
    backend = Backend()
    result = run(backend)
    assert result.decision is ReturnToDraftDecision.RETURNED_TO_DRAFT
    assert result.transition_performed is True
    assert result.returned_to_draft is True
    assert result.ready_for_review is False
    assert result.merge_performed is False
    assert backend.calls == 1


@pytest.mark.parametrize("attribute,value", [("draft", True), ("state", "closed"), ("merged", True)])
def test_invalid_pre_state_fails_without_mutation(attribute: str, value: object) -> None:
    backend = Backend()
    setattr(backend, attribute, value)
    with pytest.raises(ReturnToDraftError):
        run(backend)
    assert backend.calls == 0


@pytest.mark.parametrize("attribute", ["pr_base", "pr_head"])
def test_wrong_snapshot_binding_fails_without_mutation(attribute: str) -> None:
    backend = Backend()
    setattr(backend, attribute, "e" * 40)
    with pytest.raises(ReturnToDraftError, match="binding"):
        run(backend)
    assert backend.calls == 0


@pytest.mark.parametrize("attribute", ["live_base", "live_head"])
def test_live_ref_drift_requests_refresh(attribute: str) -> None:
    backend = Backend()
    setattr(backend, attribute, "e" * 40)
    result = run(backend)
    assert result.decision is ReturnToDraftDecision.NEEDS_REF_REFRESH
    assert backend.calls == 0


def test_second_freshness_barrier_stops_transition() -> None:
    backend = Backend()
    backend.drift_on_second_barrier = True
    assert run(backend).decision is ReturnToDraftDecision.NEEDS_REF_REFRESH
    assert backend.calls == 0


def test_invalid_post_transition_read_back_fails_closed() -> None:
    backend = Backend()
    backend.invalid_after = True
    with pytest.raises(ReturnToDraftError, match="must be Draft"):
        run(backend)
    assert backend.calls == 1


def test_malformed_payload_fails_without_mutation() -> None:
    backend = Backend()
    backend.state = ""
    with pytest.raises(ReturnToDraftError, match="non-empty string"):
        run(backend)
    assert backend.calls == 0
