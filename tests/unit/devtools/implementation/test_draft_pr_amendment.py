from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from cisco_assessment.devtools.implementation.draft_pr_amendment import ImplementationDraftPrAmendmentChange, ImplementationDraftPrAmendmentError, ImplementationDraftPrAmendmentOperation, execute_draft_pr_amendment
from cisco_assessment.devtools.implementation.enums import ImplementationFileChangeKind

OLD, NEW, BASE = "old-head", "new-head", "base-head"
BRANCH = "agent/implementation/example"


class Backend:
    def __init__(self) -> None:
        self.base = BASE
        self.head = OLD
        self.pr: Mapping[str, object] | None = self.payload()
        self.parent: str | None = None
        self.base_tree_arg: str | None = None
        self.race = False

    def payload(self) -> Mapping[str, object]:
        return {"state": "open", "draft": True, "merged": False, "base": {"ref": "main", "sha": self.base}, "head": {"ref": BRANCH, "sha": self.head}}

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None:
        del repository, pr_number
        return self.pr if self.pr is None else self.payload()

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        del repository
        return {"commit": {"sha": self.base if branch == "main" else self.head}}

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        del repository
        assert commit_sha == OLD
        return ({"path": "pyproject.toml", "type": "blob", "sha": "old-blob", "mode": "100644"},)

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        del repository
        assert commit_sha == OLD
        return "old-tree"

    def create_utf8_blob(self, repository: str, content: str) -> str:
        del repository, content
        return "new-blob"

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        del repository, blob_sha
        return b"updated\n"

    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[object]) -> str:
        del repository, entries
        self.base_tree_arg = base_tree_sha
        return "new-tree"

    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str:
        del repository, message, tree_sha
        self.parent = parent_sha
        return NEW

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        del repository
        return {"sha": commit_sha, "tree": {"sha": "new-tree"}, "parents": [{"sha": OLD}]}

    def advance_branch(self, repository: str, branch: str, *, old_sha: str, new_sha: str) -> None:
        del repository, branch
        if self.race:
            raise ImplementationDraftPrAmendmentError("race")
        assert old_sha == OLD
        self.head = new_sha


def operation(path: str = "pyproject.toml") -> ImplementationDraftPrAmendmentOperation:
    return ImplementationDraftPrAmendmentOperation(repository="owner/repo", pr_number=7, base_branch="main", base_sha=BASE, work_branch=BRANCH, expected_head_sha=OLD, authorization="DRAFT_PR_AMENDMENT", authorized_components=("CI_TOOLING",), prohibited_components=("ARCHITECTURE",), changes=(ImplementationDraftPrAmendmentChange(kind=ImplementationFileChangeKind.UPDATE, path=path, component="CI_TOOLING", proposed_content="updated\n", source_blob_sha="old-blob"),), commit_message="fix: amend Draft PR")


def test_success_uses_exact_head_tree_and_sole_parent() -> None:
    backend = Backend()
    result = execute_draft_pr_amendment(operation(), backend)
    assert backend.base_tree_arg == "old-tree"
    assert backend.parent == OLD
    assert (result.old_head_sha, result.new_head_sha) == (OLD, NEW)
    assert result.ready_for_review is False and result.merge_performed is False


def test_missing_or_non_draft_pr_is_rejected() -> None:
    backend = Backend()
    backend.pr = None
    with pytest.raises(ImplementationDraftPrAmendmentError, match="missing"):
        execute_draft_pr_amendment(operation(), backend)
    backend = Backend()
    backend.payload = lambda: {"state": "open", "draft": False, "merged": False, "base": {"ref": "main", "sha": BASE}, "head": {"ref": BRANCH, "sha": OLD}}
    with pytest.raises(ImplementationDraftPrAmendmentError, match="Draft"):
        execute_draft_pr_amendment(operation(), backend)


def test_stale_head_and_base_drift_are_rejected_before_writes() -> None:
    backend = Backend()
    backend.head = "stale"
    with pytest.raises(ImplementationDraftPrAmendmentError):
        execute_draft_pr_amendment(operation(), backend)
    backend = Backend()
    backend.base = "advanced"
    with pytest.raises(ImplementationDraftPrAmendmentError):
        execute_draft_pr_amendment(operation(), backend)


def test_unauthorized_path_is_rejected() -> None:
    with pytest.raises(ImplementationDraftPrAmendmentError, match="outside"):
        execute_draft_pr_amendment(operation("README.md"), Backend())


def test_concurrent_ref_race_fails_closed() -> None:
    backend = Backend()
    backend.race = True
    with pytest.raises(ImplementationDraftPrAmendmentError, match="race"):
        execute_draft_pr_amendment(operation(), backend)
    assert backend.head == OLD
