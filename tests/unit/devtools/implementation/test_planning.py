from __future__ import annotations

import pytest

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationContext,
    ImplementationContextFile,
    ImplementationDecision,
    ImplementationPlanningError,
    ImplementationPlanStepKind,
    ImplementationRequest,
    build_implementation_plan,
    evaluate_implementation_readiness,
)


def _context() -> ImplementationContext:
    return ImplementationContext(
        repository="owner/repo",
        base_branch="main",
        base_sha="base-123",
        files=(
            ImplementationContextFile(
                path="src/cisco_assessment/parsers/example.py",
                component=ComponentId.PARSER,
                blob_sha="p",
            ),
            ImplementationContextFile(
                path="tests/unit/parsers/test_example.py",
                component=ComponentId.TESTING_FIXTURES,
                blob_sha="t",
            ),
        ),
        observed_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
    )


def _request(
    *,
    authorization: ImplementationAuthorization = ImplementationAuthorization.DRAFT_PR,
    contract_approved: bool = True,
    components: tuple[ComponentId, ...] = (
        ComponentId.TESTING_FIXTURES,
        ComponentId.PARSER,
    ),
) -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Implement an approved parser change.",
        authorized_components=components,
        prohibited_components=(ComponentId.COLLECTOR, ComponentId.RULES),
        contracts_to_preserve=("CommandId.EXAMPLE",),
        contracts_to_change=("ParserId.IOS_EXAMPLE_V1",),
        invariants=("Parser remains extraction-only.",),
        acceptance_criteria=("Regression tests pass.", "Evidence paths remain stable."),
        contract_approved=contract_approved,
        authorization=authorization,
    )


def test_plan_requires_ready_request() -> None:
    request = _request(contract_approved=False)
    assert evaluate_implementation_readiness(request).decision is ImplementationDecision.NEEDS_HUMAN_INPUT

    with pytest.raises(ImplementationPlanningError, match="NEEDS_HUMAN_INPUT"):
        build_implementation_plan(request, _context())


def test_plan_is_deterministic_and_uses_canonical_component_order() -> None:
    plan = build_implementation_plan(_request(), _context())

    assert tuple(step.step_id for step in plan.steps) == tuple(
        f"impl-step:{ordinal:04d}" for ordinal in range(1, len(plan.steps) + 1)
    )
    implementation_components = tuple(
        step.component
        for step in plan.steps
        if step.kind is ImplementationPlanStepKind.IMPLEMENT_COMPONENT
    )
    assert implementation_components == (
        ComponentId.PARSER,
        ComponentId.TESTING_FIXTURES,
    )
    parser_step = next(
        step
        for step in plan.steps
        if step.kind is ImplementationPlanStepKind.IMPLEMENT_COMPONENT
        and step.component is ComponentId.PARSER
    )
    assert parser_step.candidate_paths == ("src/cisco_assessment/parsers/example.py",)
    assert "candidate paths are observational" in parser_step.description


def test_plan_only_describes_mutation_but_does_not_authorize_it() -> None:
    plan = build_implementation_plan(
        _request(authorization=ImplementationAuthorization.PLAN_ONLY),
        _context(),
    )

    mutation_steps = tuple(step for step in plan.steps if step.requires_repository_mutation)
    assert mutation_steps
    assert all(not step.permitted_by_authorization for step in mutation_steps)
    assert all(
        step.kind is not ImplementationPlanStepKind.PREPARE_DRAFT_PR for step in plan.steps
    )


def test_work_branch_never_plans_draft_pr_or_merge() -> None:
    plan = build_implementation_plan(
        _request(authorization=ImplementationAuthorization.WORK_BRANCH),
        _context(),
    )

    assert all(
        step.kind is not ImplementationPlanStepKind.PREPARE_DRAFT_PR for step in plan.steps
    )
    assert all(step.kind.value != "MERGE" for step in plan.steps)
    assert plan.human_merge_gate_required is True
    assert plan.cisco_execution_allowed is False


def test_draft_pr_authorization_adds_only_draft_pr_preparation() -> None:
    plan = build_implementation_plan(_request(), _context())

    assert plan.steps[-1].kind is ImplementationPlanStepKind.PREPARE_DRAFT_PR
    assert plan.steps[-1].permitted_by_authorization is True
    verify = next(
        step for step in plan.steps if step.kind is ImplementationPlanStepKind.VERIFY_ACCEPTANCE
    )
    assert verify.acceptance_criteria == (
        "Regression tests pass.",
        "Evidence paths remain stable.",
    )
    assert verify.candidate_paths == ("tests/unit/parsers/test_example.py",)


def test_context_repository_or_base_mismatch_blocks_planning() -> None:
    context = _context().model_copy(update={"repository": "other/repo"})
    with pytest.raises(ImplementationPlanningError, match="repository"):
        build_implementation_plan(_request(), context)

    context = _context().model_copy(update={"base_branch": "develop"})
    with pytest.raises(ImplementationPlanningError, match="base branch"):
        build_implementation_plan(_request(), context)
