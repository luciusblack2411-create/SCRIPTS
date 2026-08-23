"""Proposal-only implementation workspace for Implementation Agent v0.1."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from ..pr_review import ComponentId, classify_changed_path
from .context import ImplementationContext
from .enums import ImplementationDecision, ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel, ImplementationRequest
from .planning import ImplementationPlan
from .readiness import evaluate_implementation_readiness
from .source_inspection import (
    SUPPORTED_SOURCE_SUFFIXES,
    ImplementationSourceInspection,
)


class ImplementationWorkspaceError(RuntimeError):
    """Raised when a proposal workspace cannot be built from approved evidence."""


class ImplementationFileChangeDraft(FrozenImplementationModel):
    """Unexecuted proposed source change supplied for deterministic validation."""

    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    proposed_content: str
    rationale: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = ()


class ImplementationProposedFileChange(FrozenImplementationModel):
    """Canonical validated file proposal pinned to exact source evidence when updating."""

    ordinal: int = Field(gt=0)
    change_id: str = Field(min_length=1)
    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    component: ComponentId
    source_blob_sha: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposed_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_byte_size: int = Field(ge=0)
    proposed_content: str
    rationale: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = ()
    requires_repository_mutation: Literal[True] = True
    executed: Literal[False] = False

    @model_validator(mode="after")
    def validate_change_contract(self) -> ImplementationProposedFileChange:
        """Require stable IDs, coherent source evidence, and exact proposed hashes."""
        expected_id = f"impl-change:{self.ordinal:04d}"
        if self.change_id != expected_id:
            raise ValueError(f"change_id must equal {expected_id!r}")
        if self.kind is ImplementationFileChangeKind.CREATE:
            if self.source_blob_sha is not None or self.source_sha256 is not None:
                raise ValueError("CREATE proposals must not claim source blob evidence")
        elif self.source_blob_sha is None or self.source_sha256 is None:
            raise ValueError("UPDATE proposals require source blob and SHA-256 evidence")

        try:
            content_bytes = self.proposed_content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("proposed_content must be strict UTF-8 text") from exc
        if self.proposed_byte_size != len(content_bytes):
            raise ValueError("proposed_byte_size must equal UTF-8 content size")
        expected_sha256 = hashlib.sha256(content_bytes).hexdigest()
        if self.proposed_content_sha256 != expected_sha256:
            raise ValueError("proposed_content_sha256 must match proposed_content")
        return self


class ImplementationWorkspace(FrozenImplementationModel):
    """Canonical proposal workspace that never performs repository mutation."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    plan_step_ids: tuple[str, ...] = Field(min_length=1)
    inspected_paths: tuple[str, ...] = Field(min_length=1)
    contracts_to_preserve: tuple[str, ...] = ()
    contracts_to_change: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    changes: tuple[ImplementationProposedFileChange, ...] = Field(min_length=1)
    repository_mutation_executed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_canonical_workspace(self) -> ImplementationWorkspace:
        """Require deterministic path and ordinal ordering."""
        if self.inspected_paths != tuple(sorted(self.inspected_paths)):
            raise ValueError("inspected_paths must be sorted")
        if len(set(self.inspected_paths)) != len(self.inspected_paths):
            raise ValueError("inspected_paths must be unique")
        ordinals = tuple(change.ordinal for change in self.changes)
        expected_ordinals = tuple(range(1, len(self.changes) + 1))
        if ordinals != expected_ordinals:
            raise ValueError("workspace change ordinals must be contiguous from 1")
        paths = tuple(change.path for change in self.changes)
        if paths != tuple(sorted(paths)):
            raise ValueError("workspace changes must be sorted by repository path")
        if len(set(paths)) != len(paths):
            raise ValueError("workspace change paths must be unique")
        return self


def build_implementation_workspace(
    request: ImplementationRequest,
    context: ImplementationContext,
    plan: ImplementationPlan,
    inspection: ImplementationSourceInspection,
    drafts: Sequence[ImplementationFileChangeDraft],
) -> ImplementationWorkspace:
    """Validate proposed source changes without writing repository state."""
    readiness = evaluate_implementation_readiness(request)
    if readiness.decision is not ImplementationDecision.READY:
        raise ImplementationWorkspaceError(
            f"implementation request is not ready: {readiness.decision.value}"
        )
    _validate_workspace_inputs(request, context, plan, inspection)

    draft_items = tuple(drafts)
    if not draft_items:
        raise ImplementationWorkspaceError("implementation workspace requires at least one change")
    paths = tuple(item.path for item in draft_items)
    if len(set(paths)) != len(paths):
        raise ImplementationWorkspaceError("implementation workspace change paths must be unique")

    context_by_path = {item.path: item for item in context.files}
    inspection_by_path = {item.path: item for item in inspection.files}
    allowed = set(request.authorized_components)
    prohibited = set(request.prohibited_components)
    approved_criteria = set(request.acceptance_criteria)

    changes: list[ImplementationProposedFileChange] = []
    for ordinal, draft in enumerate(sorted(draft_items, key=lambda item: item.path), start=1):
        _validate_repository_path(draft.path)
        suffix = PurePosixPath(draft.path).suffix.lower()
        if suffix not in SUPPORTED_SOURCE_SUFFIXES:
            raise ImplementationWorkspaceError(
                f"path {draft.path!r} is not an approved source-text file type"
            )
        component = classify_changed_path(draft.path)
        if component is ComponentId.UNKNOWN or component not in allowed or component in prohibited:
            raise ImplementationWorkspaceError(
                f"path {draft.path!r} is outside the authorized implementation scope"
            )
        unapproved_criteria = set(draft.acceptance_criteria).difference(approved_criteria)
        if unapproved_criteria:
            raise ImplementationWorkspaceError(
                f"path {draft.path!r} cites acceptance criteria not approved by the request"
            )

        source_blob_sha: str | None = None
        source_sha256: str | None = None
        if draft.kind is ImplementationFileChangeKind.CREATE:
            if draft.path in context_by_path:
                raise ImplementationWorkspaceError(
                    f"CREATE path {draft.path!r} already exists at the implementation base"
                )
        else:
            context_file = context_by_path.get(draft.path)
            source_file = inspection_by_path.get(draft.path)
            if context_file is None:
                raise ImplementationWorkspaceError(
                    f"UPDATE path {draft.path!r} is not present in the implementation context"
                )
            if source_file is None:
                raise ImplementationWorkspaceError(
                    f"UPDATE path {draft.path!r} was not explicitly source-inspected"
                )
            if source_file.blob_sha != context_file.blob_sha:
                raise ImplementationWorkspaceError(
                    f"UPDATE path {draft.path!r} source blob does not match context evidence"
                )
            if source_file.component is not component or context_file.component is not component:
                raise ImplementationWorkspaceError(
                    f"UPDATE path {draft.path!r} component evidence is inconsistent"
                )
            if draft.proposed_content == source_file.content:
                raise ImplementationWorkspaceError(
                    f"UPDATE path {draft.path!r} does not change inspected source content"
                )
            source_blob_sha = source_file.blob_sha
            source_sha256 = source_file.sha256

        try:
            proposed_bytes = draft.proposed_content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ImplementationWorkspaceError(
                f"path {draft.path!r} proposed content is not strict UTF-8 text"
            ) from exc
        changes.append(
            ImplementationProposedFileChange(
                ordinal=ordinal,
                change_id=f"impl-change:{ordinal:04d}",
                kind=draft.kind,
                path=draft.path,
                component=component,
                source_blob_sha=source_blob_sha,
                source_sha256=source_sha256,
                proposed_content_sha256=hashlib.sha256(proposed_bytes).hexdigest(),
                proposed_byte_size=len(proposed_bytes),
                proposed_content=draft.proposed_content,
                rationale=draft.rationale,
                acceptance_criteria=draft.acceptance_criteria,
            )
        )

    return ImplementationWorkspace(
        repository=request.repository,
        base_branch=context.base_branch,
        base_sha=context.base_sha,
        objective=request.objective,
        plan_step_ids=tuple(step.step_id for step in plan.steps),
        inspected_paths=tuple(item.path for item in inspection.files),
        contracts_to_preserve=request.contracts_to_preserve,
        contracts_to_change=request.contracts_to_change,
        acceptance_criteria=request.acceptance_criteria,
        changes=tuple(changes),
    )


def _validate_workspace_inputs(
    request: ImplementationRequest,
    context: ImplementationContext,
    plan: ImplementationPlan,
    inspection: ImplementationSourceInspection,
) -> None:
    if context.repository != request.repository:
        raise ImplementationWorkspaceError("implementation context repository does not match request")
    if context.base_branch != request.expected_base_branch:
        raise ImplementationWorkspaceError("implementation context base branch does not match request")
    if plan.repository != request.repository or plan.base_sha != context.base_sha:
        raise ImplementationWorkspaceError("implementation plan does not match exact context base")
    if plan.base_branch != context.base_branch or plan.objective != request.objective:
        raise ImplementationWorkspaceError("implementation plan metadata does not match request")
    if plan.authorization != request.authorization:
        raise ImplementationWorkspaceError("implementation plan authorization does not match request")
    if inspection.repository != request.repository or inspection.base_sha != context.base_sha:
        raise ImplementationWorkspaceError("source inspection does not match exact context base")


def _validate_repository_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if path.startswith("/") or path.endswith("/"):
        raise ImplementationWorkspaceError(f"path {path!r} is not a canonical repository file path")
    if not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ImplementationWorkspaceError(f"path {path!r} is not a canonical repository file path")
    if str(parsed) != path:
        raise ImplementationWorkspaceError(f"path {path!r} is not a canonical repository file path")
