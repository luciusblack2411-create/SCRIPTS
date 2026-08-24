"""Persistent run journal, resume checks, and explicit base-refresh recovery for feature orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import Field, ValidationError, model_validator

from .feature_intake import FeatureRequest
from .models import FrozenImplementationModel
from .orchestrator import (
    FeatureOrchestrationRun,
    FeatureOrchestrationState,
    begin_feature_orchestration,
    orchestration_artifact_sha256,
)

JOURNAL_ID: Literal["FEATURE_RUN_JOURNAL_V1"] = "FEATURE_RUN_JOURNAL_V1"
RESUME_ID: Literal["FEATURE_RUN_RESUME_V1"] = "FEATURE_RUN_RESUME_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class FeatureRunJournalError(RuntimeError):
    """Raised when run history cannot be recorded, loaded, or resumed safely."""


class FeatureRunJournalFileError(FeatureRunJournalError):
    """Raised when the local journal store cannot preserve its append-only contract."""


class FeatureRunResumeDecision(StrEnum):
    """Deterministic next action derived from one persisted orchestration checkpoint."""

    RESUME = "RESUME"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"
    HUMAN_MERGE_GATE = "HUMAN_MERGE_GATE"
    BLOCKED = "BLOCKED"


class FeatureRunJournalEntry(FrozenImplementationModel):
    """One hash-chained, timestamped orchestration checkpoint."""

    ordinal: int = Field(gt=0)
    recorded_at: datetime
    checkpoint: FeatureOrchestrationRun
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_entry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_entry_integrity(self) -> FeatureRunJournalEntry:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("journal recorded_at must be timezone-aware")
        expected_checkpoint = orchestration_artifact_sha256(self.checkpoint)
        if self.checkpoint_sha256 != expected_checkpoint:
            raise ValueError("checkpoint_sha256 does not match the checkpoint payload")
        expected_entry = _entry_sha256(
            ordinal=self.ordinal,
            recorded_at=self.recorded_at,
            checkpoint_sha256=self.checkpoint_sha256,
            previous_entry_sha256=self.previous_entry_sha256,
        )
        if self.entry_sha256 != expected_entry:
            raise ValueError("entry_sha256 does not match canonical journal entry material")
        return self


class FeatureRunJournal(FrozenImplementationModel):
    """Append-only local history for one feature orchestration run."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    journal_id: Literal["FEATURE_RUN_JOURNAL_V1"] = JOURNAL_ID
    run_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    initial_base_sha: str = Field(min_length=1)
    supersedes_run_id: str | None = Field(default=None, min_length=1)
    entries: tuple[FeatureRunJournalEntry, ...] = Field(min_length=1)
    head_entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_journal_integrity(self) -> FeatureRunJournal:
        expected_ordinals = tuple(range(1, len(self.entries) + 1))
        if tuple(entry.ordinal for entry in self.entries) != expected_ordinals:
            raise ValueError("journal entry ordinals must be contiguous from 1")
        if self.head_entry_sha256 != self.entries[-1].entry_sha256:
            raise ValueError("head_entry_sha256 must identify the final journal entry")

        previous: FeatureRunJournalEntry | None = None
        for entry in self.entries:
            checkpoint = entry.checkpoint
            if (
                checkpoint.run_id != self.run_id
                or checkpoint.repository != self.repository
                or checkpoint.base_branch != self.base_branch
                or checkpoint.base_sha != self.initial_base_sha
            ):
                raise ValueError("journal checkpoint identity/base does not match journal envelope")
            if previous is None:
                if entry.previous_entry_sha256 is not None:
                    raise ValueError("first journal entry must not claim a previous entry")
            else:
                if entry.previous_entry_sha256 != previous.entry_sha256:
                    raise ValueError("journal entry hash chain is broken")
                if entry.recorded_at < previous.recorded_at:
                    raise ValueError("journal timestamps must be monotonic")
                _validate_checkpoint_evidence_monotonic(previous.checkpoint, checkpoint)
            previous = entry
        return self

    @property
    def head_checkpoint(self) -> FeatureOrchestrationRun:
        """Return the latest validated orchestration checkpoint."""
        return self.entries[-1].checkpoint


class FeatureRunResumeBackend(Protocol):
    """Read-only branch evidence required to decide whether a run can resume."""

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Return current branch metadata, or None when it cannot be observed."""
        ...


class FeatureRunResumeResult(FrozenImplementationModel):
    """Canonical resume decision bound to one exact journal head and live base observation."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    resume_id: Literal["FEATURE_RUN_RESUME_V1"] = RESUME_ID
    run_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    journal_head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_state: FeatureOrchestrationState
    expected_base_sha: str = Field(min_length=1)
    observed_base_sha: str = Field(min_length=1)
    base_fresh: bool
    decision: FeatureRunResumeDecision
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_resume_result(self) -> FeatureRunResumeResult:
        if self.base_fresh is not (self.expected_base_sha == self.observed_base_sha):
            raise ValueError("base_fresh must match expected/observed base SHA evidence")
        if not self.base_fresh and self.decision is not FeatureRunResumeDecision.NEEDS_BASE_REFRESH:
            raise ValueError("stale base evidence requires NEEDS_BASE_REFRESH")
        return self


class FeatureBaseRefreshRestart(FrozenImplementationModel):
    """Explicit restart evidence after base drift; prior base-bound artifacts are never reused."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    resume_id: Literal["FEATURE_RUN_RESUME_V1"] = RESUME_ID
    previous_run_id: str = Field(min_length=1)
    new_run_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    previous_base_sha: str = Field(min_length=1)
    refreshed_base_sha: str = Field(min_length=1)
    previous_journal_head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_run: FeatureOrchestrationRun
    previous_base_bound_artifacts_reused: Literal[False] = False
    requires_contract_reproposal: Literal[True] = True
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_restart(self) -> FeatureBaseRefreshRestart:
        if self.previous_run_id == self.new_run_id:
            raise ValueError("base refresh must create a distinct run_id")
        if self.previous_base_sha == self.refreshed_base_sha:
            raise ValueError("base refresh requires an actually changed base SHA")
        if (
            self.new_run.run_id != self.new_run_id
            or self.new_run.repository != self.repository
            or self.new_run.base_branch != self.base_branch
            or self.new_run.base_sha != self.refreshed_base_sha
            or self.new_run.feature_request_sha256 != self.feature_request_sha256
            or self.new_run.state is not FeatureOrchestrationState.FEATURE_RECEIVED
        ):
            raise ValueError("refreshed run does not match restart evidence")
        if any(
            value is not None
            for value in (
                self.new_run.objective,
                self.new_run.proposal_sha256,
                self.new_run.implementation_request_sha256,
                self.new_run.workspace_sha256,
                self.new_run.operational_result_sha256,
                self.new_run.draft_pr_result_sha256,
                self.new_run.review_report_sha256,
                self.new_run.ready_result_sha256,
                self.new_run.work_branch,
                self.new_run.commit_sha,
                self.new_run.ci_run_id,
                self.new_run.pr_number,
                self.new_run.pr_url,
                self.new_run.head_branch,
                self.new_run.head_sha,
            )
        ):
            raise ValueError("base refresh must not carry forward prior base-bound artifacts")
        return self


class JsonFeatureRunJournalStore:
    """Local strict JSON store using atomic replacement for existing run journals."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for_run(self, run_id: str) -> Path:
        """Map a run ID to a non-secret deterministic local filename."""
        if not run_id.strip():
            raise FeatureRunJournalFileError("run_id must not be blank")
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.json"

    def create(self, journal: FeatureRunJournal) -> Path:
        """Create one journal and fail closed if the run already has persisted state."""
        journal = FeatureRunJournal.model_validate(journal.model_dump(mode="python"))
        self._root.mkdir(parents=True, exist_ok=True)
        path = self.path_for_run(journal.run_id)
        payload = _journal_json_bytes(journal)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise FeatureRunJournalFileError(
                f"journal already exists for run_id {journal.run_id!r}"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def load(self, run_id: str) -> FeatureRunJournal:
        """Load and fully revalidate one persisted hash-chained journal."""
        path = self.path_for_run(run_id)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise FeatureRunJournalFileError(f"cannot read run journal {path}: {exc}") from exc
        try:
            return FeatureRunJournal.model_validate_json(payload)
        except (ValidationError, ValueError) as exc:
            raise FeatureRunJournalFileError(f"invalid run journal {path}: {exc}") from exc

    def append(
        self,
        journal: FeatureRunJournal,
        *,
        expected_previous_head_sha256: str,
    ) -> Path:
        """Atomically replace persisted state only when it extends the observed journal by one entry."""
        journal = FeatureRunJournal.model_validate(journal.model_dump(mode="python"))
        current = self.load(journal.run_id)
        if current.head_entry_sha256 != expected_previous_head_sha256:
            raise FeatureRunJournalFileError("persisted journal head changed before append")
        if len(journal.entries) != len(current.entries) + 1:
            raise FeatureRunJournalFileError("journal append must add exactly one checkpoint")
        if journal.entries[:-1] != current.entries:
            raise FeatureRunJournalFileError("journal append must preserve exact persisted history")
        if (
            journal.repository != current.repository
            or journal.base_branch != current.base_branch
            or journal.initial_base_sha != current.initial_base_sha
            or journal.supersedes_run_id != current.supersedes_run_id
        ):
            raise FeatureRunJournalFileError("journal envelope changed during append")

        path = self.path_for_run(journal.run_id)
        self._root.mkdir(parents=True, exist_ok=True)
        payload = _journal_json_bytes(journal)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=self._root,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.chmod(temporary_path, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise FeatureRunJournalFileError(f"cannot append run journal {path}: {exc}") from exc
        return path


def create_feature_run_journal(
    run: FeatureOrchestrationRun,
    *,
    recorded_at: datetime | None = None,
    supersedes_run_id: str | None = None,
) -> FeatureRunJournal:
    """Create the first persistent checkpoint for one orchestration run."""
    run = FeatureOrchestrationRun.model_validate(run.model_dump(mode="python"))
    timestamp = _timestamp(recorded_at)
    entry = _build_entry(run, ordinal=1, recorded_at=timestamp, previous_entry_sha256=None)
    return FeatureRunJournal(
        run_id=run.run_id,
        repository=run.repository,
        base_branch=run.base_branch,
        initial_base_sha=run.base_sha,
        supersedes_run_id=supersedes_run_id,
        entries=(entry,),
        head_entry_sha256=entry.entry_sha256,
    )


def append_feature_run_checkpoint(
    journal: FeatureRunJournal,
    run: FeatureOrchestrationRun,
    *,
    recorded_at: datetime | None = None,
) -> FeatureRunJournal:
    """Append one exact checkpoint without rewriting earlier history or evidence."""
    journal = FeatureRunJournal.model_validate(journal.model_dump(mode="python"))
    run = FeatureOrchestrationRun.model_validate(run.model_dump(mode="python"))
    previous = journal.entries[-1]
    if (
        run.run_id != journal.run_id
        or run.repository != journal.repository
        or run.base_branch != journal.base_branch
        or run.base_sha != journal.initial_base_sha
    ):
        raise FeatureRunJournalError("checkpoint identity/base does not match the journal")
    _validate_checkpoint_evidence_monotonic(previous.checkpoint, run)
    checkpoint_sha = orchestration_artifact_sha256(run)
    if checkpoint_sha == previous.checkpoint_sha256:
        raise FeatureRunJournalError("journal append requires a changed orchestration checkpoint")
    timestamp = _timestamp(recorded_at)
    if timestamp < previous.recorded_at:
        raise FeatureRunJournalError("journal append timestamp precedes the current head")
    entry = _build_entry(
        run,
        ordinal=previous.ordinal + 1,
        recorded_at=timestamp,
        previous_entry_sha256=previous.entry_sha256,
    )
    return FeatureRunJournal(
        run_id=journal.run_id,
        repository=journal.repository,
        base_branch=journal.base_branch,
        initial_base_sha=journal.initial_base_sha,
        supersedes_run_id=journal.supersedes_run_id,
        entries=(*journal.entries, entry),
        head_entry_sha256=entry.entry_sha256,
    )


def evaluate_feature_run_resume(
    journal: FeatureRunJournal,
    backend: FeatureRunResumeBackend,
) -> FeatureRunResumeResult:
    """Compare persisted base evidence with live read-only branch state and derive one safe next action."""
    journal = FeatureRunJournal.model_validate(journal.model_dump(mode="python"))
    checkpoint = journal.head_checkpoint
    observed_base = _branch_sha(
        backend.get_branch(journal.repository, journal.base_branch),
        journal.base_branch,
    )
    base_fresh = observed_base == journal.initial_base_sha
    if not base_fresh or checkpoint.state is FeatureOrchestrationState.NEEDS_BASE_REFRESH:
        decision = FeatureRunResumeDecision.NEEDS_BASE_REFRESH
    elif checkpoint.state is FeatureOrchestrationState.BLOCKED:
        decision = FeatureRunResumeDecision.BLOCKED
    elif checkpoint.state is FeatureOrchestrationState.HUMAN_MERGE_GATE:
        decision = FeatureRunResumeDecision.HUMAN_MERGE_GATE
    else:
        decision = FeatureRunResumeDecision.RESUME
    return FeatureRunResumeResult(
        run_id=journal.run_id,
        repository=journal.repository,
        base_branch=journal.base_branch,
        journal_head_sha256=journal.head_entry_sha256,
        checkpoint_state=checkpoint.state,
        expected_base_sha=journal.initial_base_sha,
        observed_base_sha=observed_base,
        base_fresh=base_fresh,
        decision=decision,
    )


def prepare_base_refresh_restart(
    journal: FeatureRunJournal,
    feature_request: FeatureRequest,
    resume_result: FeatureRunResumeResult,
    *,
    new_run_id: str,
) -> FeatureBaseRefreshRestart:
    """Restart from FEATURE_RECEIVED on a newly observed base without reusing stale base-bound artifacts."""
    journal = FeatureRunJournal.model_validate(journal.model_dump(mode="python"))
    feature_request = FeatureRequest.model_validate(feature_request.model_dump(mode="python"))
    resume_result = FeatureRunResumeResult.model_validate(resume_result.model_dump(mode="python"))
    checkpoint = journal.head_checkpoint
    if resume_result.decision is not FeatureRunResumeDecision.NEEDS_BASE_REFRESH:
        raise FeatureRunJournalError("base-refresh restart requires NEEDS_BASE_REFRESH evidence")
    if (
        resume_result.run_id != journal.run_id
        or resume_result.repository != journal.repository
        or resume_result.base_branch != journal.base_branch
        or resume_result.journal_head_sha256 != journal.head_entry_sha256
        or resume_result.expected_base_sha != journal.initial_base_sha
    ):
        raise FeatureRunJournalError("resume evidence does not bind to the exact journal head")
    if resume_result.observed_base_sha == journal.initial_base_sha:
        raise FeatureRunJournalError("base-refresh restart requires an observed changed base SHA")
    request_sha = orchestration_artifact_sha256(feature_request)
    if (
        request_sha != checkpoint.feature_request_sha256
        or feature_request.repository != journal.repository
        or feature_request.expected_base_branch != journal.base_branch
    ):
        raise FeatureRunJournalError("FeatureRequest does not match the run being refreshed")
    if not new_run_id.strip() or new_run_id == journal.run_id:
        raise FeatureRunJournalError("base refresh requires a distinct non-blank new_run_id")

    new_run = begin_feature_orchestration(
        feature_request,
        run_id=new_run_id,
        base_sha=resume_result.observed_base_sha,
    )
    return FeatureBaseRefreshRestart(
        previous_run_id=journal.run_id,
        new_run_id=new_run_id,
        repository=journal.repository,
        base_branch=journal.base_branch,
        previous_base_sha=journal.initial_base_sha,
        refreshed_base_sha=resume_result.observed_base_sha,
        previous_journal_head_sha256=journal.head_entry_sha256,
        feature_request_sha256=request_sha,
        new_run=new_run,
    )


def _build_entry(
    run: FeatureOrchestrationRun,
    *,
    ordinal: int,
    recorded_at: datetime,
    previous_entry_sha256: str | None,
) -> FeatureRunJournalEntry:
    checkpoint_sha = orchestration_artifact_sha256(run)
    entry_sha = _entry_sha256(
        ordinal=ordinal,
        recorded_at=recorded_at,
        checkpoint_sha256=checkpoint_sha,
        previous_entry_sha256=previous_entry_sha256,
    )
    return FeatureRunJournalEntry(
        ordinal=ordinal,
        recorded_at=recorded_at,
        checkpoint=run,
        checkpoint_sha256=checkpoint_sha,
        previous_entry_sha256=previous_entry_sha256,
        entry_sha256=entry_sha,
    )


def _entry_sha256(
    *,
    ordinal: int,
    recorded_at: datetime,
    checkpoint_sha256: str,
    previous_entry_sha256: str | None,
) -> str:
    material = {
        "ordinal": ordinal,
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        "checkpoint_sha256": checkpoint_sha256,
        "previous_entry_sha256": previous_entry_sha256,
    }
    payload = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise FeatureRunJournalError("journal timestamp must be timezone-aware")
    return timestamp


def _validate_checkpoint_evidence_monotonic(
    previous: FeatureOrchestrationRun,
    current: FeatureOrchestrationRun,
) -> None:
    immutable_fields = (
        "run_id",
        "repository",
        "base_branch",
        "base_sha",
        "request_text",
        "feature_request_sha256",
        "merge_performed",
        "human_merge_gate_required",
        "cisco_execution_allowed",
    )
    for field_name in immutable_fields:
        if getattr(previous, field_name) != getattr(current, field_name):
            raise FeatureRunJournalError(f"checkpoint field {field_name!r} cannot change within a run")

    evidence_fields = (
        "objective",
        "proposal_sha256",
        "implementation_request_sha256",
        "workspace_sha256",
        "operational_result_sha256",
        "draft_pr_result_sha256",
        "review_report_sha256",
        "ready_result_sha256",
        "work_branch",
        "commit_sha",
        "ci_run_id",
        "pr_number",
        "pr_url",
        "head_branch",
        "head_sha",
    )
    for field_name in evidence_fields:
        previous_value = getattr(previous, field_name)
        if previous_value is not None and getattr(current, field_name) != previous_value:
            raise FeatureRunJournalError(
                f"checkpoint evidence field {field_name!r} cannot be removed or rewritten"
            )


def _branch_sha(payload: Mapping[str, object] | None, branch: str) -> str:
    if payload is None:
        raise FeatureRunJournalError(f"cannot observe base branch {branch!r}")
    commit_value = payload.get("commit")
    if not isinstance(commit_value, Mapping):
        raise FeatureRunJournalError(f"base branch {branch!r} has no commit object")
    commit = cast(Mapping[str, object], commit_value)
    sha = commit.get("sha")
    if not isinstance(sha, str) or not sha:
        raise FeatureRunJournalError(f"base branch {branch!r} has no valid commit SHA")
    return sha


def _journal_json_bytes(journal: FeatureRunJournal) -> bytes:
    return (journal.model_dump_json(indent=2) + "\n").encode("utf-8")
