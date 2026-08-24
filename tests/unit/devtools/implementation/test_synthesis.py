from __future__ import annotations

import hashlib
import json

import pytest

from cisco_assessment.devtools.implementation.context import (
    ImplementationContext,
    ImplementationContextFile,
)
from cisco_assessment.devtools.implementation.enums import (
    ImplementationAuthorization,
    ImplementationFileChangeKind,
)
from cisco_assessment.devtools.implementation.models import ImplementationRequest
from cisco_assessment.devtools.implementation.planning import build_implementation_plan
from cisco_assessment.devtools.implementation.source_inspection import (
    ImplementationSourceFile,
    ImplementationSourceInspection,
)
from cisco_assessment.devtools.implementation.synthesis import (
    CODEX_ADAPTER_ID,
    SYNTHESIS_ID,
    CodexSynthesisChange,
    CodexSynthesisOutput,
    ImplementationSynthesisError,
    build_codex_synthesis_prompt,
    build_codex_synthesis_workspace,
    parse_codex_synthesis_output,
    render_codex_synthesis_prompt,
    run_codex_synthesis_adapter,
)
from cisco_assessment.devtools.pr_review import ComponentId

PARSER_PATH = "src/cisco_assessment/parsers/example.py"
TEST_PATH = "tests/unit/parsers/test_example.py"
NEW_TEST_PATH = "tests/unit/parsers/test_example_regression.py"
PARSER_CONTENT = "def parse():\n    return 1\n"
TEST_CONTENT = "def test_parse():\n    assert True\n"


def _request(*, approved: bool = True) -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Implement an approved parser change.",
        authorized_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
        prohibited_components=(ComponentId.COLLECTOR, ComponentId.RULES),
        contracts_to_preserve=("CommandId.EXAMPLE",),
        contracts_to_change=("ParserId.IOS_EXAMPLE_V1",),
        invariants=("Parser remains extraction-only.",),
        acceptance_criteria=("Regression tests pass.", "Evidence paths remain stable."),
        contract_approved=approved,
        authorization=ImplementationAuthorization.PLAN_ONLY,
    )


def _context() -> ImplementationContext:
    return ImplementationContext(
        repository="owner/repo",
        base_branch="main",
        base_sha="base-123",
        files=(
            ImplementationContextFile(
                path=PARSER_PATH,
                component=ComponentId.PARSER,
                blob_sha="parser-blob",
                size=len(PARSER_CONTENT.encode("utf-8")),
            ),
            ImplementationContextFile(
                path=TEST_PATH,
                component=ComponentId.TESTING_FIXTURES,
                blob_sha="test-blob",
                size=len(TEST_CONTENT.encode("utf-8")),
            ),
        ),
        observed_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
    )


def _inspection() -> ImplementationSourceInspection:
    parser_bytes = PARSER_CONTENT.encode("utf-8")
    test_bytes = TEST_CONTENT.encode("utf-8")
    return ImplementationSourceInspection(
        repository="owner/repo",
        base_sha="base-123",
        files=(
            ImplementationSourceFile(
                path=PARSER_PATH,
                component=ComponentId.PARSER,
                blob_sha="parser-blob",
                byte_size=len(parser_bytes),
                sha256=hashlib.sha256(parser_bytes).hexdigest(),
                content=PARSER_CONTENT,
            ),
            ImplementationSourceFile(
                path=TEST_PATH,
                component=ComponentId.TESTING_FIXTURES,
                blob_sha="test-blob",
                byte_size=len(test_bytes),
                sha256=hashlib.sha256(test_bytes).hexdigest(),
                content=TEST_CONTENT,
            ),
        ),
        total_bytes=len(parser_bytes) + len(test_bytes),
    )


def _output(*, base_sha: str = "base-123") -> CodexSynthesisOutput:
    return CodexSynthesisOutput(
        repository="owner/repo",
        base_sha=base_sha,
        objective="Implement an approved parser change.",
        changes=(
            CodexSynthesisChange(
                kind=ImplementationFileChangeKind.UPDATE,
                path=PARSER_PATH,
                proposed_content="def parse():\n    return 2\n",
                rationale="Apply only the approved parser change.",
                acceptance_criteria=("Evidence paths remain stable.",),
            ),
            CodexSynthesisChange(
                kind=ImplementationFileChangeKind.CREATE,
                path=NEW_TEST_PATH,
                proposed_content="def test_regression():\n    assert True\n",
                rationale="Lock the approved regression behavior.",
                acceptance_criteria=("Regression tests pass.",),
            ),
        ),
    )


def test_prompt_is_exact_base_bound_and_proposal_only() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)

    prompt = build_codex_synthesis_prompt(request, context, plan, _inspection())
    rendered = json.loads(render_codex_synthesis_prompt(prompt))

    assert prompt.synthesis_id == SYNTHESIS_ID
    assert prompt.adapter_id == CODEX_ADAPTER_ID
    assert prompt.base_sha == "base-123"
    assert prompt.repository_mutation_allowed is False
    assert prompt.contract_approval_allowed is False
    assert prompt.cisco_execution_allowed is False
    assert prompt.human_merge_gate_required is True
    assert tuple(source.path for source in prompt.sources) == (PARSER_PATH, TEST_PATH)
    assert rendered["input"]["base_sha"] == "base-123"
    assert "Do not claim approval" in rendered["instructions"]


def test_prompt_rejects_unapproved_request_and_stale_inputs() -> None:
    context = _context()
    inspection = _inspection()
    unapproved = _request(approved=False)
    unapproved_plan = build_implementation_plan(
        _request(),
        context,
    )

    with pytest.raises(ImplementationSynthesisError, match="not ready"):
        build_codex_synthesis_prompt(unapproved, context, unapproved_plan, inspection)

    request = _request()
    plan = build_implementation_plan(request, context)
    stale_plan = plan.model_copy(update={"base_sha": "stale-base"})
    with pytest.raises(ImplementationSynthesisError, match="exact context base"):
        build_codex_synthesis_prompt(request, context, stale_plan, inspection)

    stale_inspection = inspection.model_copy(update={"base_sha": "stale-base"})
    with pytest.raises(ImplementationSynthesisError, match="source inspection"):
        build_codex_synthesis_prompt(request, context, plan, stale_inspection)


def test_external_output_is_strict_and_cannot_claim_authority() -> None:
    with pytest.raises(ImplementationSynthesisError, match="not valid JSON"):
        parse_codex_synthesis_output("not-json")

    payload = _output().model_dump(mode="json")
    payload["authorization"] = "DRAFT_PR"
    with pytest.raises(ImplementationSynthesisError, match="strict schema"):
        parse_codex_synthesis_output(json.dumps(payload))

    payload = _output().model_dump(mode="json")
    payload["repository_mutation_requested"] = True
    with pytest.raises(ImplementationSynthesisError, match="strict schema"):
        parse_codex_synthesis_output(json.dumps(payload))

    payload = _output().model_dump(mode="json")
    payload["cisco_execution_allowed"] = True
    with pytest.raises(ImplementationSynthesisError, match="strict schema"):
        parse_codex_synthesis_output(json.dumps(payload))


def test_valid_output_delegates_to_existing_workspace_contract() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)

    workspace = build_codex_synthesis_workspace(
        request,
        context,
        plan,
        _inspection(),
        _output(),
    )

    assert tuple(change.path for change in workspace.changes) == (PARSER_PATH, NEW_TEST_PATH)
    assert workspace.changes[0].source_blob_sha == "parser-blob"
    assert workspace.repository_mutation_executed is False
    assert workspace.human_merge_gate_required is True
    assert workspace.cisco_execution_allowed is False


def test_output_fails_closed_on_base_drift_scope_escape_or_invented_policy() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)
    inspection = _inspection()

    with pytest.raises(ImplementationSynthesisError, match="base_sha"):
        build_codex_synthesis_workspace(
            request,
            context,
            plan,
            inspection,
            _output(base_sha="stale-base"),
        )

    scope_escape = _output().model_copy(
        update={
            "changes": (
                CodexSynthesisChange(
                    kind=ImplementationFileChangeKind.CREATE,
                    path="src/cisco_assessment/collector/escape.py",
                    proposed_content="x = 1\n",
                    rationale="Attempt to escape approved scope.",
                ),
            )
        }
    )
    with pytest.raises(ImplementationSynthesisError, match="workspace validation"):
        build_codex_synthesis_workspace(request, context, plan, inspection, scope_escape)

    invented_policy = _output().model_copy(
        update={
            "changes": (
                CodexSynthesisChange(
                    kind=ImplementationFileChangeKind.CREATE,
                    path=NEW_TEST_PATH,
                    proposed_content="def test_x():\n    assert True\n",
                    rationale="Attempt to invent policy.",
                    acceptance_criteria=("Invented policy passes.",),
                ),
            )
        }
    )
    with pytest.raises(ImplementationSynthesisError, match="workspace validation"):
        build_codex_synthesis_workspace(request, context, plan, inspection, invented_policy)


class _FakeCodexBackend:
    def __init__(self, output: CodexSynthesisOutput) -> None:
        self.output = output
        self.prompts: list[str] = []

    def synthesize(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.output.model_dump_json()


def test_adapter_backend_receives_bounded_prompt_and_cannot_mutate_directly() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)
    backend = _FakeCodexBackend(_output())

    workspace = run_codex_synthesis_adapter(
        request,
        context,
        plan,
        _inspection(),
        backend,
    )

    assert len(backend.prompts) == 1
    prompt_payload = json.loads(backend.prompts[0])
    assert prompt_payload["input"]["repository_mutation_allowed"] is False
    assert prompt_payload["input"]["contract_approval_allowed"] is False
    assert prompt_payload["input"]["cisco_execution_allowed"] is False
    assert workspace.repository_mutation_executed is False
