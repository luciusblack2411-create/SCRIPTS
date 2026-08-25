"""Fail-closed amendment of one exact existing Implementation Draft PR."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from ..pr_review import classify_changed_path
from .enums import ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .mutation import ImplementationMutationTreeEntry

WORK_BRANCH_PREFIX = "agent/implementation/"
AMENDMENT_AUTHORIZATION: Literal["DRAFT_PR_AMENDMENT"] = "DRAFT_PR_AMENDMENT"


class ImplementationDraftPrAmendmentError(RuntimeError):
    """Raised when an exact Draft PR amendment cannot proceed safely."""


class ImplementationDraftPrAmendmentChange(FrozenImplementationModel):
    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    component: str = Field(min_length=1)
    proposed_content: str
    source_blob_sha: str | None = None


class ImplementationDraftPrAmendmentOperation(FrozenImplementationModel):
    """Frozen authorization bound to one repository state and exact proposed changes."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    expected_head_sha: str = Field(min_length=1)
    authorization: Literal["DRAFT_PR_AMENDMENT"]
    authorized_components: tuple[str, ...] = Field(min_length=1)
    prohibited_components: tuple[str, ...] = ()
    changes: tuple[ImplementationDraftPrAmendmentChange, ...] = Field(min_length=1)
    commit_message: str = Field(min_length=1)
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_contract(self) -> ImplementationDraftPrAmendmentOperation:
        if not self.work_branch.startswith(WORK_BRANCH_PREFIX) or self.work_branch == self.base_branch:
            raise ValueError("amendment work branch must use the implementation namespace")
        if not self.commit_message.strip():
            raise ValueError("commit_message must not be blank")
        paths = tuple(change.path for change in self.changes)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("amendment paths must be unique and lexically ordered")
        return self


class ImplementationDraftPrAmendmentBackend(Protocol):
    """Dedicated existing-PR/ref authority; separate from ImplementationMutationBackend."""

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None: ...
    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None: ...
    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]: ...
    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]: ...
    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str: ...
    def create_utf8_blob(self, repository: str, content: str) -> str: ...
    def get_blob(self, repository: str, blob_sha: str) -> bytes: ...
    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[ImplementationMutationTreeEntry]) -> str: ...
    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str: ...
    def advance_branch(self, repository: str, branch: str, *, old_sha: str, new_sha: str) -> None: ...


class ImplementationDraftPrAmendmentResult(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str
    pr_number: int
    base_branch: str
    base_sha: str
    work_branch: str
    old_head_sha: str
    new_head_sha: str
    tree_sha: str
    changed_paths: tuple[str, ...]
    state: Literal["open"] = "open"
    draft: Literal[True] = True
    merged: Literal[False] = False
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


def execute_draft_pr_amendment(operation: ImplementationDraftPrAmendmentOperation, backend: ImplementationDraftPrAmendmentBackend) -> ImplementationDraftPrAmendmentResult:
    op = ImplementationDraftPrAmendmentOperation.model_validate(operation.model_dump(mode="python"))
    _validate_scope(op)
    _require_state(op, backend)
    entries = tuple(backend.list_tree(op.repository, op.expected_head_sha))
    blobs = _blob_entries(entries)
    tree_entries: list[ImplementationMutationTreeEntry] = []
    for change in op.changes:
        current = blobs.get(change.path)
        if change.kind is ImplementationFileChangeKind.CREATE:
            if current is not None:
                raise ImplementationDraftPrAmendmentError(f"CREATE path {change.path!r} exists")
        elif current is None or current != (change.source_blob_sha, "100644"):
            raise ImplementationDraftPrAmendmentError(f"UPDATE path {change.path!r} does not match expected head")
        blob_sha = backend.create_utf8_blob(op.repository, change.proposed_content)
        if backend.get_blob(op.repository, blob_sha) != change.proposed_content.encode("utf-8"):
            raise ImplementationDraftPrAmendmentError("created blob failed read-back")
        tree_entries.append(ImplementationMutationTreeEntry(path=change.path, blob_sha=blob_sha))
    base_tree = backend.get_commit_tree_sha(op.repository, op.expected_head_sha)
    tree_sha = backend.create_tree(op.repository, base_tree, tuple(tree_entries))
    new_sha = backend.create_commit(repository=op.repository, message=op.commit_message, tree_sha=tree_sha, parent_sha=op.expected_head_sha)
    _verify_commit(backend.get_commit(op.repository, new_sha), new_sha, tree_sha, op.expected_head_sha)
    _require_state(op, backend)
    backend.advance_branch(op.repository, op.work_branch, old_sha=op.expected_head_sha, new_sha=new_sha)
    _require_branch(backend.get_branch(op.repository, op.work_branch), op.work_branch, new_sha)
    _verify_commit(backend.get_commit(op.repository, new_sha), new_sha, tree_sha, op.expected_head_sha)
    pr = backend.get_pull_request(op.repository, op.pr_number)
    _validate_pr(pr, op, new_sha)
    return ImplementationDraftPrAmendmentResult(repository=op.repository, pr_number=op.pr_number, base_branch=op.base_branch, base_sha=op.base_sha, work_branch=op.work_branch, old_head_sha=op.expected_head_sha, new_head_sha=new_sha, tree_sha=tree_sha, changed_paths=tuple(change.path for change in op.changes))


def _validate_scope(op: ImplementationDraftPrAmendmentOperation) -> None:
    allowed, prohibited = set(op.authorized_components), set(op.prohibited_components)
    for change in op.changes:
        observed = classify_changed_path(change.path).value
        if observed != change.component or observed not in allowed or observed in prohibited:
            raise ImplementationDraftPrAmendmentError(f"path {change.path!r} is outside authorized components")


def _require_state(op: ImplementationDraftPrAmendmentOperation, backend: ImplementationDraftPrAmendmentBackend) -> None:
    _validate_pr(backend.get_pull_request(op.repository, op.pr_number), op, op.expected_head_sha)
    _require_branch(backend.get_branch(op.repository, op.base_branch), op.base_branch, op.base_sha)
    _require_branch(backend.get_branch(op.repository, op.work_branch), op.work_branch, op.expected_head_sha)


def _validate_pr(payload: Mapping[str, object] | None, op: ImplementationDraftPrAmendmentOperation, head_sha: str) -> None:
    if payload is None:
        raise ImplementationDraftPrAmendmentError("pull request is missing")
    if payload.get("state") != "open" or payload.get("draft") is not True or payload.get("merged") is not False:
        raise ImplementationDraftPrAmendmentError("pull request must be open, Draft, and unmerged")
    base, head = _mapping(payload, "base"), _mapping(payload, "head")
    if base.get("ref") != op.base_branch or base.get("sha") != op.base_sha:
        raise ImplementationDraftPrAmendmentError("pull request base drifted")
    if head.get("ref") != op.work_branch or head.get("sha") != head_sha:
        raise ImplementationDraftPrAmendmentError("pull request head is stale or inconsistent")


def _require_branch(payload: Mapping[str, object] | None, name: str, sha: str) -> None:
    if payload is None or _mapping(payload, "commit").get("sha") != sha:
        raise ImplementationDraftPrAmendmentError(f"branch {name!r} moved or is missing")


def _verify_commit(payload: Mapping[str, object], sha: str, tree_sha: str, parent_sha: str) -> None:
    parents = payload.get("parents")
    if payload.get("sha") != sha or _mapping(payload, "tree").get("sha") != tree_sha or not isinstance(parents, Sequence) or isinstance(parents, (str, bytes)) or len(parents) != 1 or not isinstance(parents[0], Mapping) or parents[0].get("sha") != parent_sha:
        raise ImplementationDraftPrAmendmentError("published commit/tree/sole-parent evidence is inconsistent")


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ImplementationDraftPrAmendmentError(f"payload has no valid {key}")
    return cast(Mapping[str, object], value)


def _blob_entries(entries: Sequence[Mapping[str, object]]) -> dict[str, tuple[str, str]]:
    return {str(item["path"]): (str(item["sha"]), str(item["mode"])) for item in entries if item.get("type") == "blob"}
