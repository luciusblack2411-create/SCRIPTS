"""Bounded synthesis boundary for converting approved implementation inputs into file drafts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import Field, ValidationError, model_validator

from ..pr_review import ComponentId
from .context import ImplementationContext
from .enums import ImplementationDecision, ImplementationFileChangeKind
from .models import SCHEMA_VERSION, FrozenImplementationModel, ImplementationRequest
from .planning import ImplementationPlan
from .readiness import evaluate_implementation_readiness
from .source_inspection import ImplementationSourceFile, ImplementationSourceInspection
from .workspace import (
    ImplementationFileChangeDraft,
    ImplementationWorkspace,
    build_implementation_workspace,
)

SYNTHESIS_ID: Literal["IMPLEMENTATION_SYNTHESIS_V1"] = "IMPLEMENTATION_SYNTHESIS_V1"
CODEX_ADAPTER_ID: Literal["CODEX_ADAPTER_V1"] = "CODEX_ADAPTER_V1"


class ImplementationSynthesisError(RuntimeError):
    """Raised when synthesis input or output cannot be trusted as a bounded proposal."""


class CodexSynthesisBackend(Protocol):
    """External synthesis engine hidden behind a project-owned text boundary."""

    def synthesize(self, prompt: str) -> str:
        """Return one JSON synthesis proposal; never mutate repository or Cisco state."""
        ...


class CodexSynthesisPrompt(FrozenImplementationModel):
    """Canonical prompt payload containing only approved scope and inspected source evidence."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    synthesis_id: Literal["IMPLEMENTATION_SYNTHESIS_V1"] = SYNTHESIS_ID
    adapter_id: Literal["CODEX_ADAPTER_V1"] = CODEX_ADAPTER_ID
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    authorized_components: tuple[ComponentId, ...] = Field(min_length=1)
    prohibited_components: tuple[ComponentId, ...] = ()
    contracts_to_preserve: tuple[str, ...] = ()
    contracts_to_change: tuple[str, ...] = ()
    invariants: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    plan_step_ids: tuple[str, ...] = Field(min_length=1)
    sources: tuple[ImplementationSourceFile, ...] = Field(min_length=1)
    repository_mutation_allowed: Literal[False] = False
    contract_approval_allowed: Literal[False] = False
    cisco_execution_allowed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_prompt_contract(self) -> CodexSynthesisPrompt:
        """Require deterministic source ordering and explicit non-overlapping scope."""
        paths = tuple(item.path for item in self.sources)
        if paths != tuple(sorted(paths)):
            raise ValueError("synthesis prompt sources must be sorted by repository path")
        if len(set(paths)) != len(paths):
            raise ValueError("synthesis prompt source paths must be unique")
        if ComponentId.UNKNOWN in self.authorized_components:
            raise ValueError("synthesis prompt authorized_components must not contain UNKNOWN")
        if set(self.authorized_components).intersection(self.prohibited_components):
            raise ValueError("synthesis prompt authorized and prohibited scope must not overlap")
        return self


class CodexSynthesisChange(FrozenImplementationModel):
    """One unexecuted file-change candidate emitted by an external synthesis engine."""

    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    proposed_content: str
    rationale: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = ()


class CodexSynthesisOutput(FrozenImplementationModel):
    """Strict untrusted-output envelope accepted from the Codex adapter boundary."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    synthesis_id: Literal["IMPLEMENTATION_SYNTHESIS_V1"] = SYNTHESIS_ID
    adapter_id: Literal["CODEX_ADAPTER_V1"] = CODEX_ADAPTER_ID
    repository: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    changes: tuple[CodexSynthesisChange, ...] = Field(min_length=1)
    notes: tuple[str, ...] = ()
    repository_mutation_requested: Literal[False] = False
    contract_approval_claimed: Literal[False] = False
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_output_contract(self) -> CodexSynthesisOutput:
        """Reject duplicate change paths instead of allowing last-write-wins behavior."""
        paths = tuple(item.path for item in self.changes)
        if len(set(paths)) != len(paths):
            raise ValueError("synthesis output change paths must be unique")
        return self


def build_codex_synthesis_prompt(
    request: ImplementationRequest,
    context: ImplementationContext,
    plan: ImplementationPlan,
    inspection: ImplementationSourceInspection,
) -> CodexSynthesisPrompt:
    """Build a base-bound prompt only from approved and byte-pinned project evidence."""
    request = ImplementationRequest.model_validate(request.model_dump(mode="python"))
    context = ImplementationContext.model_validate(context.model_dump(mode="python"))
    plan = ImplementationPlan.model_validate(plan.model_dump(mode="python"))
    inspection = ImplementationSourceInspection.model_validate(inspection.model_dump(mode="python"))

    readiness = evaluate_implementation_readiness(request)
    if readiness.decision is not ImplementationDecision.READY:
        raise ImplementationSynthesisError(
            f"implementation request is not ready: {readiness.decision.value}"
        )
    _validate_bound_inputs(request, context, plan, inspection)

    return CodexSynthesisPrompt(
        repository=request.repository,
        base_branch=context.base_branch,
        base_sha=context.base_sha,
        objective=request.objective,
        authorized_components=request.authorized_components,
        prohibited_components=request.prohibited_components,
        contracts_to_preserve=request.contracts_to_preserve,
        contracts_to_change=request.contracts_to_change,
        invariants=request.invariants,
        acceptance_criteria=request.acceptance_criteria,
        plan_step_ids=tuple(step.step_id for step in plan.steps),
        sources=inspection.files,
    )


def render_codex_synthesis_prompt(prompt: CodexSynthesisPrompt) -> str:
    """Render a deterministic JSON prompt with explicit proposal-only instructions."""
    prompt = CodexSynthesisPrompt.model_validate(prompt.model_dump(mode="python"))
    envelope = {
        "instructions": (
            "Return JSON only matching CodexSynthesisOutput. Propose file content only. "
            "Do not claim approval, repository mutation, merge authority, Cisco execution, "
            "or evidence that is not present in this prompt."
        ),
        "input": prompt.model_dump(mode="json"),
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def parse_codex_synthesis_output(raw_output: str) -> CodexSynthesisOutput:
    """Strictly parse external synthesis JSON; unknown or authority fields fail closed."""
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ImplementationSynthesisError("Codex synthesis output is not valid JSON") from exc
    try:
        return CodexSynthesisOutput.model_validate(payload)
    except ValidationError as exc:
        raise ImplementationSynthesisError("Codex synthesis output violates the strict schema") from exc


def build_codex_synthesis_workspace(
    request: ImplementationRequest,
    context: ImplementationContext,
    plan: ImplementationPlan,
    inspection: ImplementationSourceInspection,
    output: CodexSynthesisOutput,
) -> ImplementationWorkspace:
    """Convert bounded synthesis output into the existing validated proposal workspace."""
    prompt = build_codex_synthesis_prompt(request, context, plan, inspection)
    output = CodexSynthesisOutput.model_validate(output.model_dump(mode="python"))
    if output.repository != prompt.repository:
        raise ImplementationSynthesisError("synthesis output repository does not match prompt")
    if output.base_sha != prompt.base_sha:
        raise ImplementationSynthesisError("synthesis output base_sha does not match prompt")
    if output.objective != prompt.objective:
        raise ImplementationSynthesisError("synthesis output objective does not match prompt")

    drafts = tuple(
        ImplementationFileChangeDraft(
            kind=change.kind,
            path=change.path,
            proposed_content=change.proposed_content,
            rationale=change.rationale,
            acceptance_criteria=change.acceptance_criteria,
        )
        for change in output.changes
    )
    try:
        return build_implementation_workspace(request, context, plan, inspection, drafts)
    except Exception as exc:
        if isinstance(exc, ImplementationSynthesisError):
            raise
        raise ImplementationSynthesisError(
            "synthesis output failed project-owned workspace validation"
        ) from exc


def run_codex_synthesis_adapter(
    request: ImplementationRequest,
    context: ImplementationContext,
    plan: ImplementationPlan,
    inspection: ImplementationSourceInspection,
    backend: CodexSynthesisBackend,
) -> ImplementationWorkspace:
    """Run an external synthesizer behind a proposal-only boundary and validate its output."""
    prompt = build_codex_synthesis_prompt(request, context, plan, inspection)
    raw_output = backend.synthesize(render_codex_synthesis_prompt(prompt))
    output = parse_codex_synthesis_output(raw_output)
    return build_codex_synthesis_workspace(request, context, plan, inspection, output)


def _validate_bound_inputs(
    request: ImplementationRequest,
    context: ImplementationContext,
    plan: ImplementationPlan,
    inspection: ImplementationSourceInspection,
) -> None:
    if context.repository != request.repository:
        raise ImplementationSynthesisError("implementation context repository does not match request")
    if context.base_branch != request.expected_base_branch:
        raise ImplementationSynthesisError("implementation context base branch does not match request")
    if plan.repository != request.repository or plan.base_sha != context.base_sha:
        raise ImplementationSynthesisError("implementation plan does not match exact context base")
    if plan.base_branch != context.base_branch or plan.objective != request.objective:
        raise ImplementationSynthesisError("implementation plan metadata does not match request")
    if plan.authorization != request.authorization:
        raise ImplementationSynthesisError("implementation plan authorization does not match request")
    if inspection.repository != request.repository or inspection.base_sha != context.base_sha:
        raise ImplementationSynthesisError("source inspection does not match exact context base")

    context_by_path = {item.path: item for item in context.files}
    for source in inspection.files:
        context_file = context_by_path.get(source.path)
        if context_file is None:
            raise ImplementationSynthesisError(
                f"source inspection path {source.path!r} is absent from context evidence"
            )
        if source.blob_sha != context_file.blob_sha or source.component is not context_file.component:
            raise ImplementationSynthesisError(
                f"source inspection path {source.path!r} does not match context evidence"
            )


def synthesis_output_from_changes(
    *,
    repository: str,
    base_sha: str,
    objective: str,
    changes: Sequence[CodexSynthesisChange],
    notes: Sequence[str] = (),
) -> CodexSynthesisOutput:
    """Convenience constructor for deterministic test or adapter implementations."""
    return CodexSynthesisOutput(
        repository=repository,
        base_sha=base_sha,
        objective=objective,
        changes=tuple(changes),
        notes=tuple(notes),
    )
