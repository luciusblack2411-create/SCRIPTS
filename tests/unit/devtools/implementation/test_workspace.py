from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationContext,
    ImplementationContextFile,
    ImplementationFileChangeDraft,
    ImplementationFileChangeKind,
    ImplementationProposedFileChange,
    ImplementationRequest,
    ImplementationSourceFile,
    ImplementationSourceInspection,
    ImplementationWorkspaceError,
    build_implementation_plan,
    build_implementation_workspace,
)

PARSER_PATH = "src/cisco_assessment/parsers/example.py"
TEST_PATH = "tests/unit/parsers/test_example.py"
NEW_TEST_PATH = "tests/unit/parsers/test_example_regression.py"
PARSER_CONTENT = "def parse():\n    return 1\n"
TEST_CONTENT = "def test_parse():\n    assert True\n"


def _request(
    *,
    authorization: ImplementationAuthorization = ImplementationAuthorization.PLAN_ONLY,
) -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Implement an approved parser change.",
        authorized_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
        prohibited_components=(ComponentId.COLLECTOR, ComponentId.RULES),
        contracts_to_preserve=("CommandId.EXAMPLE",),
        contracts_to_change=("ParserId.IOS_EXAMPLE_V1",),
        invariants=("Parser remains extraction-only.",),
        acceptance_criteria=("Regression tests pass.", "Evidence paths remain stable."),
        contract_approved=True,
        authorization=authorization,
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


def _workspace(*drafts: ImplementationFileChangeDraft):
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)
    return build_implementation_workspace(request, context, plan, _inspection(), drafts)


def test_workspace_canonicalizes_changes_and_pins_update_source_evidence() -> None:
    parser_update = "def parse():\n    return 2\n"
    new_test = "def test_regression():\n    assert True\n"

    workspace = _workspace(
        ImplementationFileChangeDraft(
            kind=ImplementationFileChangeKind.CREATE,
            path=NEW_TEST_PATH,
            proposed_content=new_test,
            rationale="Lock the approved regression behavior.",
            acceptance_criteria=("Regression tests pass.",),
        ),
        ImplementationFileChangeDraft(
            kind=ImplementationFileChangeKind.UPDATE,
            path=PARSER_PATH,
            proposed_content=parser_update,
            rationale="Apply the approved parser contract change.",
            acceptance_criteria=("Evidence paths remain stable.",),
        ),
    )

    assert tuple(change.path for change in workspace.changes) == (PARSER_PATH, NEW_TEST_PATH)
    assert tuple(change.change_id for change in workspace.changes) == (
        "impl-change:0001",
        "impl-change:0002",
    )
    update = workspace.changes[0]
    assert update.kind is ImplementationFileChangeKind.UPDATE
    assert update.source_blob_sha == "parser-blob"
    assert update.source_sha256 == hashlib.sha256(PARSER_CONTENT.encode()).hexdigest()
    assert update.proposed_content_sha256 == hashlib.sha256(parser_update.encode()).hexdigest()
    assert update.executed is False
    create = workspace.changes[1]
    assert create.kind is ImplementationFileChangeKind.CREATE
    assert create.source_blob_sha is None
    assert create.source_sha256 is None
    assert workspace.repository_mutation_executed is False
    assert workspace.human_merge_gate_required is True
    assert workspace.cisco_execution_allowed is False


def test_plan_only_can_describe_proposals_without_executing_mutation() -> None:
    workspace = _workspace(
        ImplementationFileChangeDraft(
            kind=ImplementationFileChangeKind.UPDATE,
            path=PARSER_PATH,
            proposed_content="def parse():\n    return 3\n",
            rationale="Describe an approved change without writing it.",
        )
    )

    assert workspace.repository_mutation_executed is False
    assert all(change.requires_repository_mutation for change in workspace.changes)
    assert all(change.executed is False for change in workspace.changes)


def test_update_requires_explicit_source_inspection_and_exact_context_blob() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)
    inspection = _inspection().model_copy(update={"files": (_inspection().files[1],)})
    draft = ImplementationFileChangeDraft(
        kind=ImplementationFileChangeKind.UPDATE,
        path=PARSER_PATH,
        proposed_content="def parse():\n    return 4\n",
        rationale="Update inspected source only.",
    )

    with pytest.raises(ImplementationWorkspaceError, match="source-inspected"):
        build_implementation_workspace(request, context, plan, inspection, (draft,))

    bad_file = _inspection().files[0].model_copy(update={"blob_sha": "other-blob"})
    bad_inspection = _inspection().model_copy(
        update={"files": (bad_file, _inspection().files[1])}
    )
    with pytest.raises(ImplementationWorkspaceError, match="source blob"):
        build_implementation_workspace(request, context, plan, bad_inspection, (draft,))


def test_create_must_be_new_and_update_must_change_content() -> None:
    with pytest.raises(ImplementationWorkspaceError, match="already exists"):
        _workspace(
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.CREATE,
                path=PARSER_PATH,
                proposed_content="new file\n",
                rationale="Invalid overwrite disguised as create.",
            )
        )

    with pytest.raises(ImplementationWorkspaceError, match="does not change"):
        _workspace(
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.UPDATE,
                path=PARSER_PATH,
                proposed_content=PARSER_CONTENT,
                rationale="No-op changes are not valid proposals.",
            )
        )


def test_workspace_rejects_scope_escape_raw_paths_and_unapproved_criteria() -> None:
    with pytest.raises(ImplementationWorkspaceError, match="authorized implementation scope"):
        _workspace(
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.CREATE,
                path="src/cisco_assessment/collector/escape.py",
                proposed_content="x = 1\n",
                rationale="Collector is prohibited.",
            )
        )

    with pytest.raises(ImplementationWorkspaceError, match="approved source-text"):
        _workspace(
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.CREATE,
                path="tests/fixtures/new.raw",
                proposed_content="switch#show example\n",
                rationale="RAW fixtures require their own evidence workflow.",
            )
        )

    with pytest.raises(ImplementationWorkspaceError, match="criteria not approved"):
        _workspace(
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.CREATE,
                path=NEW_TEST_PATH,
                proposed_content="def test_x():\n    assert True\n",
                rationale="Do not invent acceptance policy.",
                acceptance_criteria=("Invented policy passes.",),
            )
        )


def test_workspace_rejects_duplicate_or_noncanonical_paths() -> None:
    duplicate = ImplementationFileChangeDraft(
        kind=ImplementationFileChangeKind.CREATE,
        path=NEW_TEST_PATH,
        proposed_content="x = 1\n",
        rationale="Duplicate path.",
    )
    with pytest.raises(ImplementationWorkspaceError, match="paths must be unique"):
        _workspace(duplicate, duplicate)

    with pytest.raises(ImplementationWorkspaceError, match="canonical repository"):
        _workspace(
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.CREATE,
                path="tests/unit/parsers/../test_escape.py",
                proposed_content="x = 1\n",
                rationale="Path traversal is not canonical.",
            )
        )


def test_workspace_rejects_plan_or_inspection_from_different_base() -> None:
    request = _request()
    context = _context()
    plan = build_implementation_plan(request, context)
    draft = ImplementationFileChangeDraft(
        kind=ImplementationFileChangeKind.CREATE,
        path=NEW_TEST_PATH,
        proposed_content="x = 1\n",
        rationale="Base identity must remain exact.",
    )

    stale_plan = plan.model_copy(update={"base_sha": "stale-base"})
    with pytest.raises(ImplementationWorkspaceError, match="exact context base"):
        build_implementation_workspace(request, context, stale_plan, _inspection(), (draft,))

    stale_inspection = _inspection().model_copy(update={"base_sha": "stale-base"})
    with pytest.raises(ImplementationWorkspaceError, match="source inspection"):
        build_implementation_workspace(request, context, plan, stale_inspection, (draft,))


def test_proposed_change_model_rejects_hash_or_source_contract_forgery() -> None:
    with pytest.raises(ValidationError, match="source blob"):
        ImplementationProposedFileChange(
            ordinal=1,
            change_id="impl-change:0001",
            kind=ImplementationFileChangeKind.CREATE,
            path=NEW_TEST_PATH,
            component=ComponentId.TESTING_FIXTURES,
            source_blob_sha="forged",
            source_sha256="0" * 64,
            proposed_content_sha256=hashlib.sha256(b"x\n").hexdigest(),
            proposed_byte_size=2,
            proposed_content="x\n",
            rationale="Invalid source claim.",
        )

    with pytest.raises(ValidationError, match="proposed_content_sha256"):
        ImplementationProposedFileChange(
            ordinal=1,
            change_id="impl-change:0001",
            kind=ImplementationFileChangeKind.CREATE,
            path=NEW_TEST_PATH,
            component=ComponentId.TESTING_FIXTURES,
            proposed_content_sha256="0" * 64,
            proposed_byte_size=2,
            proposed_content="x\n",
            rationale="Invalid content hash.",
        )
