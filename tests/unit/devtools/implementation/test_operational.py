from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

import cisco_assessment.devtools.implementation.operational as operational
from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationCiJobResult,
    ImplementationCiStatus,
    ImplementationCiValidationResult,
    ImplementationFileChangeKind,
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
    ImplementationOperation,
    ImplementationOperationFileError,
    ImplementationOperationalDecision,
    ImplementationProposedFileChange,
    ImplementationRequest,
    ImplementationWorkspace,
    execute_implementation_operation,
    load_implementation_operation,
    render_implementation_result_human,
    render_implementation_result_json,
)

BASE_SHA = "base-123"
COMMIT_SHA = "commit-456"
WORK_BRANCH = "agent/implementation/operational-example"
NEW_PATH = "tests/unit/devtools/implementation/test_generated.py"
NEW_CONTENT = "def test_generated():\n    assert True\n"


def _request() -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Apply one approved testing-only implementation change.",
        authorized_components=(ComponentId.TESTING_FIXTURES,),
        prohibited_components=(ComponentId.COLLECTOR,),
        contracts_to_preserve=("IMPLEMENTATION_AGENT_V1",),
        invariants=("No Cisco execution.",),
        acceptance_criteria=("CI passes.",),
        contract_approved=True,
        authorization=ImplementationAuthorization.WORK_BRANCH,
    )


def _workspace() -> ImplementationWorkspace:
    content_bytes = NEW_CONTENT.encode("utf-8")
    return ImplementationWorkspace(
        repository="owner/repo",
        base_branch="main",
        base_sha=BASE_SHA,
        objective="Apply one approved testing-only implementation change.",
        authorization=ImplementationAuthorization.WORK_BRANCH,
        plan_step_ids=("impl-step:0001",),
        inspected_paths=("tests/unit/devtools/implementation/test_existing.py",),
        contracts_to_preserve=("IMPLEMENTATION_AGENT_V1",),
        acceptance_criteria=("CI passes.",),
        changes=(
            ImplementationProposedFileChange(
                ordinal=1,
                change_id="impl-change:0001",
                kind=ImplementationFileChangeKind.CREATE,
                path=NEW_PATH,
                component=ComponentId.TESTING_FIXTURES,
                proposed_content_sha256=hashlib.sha256(content_bytes).hexdigest(),
                proposed_byte_size=len(content_bytes),
                proposed_content=NEW_CONTENT,
                rationale="Exercise the operational gate.",
                acceptance_criteria=("CI passes.",),
            ),
        ),
    )


def _operation() -> ImplementationOperation:
    return ImplementationOperation(
        request=_request(),
        workspace=_workspace(),
        work_branch=WORK_BRANCH,
        commit_message="test(devtools): apply approved operational change",
    )


def _mutation() -> ImplementationMutationResult:
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
                path=NEW_PATH,
                published_blob_sha="blob-new",
                proposed_content_sha256=hashlib.sha256(NEW_CONTENT.encode()).hexdigest(),
            ),
        ),
        base_head_after_publish=BASE_SHA,
        base_fresh_after_publish=True,
    )


def _ci() -> ImplementationCiValidationResult:
    return ImplementationCiValidationResult(
        repository="owner/repo",
        workflow_file="ci.yml",
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        run_id=101,
        ci_status=ImplementationCiStatus.PASSED,
        workflow_conclusion="success",
        jobs=(
            ImplementationCiJobResult(
                job_id=11,
                name="quality (3.11)",
                conclusion="success",
            ),
        ),
        base_head_after_ci=BASE_SHA,
        base_fresh_after_ci=True,
        decision=ImplementationOperationalDecision.READY_FOR_DRAFT_PR,
    )


def test_load_operation_round_trips_strict_json(tmp_path: Path) -> None:
    path = tmp_path / "operation.json"
    operation = _operation()
    path.write_text(operation.model_dump_json(indent=2), encoding="utf-8")

    assert load_implementation_operation(path) == operation


def test_load_operation_rejects_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "operation.json"
    path.write_text(_operation().model_dump_json()[:-1] + ',"unexpected":true}', encoding="utf-8")

    with pytest.raises(ImplementationOperationFileError, match="invalid"):
        load_implementation_operation(path)


def test_operation_rejects_request_workspace_mismatch() -> None:
    with pytest.raises(ValidationError, match="repository"):
        ImplementationOperation(
            request=_request(),
            workspace=_workspace().model_copy(update={"repository": "other/repo"}),
            work_branch=WORK_BRANCH,
            commit_message="test: mismatch",
        )


def test_execute_operation_binds_mutation_and_ci_result(monkeypatch: pytest.MonkeyPatch) -> None:
    mutation = _mutation()
    ci = _ci()
    observed: dict[str, object] = {}

    def fake_mutation(*args: object, **kwargs: object) -> ImplementationMutationResult:
        observed["mutation_args"] = (args, kwargs)
        return mutation

    def fake_ci(*args: object, **kwargs: object) -> ImplementationCiValidationResult:
        observed["ci_args"] = (args, kwargs)
        return ci

    monkeypatch.setattr(operational, "execute_work_branch_mutation", fake_mutation)
    monkeypatch.setattr(operational, "validate_work_branch_ci", fake_ci)

    result = execute_implementation_operation(
        _operation(),
        mutation_backend=object(),  # type: ignore[arg-type]
        ci_backend=object(),  # type: ignore[arg-type]
        timeout_seconds=30.0,
        poll_interval_seconds=1.0,
    )

    assert result.mutation == mutation
    assert result.ci_validation == ci
    assert result.decision is ImplementationOperationalDecision.READY_FOR_DRAFT_PR
    assert result.pull_request_created is False
    assert result.merge_performed is False
    assert "mutation_args" in observed
    assert "ci_args" in observed


def test_renderers_preserve_canonical_result_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    mutation = _mutation()
    ci = _ci()
    monkeypatch.setattr(operational, "execute_work_branch_mutation", lambda *args, **kwargs: mutation)
    monkeypatch.setattr(operational, "validate_work_branch_ci", lambda *args, **kwargs: ci)
    result = execute_implementation_operation(
        _operation(),
        mutation_backend=object(),  # type: ignore[arg-type]
        ci_backend=object(),  # type: ignore[arg-type]
    )

    rendered_json = render_implementation_result_json(result)
    rendered_human = render_implementation_result_human(result)

    assert COMMIT_SHA in rendered_json
    assert "READY_FOR_DRAFT_PR" in rendered_json
    assert f"Commit: {COMMIT_SHA}" in rendered_human
    assert "PR created: false" in rendered_human
    assert "Cisco execution allowed: false" in rendered_human
