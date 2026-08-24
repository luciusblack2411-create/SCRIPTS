"""Deterministic read-only planning for Implementation Agent v0.1."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..pr_review import ComponentId
from .context import ImplementationContext
from .enums import (
    ImplementationAuthorization,
    ImplementationDecision,
    ImplementationPlanStepKind,
)
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel, ImplementationRequest
from .readiness import evaluate_implementation_readiness


class ImplementationPlanningError(RuntimeError):
    """Raised when a deterministic plan cannot be built from approved inputs."""


class ImplementationPlanStep(FrozenImplementationModel):
    """One ordered planning step; it describes work but performs no mutation."""

    ordinal: int = Field(gt=0)
    step_id: str = Field(min_length=1)
    kind: ImplementationPlanStepKind
    component: ComponentId | None = None
    description: str = Field(min_length=1)
    candidate_paths: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    requires_repository_mutation: bool
    permitted_by_authorization: bool

    @model_validator(mode="after")
    def validate_step_id(self) -> ImplementationPlanStep:
        expected = f"impl-step:{self.ordinal:04d}"
        if self.step_id != expected:
            raise ValueError(f"step_id must equal {expected!r}")
        return self


class ImplementationPlan(FrozenImplementationModel):
    """Canonical read-only plan derived from an approved implementation request."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    authorization: ImplementationAuthorization
    context_file_count: int = Field(ge=0)
    steps: tuple[ImplementationPlanStep, ...] = Field(min_length=1)
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_step_order(self) -> ImplementationPlan:
        ordinals = tuple(step.ordinal for step in self.steps)
        expected = tuple(range(1, len(self.steps) + 1))
        if ordinals != expected:
            raise ValueError("implementation plan step ordinals must be contiguous from 1")
        return self


def build_implementation_plan(
    request: ImplementationRequest,
    context: ImplementationContext,
) -> ImplementationPlan:
    """Build a deterministic plan without changing repository or Cisco state."""
    readiness = evaluate_implementation_readiness(request)
    if readiness.decision is not ImplementationDecision.READY:
        raise ImplementationPlanningError(
            f"implementation request is not ready: {readiness.decision.value}"
        )
    if context.repository != request.repository:
        raise ImplementationPlanningError("implementation context repository does not match request")
    if context.base_branch != request.expected_base_branch:
        raise ImplementationPlanningError("implementation context base branch does not match request")

    steps: list[ImplementationPlanStep] = []

    def add_step(
        *,
        kind: ImplementationPlanStepKind,
        description: str,
        component: ComponentId | None = None,
        candidate_paths: tuple[str, ...] = (),
        acceptance_criteria: tuple[str, ...] = (),
        requires_repository_mutation: bool,
        permitted_by_authorization: bool,
    ) -> None:
        ordinal = len(steps) + 1
        steps.append(
            ImplementationPlanStep(
                ordinal=ordinal,
                step_id=f"impl-step:{ordinal:04d}",
                kind=kind,
                component=component,
                description=description,
                candidate_paths=candidate_paths,
                acceptance_criteria=acceptance_criteria,
                requires_repository_mutation=requires_repository_mutation,
                permitted_by_authorization=permitted_by_authorization,
            )
        )

    all_paths = tuple(item.path for item in context.files)
    add_step(
        kind=ImplementationPlanStepKind.OBSERVE_CONTEXT,
        description="Inspect the exact base snapshot and authorized repository candidates.",
        candidate_paths=all_paths,
        requires_repository_mutation=False,
        permitted_by_authorization=True,
    )

    if request.contracts_to_preserve:
        add_step(
            kind=ImplementationPlanStepKind.PRESERVE_CONTRACTS,
            description=(
                "Preserve approved stable contracts: "
                + ", ".join(request.contracts_to_preserve)
            ),
            requires_repository_mutation=False,
            permitted_by_authorization=True,
        )

    mutation_permitted = request.authorization is not ImplementationAuthorization.PLAN_ONLY
    if request.contracts_to_change:
        add_step(
            kind=ImplementationPlanStepKind.APPLY_APPROVED_CONTRACT_CHANGES,
            description=(
                "Apply only explicitly approved contract changes: "
                + ", ".join(request.contracts_to_change)
            ),
            requires_repository_mutation=True,
            permitted_by_authorization=mutation_permitted,
        )

    authorized = set(request.authorized_components)
    for component in ComponentId:
        if component not in authorized or component is ComponentId.UNKNOWN:
            continue
        component_paths = tuple(
            item.path for item in context.files if item.component is component
        )
        add_step(
            kind=ImplementationPlanStepKind.IMPLEMENT_COMPONENT,
            component=component,
            description=(
                f"Implement the approved objective within {component.value} only; "
                "candidate paths are observational, not mandatory targets."
            ),
            candidate_paths=component_paths,
            requires_repository_mutation=True,
            permitted_by_authorization=mutation_permitted,
        )

    test_paths = tuple(
        item.path
        for item in context.files
        if item.component is ComponentId.TESTING_FIXTURES
    )
    add_step(
        kind=ImplementationPlanStepKind.VERIFY_ACCEPTANCE,
        description="Verify every approved acceptance criterion before proposing integration.",
        candidate_paths=test_paths,
        acceptance_criteria=request.acceptance_criteria,
        requires_repository_mutation=False,
        permitted_by_authorization=True,
    )

    if request.authorization is ImplementationAuthorization.DRAFT_PR:
        add_step(
            kind=ImplementationPlanStepKind.PREPARE_DRAFT_PR,
            description=(
                "Prepare a draft pull request for independent PR Review Agent evaluation; "
                "merge remains a human gate."
            ),
            requires_repository_mutation=True,
            permitted_by_authorization=True,
        )

    return ImplementationPlan(
        repository=request.repository,
        base_branch=context.base_branch,
        base_sha=context.base_sha,
        objective=request.objective,
        authorization=request.authorization,
        context_file_count=len(context.files),
        steps=tuple(steps),
    )
