"""Operational work-branch mutation and CI validation for Implementation Agent v0.1."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .ci_validation import (
    ImplementationCiBackend,
    ImplementationCiValidationResult,
    ImplementationOperationalDecision,
    validate_work_branch_ci,
)
from .github_ci import GitHubImplementationCiBackend
from .github_mutation import GitHubImplementationMutationBackend
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel, ImplementationRequest
from .mutation import (
    ImplementationMutationBackend,
    ImplementationMutationResult,
    execute_work_branch_mutation,
)
from .workspace import ImplementationWorkspace


class ImplementationOperationFileError(ValueError):
    """Raised when an operational implementation input file is invalid or unavailable."""


class ImplementationOperation(FrozenImplementationModel):
    """Explicit approved payload for one work-branch mutation plus CI gate."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    request: ImplementationRequest
    workspace: ImplementationWorkspace
    work_branch: str = Field(min_length=1)
    commit_message: str = Field(min_length=1)
    workflow_file: str = Field(default="ci.yml", min_length=1)

    @model_validator(mode="after")
    def validate_operation_contract(self) -> ImplementationOperation:
        if self.request.repository != self.workspace.repository:
            raise ValueError("operation request and workspace repository must match")
        if self.request.expected_base_branch != self.workspace.base_branch:
            raise ValueError("operation request and workspace base branch must match")
        if self.request.objective != self.workspace.objective:
            raise ValueError("operation request and workspace objective must match")
        if self.request.authorization != self.workspace.authorization:
            raise ValueError("operation request and workspace authorization must match")
        if not self.commit_message.strip():
            raise ValueError("commit_message must not be blank")
        if "/" in self.workflow_file or self.workflow_file in {".", ".."}:
            raise ValueError("workflow_file must be one workflow file name")
        return self


class ImplementationOperationalResult(FrozenImplementationModel):
    """Canonical outcome of mutation followed by exact work-branch CI validation."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    mutation: ImplementationMutationResult
    ci_validation: ImplementationCiValidationResult
    decision: ImplementationOperationalDecision
    pull_request_created: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_result_contract(self) -> ImplementationOperationalResult:
        if self.repository != self.mutation.repository or self.repository != self.ci_validation.repository:
            raise ValueError("operational result repository evidence is inconsistent")
        if self.mutation.commit_sha != self.ci_validation.commit_sha:
            raise ValueError("operational result CI must validate the exact mutation commit")
        if self.mutation.work_branch != self.ci_validation.work_branch:
            raise ValueError("operational result CI must validate the exact work branch")
        if self.decision is not self.ci_validation.decision:
            raise ValueError("operational decision must equal CI validation decision")
        return self


def load_implementation_operation(path: Path) -> ImplementationOperation:
    """Load one strict operation file without inferring scope, content, or authorization."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ImplementationOperationFileError(f"cannot read implementation operation {path}: {exc}") from exc
    try:
        return ImplementationOperation.model_validate_json(content)
    except ValidationError as exc:
        raise ImplementationOperationFileError(
            f"invalid implementation operation {path}: {exc}"
        ) from exc


def execute_implementation_operation(
    operation: ImplementationOperation,
    *,
    mutation_backend: ImplementationMutationBackend | None = None,
    ci_backend: ImplementationCiBackend | None = None,
    timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 5.0,
) -> ImplementationOperationalResult:
    """Publish one approved workspace, dispatch exact CI, and stop before PR creation."""
    operation = ImplementationOperation.model_validate(operation.model_dump(mode="python"))
    resolved_mutation_backend: ImplementationMutationBackend = (
        mutation_backend or GitHubImplementationMutationBackend()
    )
    resolved_ci_backend: ImplementationCiBackend = ci_backend or GitHubImplementationCiBackend()

    mutation = execute_work_branch_mutation(
        operation.request,
        operation.workspace,
        resolved_mutation_backend,
        work_branch=operation.work_branch,
        commit_message=operation.commit_message,
    )
    ci_validation = validate_work_branch_ci(
        mutation,
        resolved_ci_backend,
        workflow_file=operation.workflow_file,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return ImplementationOperationalResult(
        repository=operation.request.repository,
        objective=operation.request.objective,
        mutation=mutation,
        ci_validation=ci_validation,
        decision=ci_validation.decision,
    )


def render_implementation_result_json(result: ImplementationOperationalResult) -> str:
    """Render canonical structured operational evidence as deterministic JSON."""
    return result.model_dump_json(indent=2)


def render_implementation_result_human(result: ImplementationOperationalResult) -> str:
    """Render a concise human view without replacing canonical structured evidence."""
    ci = result.ci_validation
    mutation = result.mutation
    run = str(ci.run_id) if ci.run_id is not None else "<none>"
    lines = [
        f"Implementation — {result.repository}",
        f"Agent: {result.agent_id}",
        f"Decision: {result.decision.value}",
        f"Objective: {result.objective}",
        f"Base: {mutation.base_branch} {mutation.base_sha}",
        f"Work branch: {mutation.work_branch}",
        f"Commit: {mutation.commit_sha}",
        f"Tree: {mutation.tree_sha}",
        f"Changes: {len(mutation.changes)}",
        f"CI: {ci.ci_status.value} workflow={ci.workflow_file} run={run}",
        f"Base after CI: {ci.base_head_after_ci} fresh={ci.base_fresh_after_ci}",
        "PR created: false",
        "Merge performed: false",
        "Cisco execution allowed: false",
    ]
    return "\n".join(lines)
