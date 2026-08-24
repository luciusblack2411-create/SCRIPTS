from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cisco_assessment.devtools.implementation.enums import ImplementationAuthorization
from cisco_assessment.devtools.implementation.feature_intake import FeatureRequest
from cisco_assessment.devtools.implementation.orchestrator import (
    FeatureOrchestrationRun,
    FeatureOrchestrationState,
    begin_feature_orchestration,
)
from cisco_assessment.devtools.implementation.run_journal import (
    FeatureRunJournalError,
    FeatureRunJournalFileError,
    FeatureRunResumeDecision,
    JsonFeatureRunJournalStore,
    append_feature_run_checkpoint,
    create_feature_run_journal,
    evaluate_feature_run_resume,
    prepare_base_refresh_restart,
)

REPOSITORY = "owner/repo"
BASE_SHA = "a" * 40
NEW_BASE_SHA = "b" * 40
T0 = datetime(2026, 8, 23, 20, 0, tzinfo=UTC)


class FakeResumeBackend:
    def __init__(self, sha: str) -> None:
        self.sha = sha

    def get_branch(self, repository: str, branch: str):
        assert repository == REPOSITORY
        assert branch == "main"
        return {"commit": {"sha": self.sha}}


def _request(*, text: str = "Implement the approved feature.") -> FeatureRequest:
    return FeatureRequest(
        repository=REPOSITORY,
        request_text=text,
        requested_max_authorization=ImplementationAuthorization.WORK_BRANCH,
    )


def _run(*, run_id: str = "run-0001") -> FeatureOrchestrationRun:
    return begin_feature_orchestration(_request(), run_id=run_id, base_sha=BASE_SHA)


def _contract_proposed(run: FeatureOrchestrationRun) -> FeatureOrchestrationRun:
    return run.model_copy(
        update={
            "objective": "Implement one bounded DevTools feature.",
            "proposal_sha256": "1" * 64,
            "state": FeatureOrchestrationState.NEEDS_CONTRACT_APPROVAL,
        }
    )


def _human_merge_gate(run: FeatureOrchestrationRun) -> FeatureOrchestrationRun:
    return run.model_copy(
        update={
            "objective": "Implement one bounded DevTools feature.",
            "proposal_sha256": "1" * 64,
            "implementation_request_sha256": "2" * 64,
            "workspace_sha256": "3" * 64,
            "operational_result_sha256": "4" * 64,
            "draft_pr_result_sha256": "5" * 64,
            "review_report_sha256": "6" * 64,
            "ready_result_sha256": "7" * 64,
            "work_branch": "agent/implementation/run-0001",
            "commit_sha": "c" * 40,
            "ci_run_id": 1001,
            "pr_number": 70,
            "pr_url": "https://github.com/owner/repo/pull/70",
            "head_branch": "agent/implementation/run-0001",
            "head_sha": "c" * 40,
            "state": FeatureOrchestrationState.HUMAN_MERGE_GATE,
        }
    )


def test_journal_hash_chains_checkpoints_and_preserves_safety_invariants() -> None:
    first = _run()
    journal = create_feature_run_journal(first, recorded_at=T0)
    second = _contract_proposed(first)
    journal = append_feature_run_checkpoint(
        journal,
        second,
        recorded_at=T0 + timedelta(seconds=1),
    )

    assert tuple(entry.ordinal for entry in journal.entries) == (1, 2)
    assert journal.entries[0].previous_entry_sha256 is None
    assert journal.entries[1].previous_entry_sha256 == journal.entries[0].entry_sha256
    assert journal.head_entry_sha256 == journal.entries[1].entry_sha256
    assert journal.head_checkpoint.state is FeatureOrchestrationState.NEEDS_CONTRACT_APPROVAL
    assert journal.merge_performed is False
    assert journal.human_merge_gate_required is True
    assert journal.cisco_execution_allowed is False


def test_journal_rejects_rewritten_existing_evidence() -> None:
    first = _run()
    proposed = _contract_proposed(first)
    journal = create_feature_run_journal(proposed, recorded_at=T0)
    rewritten = proposed.model_copy(update={"proposal_sha256": "9" * 64})

    with pytest.raises(FeatureRunJournalError, match="cannot be removed or rewritten"):
        append_feature_run_checkpoint(
            journal,
            rewritten,
            recorded_at=T0 + timedelta(seconds=1),
        )


def test_json_store_round_trips_and_rejects_stale_append_writer(tmp_path: Path) -> None:
    store = JsonFeatureRunJournalStore(tmp_path)
    first = _run()
    journal = create_feature_run_journal(first, recorded_at=T0)
    path = store.create(journal)

    loaded = store.load(first.run_id)
    assert loaded == journal
    assert path == store.path_for_run(first.run_id)

    advanced = append_feature_run_checkpoint(
        journal,
        _contract_proposed(first),
        recorded_at=T0 + timedelta(seconds=1),
    )
    store.append(advanced, expected_previous_head_sha256=journal.head_entry_sha256)
    assert store.load(first.run_id) == advanced

    with pytest.raises(FeatureRunJournalFileError, match="head changed"):
        store.append(advanced, expected_previous_head_sha256=journal.head_entry_sha256)


def test_json_store_rejects_tampered_checkpoint_payload(tmp_path: Path) -> None:
    store = JsonFeatureRunJournalStore(tmp_path)
    journal = create_feature_run_journal(_run(), recorded_at=T0)
    path = store.create(journal)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][0]["checkpoint"]["request_text"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FeatureRunJournalFileError, match="invalid run journal"):
        store.load(journal.run_id)


def test_resume_returns_resume_only_when_live_base_is_still_exact() -> None:
    journal = create_feature_run_journal(_run(), recorded_at=T0)
    result = evaluate_feature_run_resume(journal, FakeResumeBackend(BASE_SHA))

    assert result.decision is FeatureRunResumeDecision.RESUME
    assert result.base_fresh is True
    assert result.expected_base_sha == BASE_SHA
    assert result.observed_base_sha == BASE_SHA
    assert result.merge_performed is False
    assert result.cisco_execution_allowed is False


def test_resume_detects_base_drift_and_refresh_restarts_from_feature_received() -> None:
    original_run = _contract_proposed(_run())
    journal = create_feature_run_journal(original_run, recorded_at=T0)
    resume = evaluate_feature_run_resume(journal, FakeResumeBackend(NEW_BASE_SHA))

    assert resume.decision is FeatureRunResumeDecision.NEEDS_BASE_REFRESH
    assert resume.base_fresh is False

    restart = prepare_base_refresh_restart(
        journal,
        _request(),
        resume,
        new_run_id="run-0002",
    )
    assert restart.previous_run_id == "run-0001"
    assert restart.new_run_id == "run-0002"
    assert restart.previous_base_sha == BASE_SHA
    assert restart.refreshed_base_sha == NEW_BASE_SHA
    assert restart.previous_base_bound_artifacts_reused is False
    assert restart.requires_contract_reproposal is True
    assert restart.new_run.state is FeatureOrchestrationState.FEATURE_RECEIVED
    assert restart.new_run.base_sha == NEW_BASE_SHA
    assert restart.new_run.objective is None
    assert restart.new_run.proposal_sha256 is None
    assert restart.new_run.workspace_sha256 is None
    assert restart.new_run.pr_number is None
    assert restart.merge_performed is False
    assert restart.cisco_execution_allowed is False

    refreshed_journal = create_feature_run_journal(
        restart.new_run,
        recorded_at=T0 + timedelta(seconds=2),
        supersedes_run_id=restart.previous_run_id,
    )
    assert refreshed_journal.supersedes_run_id == "run-0001"
    assert refreshed_journal.initial_base_sha == NEW_BASE_SHA


def test_base_refresh_rejects_a_different_feature_request() -> None:
    journal = create_feature_run_journal(_run(), recorded_at=T0)
    resume = evaluate_feature_run_resume(journal, FakeResumeBackend(NEW_BASE_SHA))

    with pytest.raises(FeatureRunJournalError, match="FeatureRequest does not match"):
        prepare_base_refresh_restart(
            journal,
            _request(text="Different feature intent."),
            resume,
            new_run_id="run-0002",
        )


def test_human_merge_gate_resume_stops_at_human_gate_without_merging() -> None:
    run = _human_merge_gate(_run())
    journal = create_feature_run_journal(run, recorded_at=T0)
    result = evaluate_feature_run_resume(journal, FakeResumeBackend(BASE_SHA))

    assert result.decision is FeatureRunResumeDecision.HUMAN_MERGE_GATE
    assert result.checkpoint_state is FeatureOrchestrationState.HUMAN_MERGE_GATE
    assert result.merge_performed is False
    assert result.human_merge_gate_required is True
    assert result.cisco_execution_allowed is False


def test_human_merge_gate_becomes_base_refresh_when_main_moves() -> None:
    run = _human_merge_gate(_run())
    journal = create_feature_run_journal(run, recorded_at=T0)
    result = evaluate_feature_run_resume(journal, FakeResumeBackend(NEW_BASE_SHA))

    assert result.decision is FeatureRunResumeDecision.NEEDS_BASE_REFRESH
    assert result.base_fresh is False


def test_journal_rejects_timestamp_regression_and_duplicate_checkpoint() -> None:
    run = _run()
    journal = create_feature_run_journal(run, recorded_at=T0)

    with pytest.raises(FeatureRunJournalError, match="changed orchestration checkpoint"):
        append_feature_run_checkpoint(
            journal,
            run,
            recorded_at=T0 + timedelta(seconds=1),
        )

    with pytest.raises(FeatureRunJournalError, match="timestamp precedes"):
        append_feature_run_checkpoint(
            journal,
            _contract_proposed(run),
            recorded_at=T0 - timedelta(seconds=1),
        )
