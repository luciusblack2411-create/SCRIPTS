from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import pytest

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationAuthorization,
    ImplementationContext,
    ImplementationContextFile,
    ImplementationFileChangeDraft,
    ImplementationFileChangeKind,
    ImplementationMutationError,
    ImplementationMutationTreeEntry,
    ImplementationRequest,
    ImplementationSourceFile,
    ImplementationSourceInspection,
    build_implementation_plan,
    build_implementation_workspace,
    execute_work_branch_mutation,
)

PARSER_PATH = "src/cisco_assessment/parsers/example.py"
TEST_PATH = "tests/unit/parsers/test_example.py"
NEW_TEST_PATH = "tests/unit/parsers/test_example_regression.py"
PARSER_CONTENT = "def parse():\n    return 1\n"
TEST_CONTENT = "def test_parse():\n    assert True\n"
PARSER_UPDATE = "def parse():\n    return 2\n"
NEW_TEST = "def test_regression():\n    assert True\n"
BASE_SHA = "base-123"
BASE_TREE_SHA = "tree-base"
WORK_BRANCH = "agent/implementation/parser-example-v0-1"


class FakeMutationBackend:
    def __init__(self) -> None:
        self.branches: dict[str, str] = {"main": BASE_SHA}
        self.blobs: dict[str, bytes] = {
            "parser-blob": PARSER_CONTENT.encode(),
            "test-blob": TEST_CONTENT.encode(),
        }
        self.trees: dict[str, tuple[dict[str, object], ...]] = {
            BASE_SHA: (
                {
                    "path": PARSER_PATH,
                    "type": "blob",
                    "sha": "parser-blob",
                    "mode": "100644",
                    "size": len(PARSER_CONTENT.encode()),
                },
                {
                    "path": TEST_PATH,
                    "type": "blob",
                    "sha": "test-blob",
                    "mode": "100644",
                    "size": len(TEST_CONTENT.encode()),
                },
            )
        }
        self.tree_roots: dict[str, str] = {BASE_SHA: BASE_TREE_SHA}
        self.created_tree_entries: dict[str, tuple[ImplementationMutationTreeEntry, ...]] = {}
        self.mutation_calls: list[str] = []
        self.advance_before_publish = False
        self.advance_after_publish = False

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        del repository
        sha = self.branches.get(branch)
        return None if sha is None else {"commit": {"sha": sha}}

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        del repository
        return self.trees[commit_sha]

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        del repository
        return self.tree_roots[commit_sha]

    def create_utf8_blob(self, repository: str, content: str) -> str:
        del repository
        self.mutation_calls.append("create_blob")
        sha = f"new-blob-{len(self.blobs)}"
        self.blobs[sha] = content.encode("utf-8")
        return sha

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        del repository
        return self.blobs[blob_sha]

    def create_tree(
        self,
        repository: str,
        base_tree_sha: str,
        entries: Sequence[ImplementationMutationTreeEntry],
    ) -> str:
        del repository
        assert base_tree_sha == BASE_TREE_SHA
        self.mutation_calls.append("create_tree")
        tree_sha = "tree-new"
        self.created_tree_entries[tree_sha] = tuple(entries)
        return tree_sha

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str:
        del repository
        assert message == "feat: apply approved parser change"
        assert parent_sha == BASE_SHA
        self.mutation_calls.append("create_commit")
        commit_sha = "commit-new"
        base = {str(item["path"]): dict(item) for item in self.trees[BASE_SHA]}
        for entry in self.created_tree_entries[tree_sha]:
            base[entry.path] = {
                "path": entry.path,
                "type": "blob",
                "sha": entry.blob_sha,
                "mode": entry.mode,
            }
        self.trees[commit_sha] = tuple(base[path] for path in sorted(base))
        self.tree_roots[commit_sha] = tree_sha
        if self.advance_before_publish:
            self.branches["main"] = "advanced-main"
        return commit_sha

    def create_branch(self, repository: str, branch: str, commit_sha: str) -> None:
        del repository
        self.mutation_calls.append("create_branch")
        assert branch != "main"
        assert branch not in self.branches
        self.branches[branch] = commit_sha
        if self.advance_after_publish:
            self.branches["main"] = "advanced-main"


def _request(
    authorization: ImplementationAuthorization = ImplementationAuthorization.WORK_BRANCH,
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
        base_sha=BASE_SHA,
        files=(
            ImplementationContextFile(
                path=PARSER_PATH,
                component=ComponentId.PARSER,
                blob_sha="parser-blob",
                size=len(PARSER_CONTENT.encode()),
            ),
            ImplementationContextFile(
                path=TEST_PATH,
                component=ComponentId.TESTING_FIXTURES,
                blob_sha="test-blob",
                size=len(TEST_CONTENT.encode()),
            ),
        ),
        observed_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
    )


def _inspection() -> ImplementationSourceInspection:
    parser_bytes = PARSER_CONTENT.encode()
    test_bytes = TEST_CONTENT.encode()
    return ImplementationSourceInspection(
        repository="owner/repo",
        base_sha=BASE_SHA,
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


def _workspace(
    authorization: ImplementationAuthorization = ImplementationAuthorization.WORK_BRANCH,
):
    request = _request(authorization)
    context = _context()
    plan = build_implementation_plan(request, context)
    workspace = build_implementation_workspace(
        request,
        context,
        plan,
        _inspection(),
        (
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.CREATE,
                path=NEW_TEST_PATH,
                proposed_content=NEW_TEST,
                rationale="Add the approved regression test.",
                acceptance_criteria=("Regression tests pass.",),
            ),
            ImplementationFileChangeDraft(
                kind=ImplementationFileChangeKind.UPDATE,
                path=PARSER_PATH,
                proposed_content=PARSER_UPDATE,
                rationale="Apply the approved parser change.",
                acceptance_criteria=("Evidence paths remain stable.",),
            ),
        ),
    )
    return request, workspace


def _execute(backend: FakeMutationBackend):
    request, workspace = _workspace()
    return execute_work_branch_mutation(
        request,
        workspace,
        backend,
        work_branch=WORK_BRANCH,
        commit_message="feat: apply approved parser change",
    )


def test_executor_publishes_exact_workspace_to_new_work_branch() -> None:
    backend = FakeMutationBackend()
    result = _execute(backend)

    assert result.work_branch == WORK_BRANCH
    assert result.commit_sha == "commit-new"
    assert result.base_sha == BASE_SHA
    assert result.base_fresh_after_publish is True
    assert result.repository_mutation_executed is True
    assert result.pull_request_created is False
    assert result.merge_performed is False
    assert result.human_merge_gate_required is True
    assert result.cisco_execution_allowed is False
    assert backend.branches["main"] == BASE_SHA
    assert backend.branches[WORK_BRANCH] == "commit-new"
    assert backend.mutation_calls == [
        "create_blob",
        "create_blob",
        "create_tree",
        "create_commit",
        "create_branch",
    ]
    assert tuple(item.path for item in result.changes) == (PARSER_PATH, NEW_TEST_PATH)
    assert result.changes[0].source_blob_sha == "parser-blob"
    assert result.changes[1].source_blob_sha is None


def test_executor_requires_work_branch_authorization_exactly() -> None:
    backend = FakeMutationBackend()
    for authorization in (
        ImplementationAuthorization.PLAN_ONLY,
        ImplementationAuthorization.DRAFT_PR,
    ):
        request, workspace = _workspace(authorization)
        with pytest.raises(ImplementationMutationError, match="WORK_BRANCH authorization"):
            execute_work_branch_mutation(
                request,
                workspace,
                backend,
                work_branch=WORK_BRANCH,
                commit_message="feat: apply approved parser change",
            )
    assert backend.mutation_calls == []


def test_executor_rejects_stale_base_before_any_write() -> None:
    backend = FakeMutationBackend()
    backend.branches["main"] = "advanced-main"

    with pytest.raises(ImplementationMutationError, match="branch 'main' moved"):
        _execute(backend)

    assert backend.mutation_calls == []
    assert WORK_BRANCH not in backend.branches


def test_executor_rejects_existing_work_branch_before_any_write() -> None:
    backend = FakeMutationBackend()
    backend.branches[WORK_BRANCH] = BASE_SHA

    with pytest.raises(ImplementationMutationError, match="already exists"):
        _execute(backend)

    assert backend.mutation_calls == []


def test_executor_revalidates_update_blob_and_regular_file_mode() -> None:
    backend = FakeMutationBackend()
    bad = [dict(item) for item in backend.trees[BASE_SHA]]
    bad[0]["sha"] = "other-blob"
    backend.trees[BASE_SHA] = tuple(bad)
    with pytest.raises(ImplementationMutationError, match="source blob"):
        _execute(backend)
    assert backend.mutation_calls == []

    backend = FakeMutationBackend()
    bad = [dict(item) for item in backend.trees[BASE_SHA]]
    bad[0]["mode"] = "100755"
    backend.trees[BASE_SHA] = tuple(bad)
    with pytest.raises(ImplementationMutationError, match="non-executable"):
        _execute(backend)
    assert backend.mutation_calls == []


def test_executor_rejects_create_path_that_appears_in_base_tree() -> None:
    backend = FakeMutationBackend()
    backend.trees[BASE_SHA] = backend.trees[BASE_SHA] + (
        {
            "path": NEW_TEST_PATH,
            "type": "blob",
            "sha": "unexpected",
            "mode": "100644",
        },
    )

    with pytest.raises(ImplementationMutationError, match="already exists"):
        _execute(backend)
    assert backend.mutation_calls == []


def test_executor_rechecks_base_immediately_before_ref_publish() -> None:
    backend = FakeMutationBackend()
    backend.advance_before_publish = True

    with pytest.raises(ImplementationMutationError, match="branch 'main' moved"):
        _execute(backend)

    assert "create_commit" in backend.mutation_calls
    assert "create_branch" not in backend.mutation_calls
    assert WORK_BRANCH not in backend.branches


def test_executor_records_base_advance_after_publish_for_followup_gate() -> None:
    backend = FakeMutationBackend()
    backend.advance_after_publish = True

    result = _execute(backend)

    assert result.base_head_after_publish == "advanced-main"
    assert result.base_fresh_after_publish is False
    assert backend.branches[WORK_BRANCH] == "commit-new"


def test_executor_rejects_non_dedicated_or_noncanonical_branch_names() -> None:
    request, workspace = _workspace()
    backend = FakeMutationBackend()
    for branch in ("main", "feature/x", "agent/implementation/../x", "agent/implementation/a b"):
        with pytest.raises(ImplementationMutationError):
            execute_work_branch_mutation(
                request,
                workspace,
                backend,
                work_branch=branch,
                commit_message="feat: apply approved parser change",
            )
    assert backend.mutation_calls == []
