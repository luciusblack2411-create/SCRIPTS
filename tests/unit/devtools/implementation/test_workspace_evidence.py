from __future__ import annotations

import hashlib

import pytest

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationContext,
    ImplementationContextFile,
    ImplementationFileChangeDraft,
    ImplementationFileChangeKind,
    ImplementationRequest,
    ImplementationSourceFile,
    ImplementationSourceInspection,
    ImplementationWorkspaceError,
    build_implementation_plan,
    build_implementation_workspace,
)

PATH = "src/cisco_assessment/parsers/example.py"
CONTENT = "def parse():\n    return 1\n"
UPDATED = "def parse():\n    return 2\n"


def _request() -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Implement an approved parser change.",
        authorized_components=(ComponentId.PARSER,),
        prohibited_components=(ComponentId.COLLECTOR,),
        contracts_to_preserve=("CommandId.EXAMPLE",),
        invariants=("Parser remains extraction-only.",),
        acceptance_criteria=("Regression tests pass.",),
        contract_approved=True,
        authorization=ImplementationAuthorization.PLAN_ONLY,
    )


def _context() -> ImplementationContext:
    return ImplementationContext(
        repository="owner/repo",
        base_branch="main",
        base_sha="base-123",
        files=(
            ImplementationContextFile(
                path=PATH,
                component=ComponentId.PARSER,
                blob_sha="parser-blob",
                size=len(CONTENT.encode("utf-8")),
            ),
        ),
        observed_components=(ComponentId.PARSER,),
    )


def _inspection(*, sha256: str | None = None) -> ImplementationSourceInspection:
    data = CONTENT.encode("utf-8")
    return ImplementationSourceInspection(
        repository="owner/repo",
        base_sha="base-123",
        files=(
            ImplementationSourceFile(
                path=PATH,
                component=ComponentId.PARSER,
                blob_sha="parser-blob",
                byte_size=len(data),
                sha256=sha256 or hashlib.sha256(data).hexdigest(),
                content=CONTENT,
            ),
        ),
        total_bytes=len(data),
    )


def _draft() -> ImplementationFileChangeDraft:
    return ImplementationFileChangeDraft(
        kind=ImplementationFileChangeKind.UPDATE,
        path=PATH,
        proposed_content=UPDATED,
        rationale="Apply the approved parser change.",
    )


def test_workspace_preserves_request_authorization_without_executing_it() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)

    workspace = build_implementation_workspace(
        request,
        context,
        plan,
        _inspection(),
        (_draft(),),
    )

    assert workspace.authorization is ImplementationAuthorization.PLAN_ONLY
    assert workspace.repository_mutation_executed is False


def test_workspace_recomputes_inspected_source_sha256_before_using_it() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)

    with pytest.raises(ImplementationWorkspaceError, match="SHA-256 is inconsistent"):
        build_implementation_workspace(
            request,
            context,
            plan,
            _inspection(sha256="0" * 64),
            (_draft(),),
        )


def test_workspace_rejects_inspection_path_absent_from_context() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)
    extra_content = "x = 1\n"
    extra_bytes = extra_content.encode("utf-8")
    extra = ImplementationSourceFile(
        path="src/cisco_assessment/parsers/extra.py",
        component=ComponentId.PARSER,
        blob_sha="extra-blob",
        byte_size=len(extra_bytes),
        sha256=hashlib.sha256(extra_bytes).hexdigest(),
        content=extra_content,
    )
    inspection = _inspection().model_copy(
        update={
            "files": (_inspection().files[0], extra),
            "total_bytes": _inspection().total_bytes + len(extra_bytes),
        }
    )

    with pytest.raises(ImplementationWorkspaceError, match="absent from context evidence"):
        build_implementation_workspace(request, context, plan, inspection, (_draft(),))
