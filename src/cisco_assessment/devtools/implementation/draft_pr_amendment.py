"""Strict controlled amendment of one exact open Draft PR."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from ..pr_review import classify_changed_path
from ..pr_review.enums import ComponentId
from .ci_validation import (
    ImplementationCiBackend,
    ImplementationCiStatus,
    ImplementationCiValidationResult,
    validate_work_branch_ci,
)
from .enums import ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .mutation import (
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
    ImplementationMutationTreeEntry,
)
from .workspace import ImplementationProposedFileChange

WORK_BRANCH_PREFIX = "agent/implementation/"


class ImplementationDraftPrAmendmentError(RuntimeError):
    """Raised when an exact Draft PR amendment cannot fail closed."""


class ImplementationDraftPrAmendmentRequest(FrozenImplementationModel):
    """Authorization binding an amendment to one exact Draft PR and head."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    expected_head_sha: str = Field(min_length=1)
    commit_message: str = Field(min_length=1)
    authorized_components: tuple[ComponentId, ...] = Field(min_length=1)
    prohibited_components: tuple[ComponentId, ...] = ()
    changes: tuple[ImplementationProposedFileChange, ...] = Field(min_length=1)
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_contract(self) -> ImplementationDraftPrAmendmentRequest:
        if not self.work_branch.startswith(WORK_BRANCH_PREFIX):
            raise ValueError("amendment requires the implementation work-branch namespace")
        if self.work_branch == self.base_branch:
            raise ValueError("amendment work branch must differ from the base branch")
        if not self.commit_message.strip():
            raise ValueError("commit_message must not be blank")
        paths = tuple(change.path for change in self.changes)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("amendment paths must be unique and lexically ordered")
        allowed = set(self.authorized_components)
        prohibited = set(self.prohibited_components)
        for change in self.changes:
            observed = classify_changed_path(change.path)
            if observed is not change.component or observed not in allowed or observed in prohibited:
                raise ValueError(f"amendment path {change.path!r} is outside authorized scope")
        return self


class ImplementationDraftPrAmendmentBackend(Protocol):
    """Dedicated existing-ref amendment authority."""

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None: ...

    def get_pull_request(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object] | None: ...

    def list_tree(
        self, repository: str, commit_sha: str
    ) -> Sequence[Mapping[str, object]]: ...

    def get_blob(self, repository: str, blob_sha: str) -> bytes: ...

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]: ...

    def create_utf8_blob(self, repository: str, content: str) -> str: ...

    def create_tree(
        self,
        repository: str,
        base_tree_sha: str,
        entries: Sequence[ImplementationMutationTreeEntry],
    ) -> str: ...

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str: ...

    def update_work_branch(
        self,
        repository: str,
        branch: str,
        old_sha: str,
        new_sha: str,
    ) -> None: ...


class ImplementationDraftPrAmendmentResult(FrozenImplementationModel):
    """Verified old-head to new-head amendment and exact-head CI evidence."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    old_head_sha: str = Field(min_length=1)
    new_head_sha: str = Field(min_length=1)
    tree_sha: str = Field(min_length=1)
    changes: tuple[ImplementationMutationChangeResult, ...] = Field(min_length=1)
    ci: ImplementationCiValidationResult
    state: Literal["open"] = "open"
    draft: Literal[True] = True
    merged: Literal[False] = False
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


def amend_implementation_draft_pr(
    request: ImplementationDraftPrAmendmentRequest,
    backend: ImplementationDraftPrAmendmentBackend,
    ci_backend: ImplementationCiBackend,
) -> ImplementationDraftPrAmendmentResult:
    """Amend one exact Draft PR, dispatch exact-head CI, and stop."""
    request = ImplementationDraftPrAmendmentRequest.model_validate(
        request.model_dump(mode="python")
    )
    pr = backend.get_pull_request(request.repository, request.pr_number)
    _require_pr(pr, request, request.expected_head_sha)
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _require_branch(
        backend, request.repository, request.work_branch, request.expected_head_sha
    )

    entries = tuple(backend.list_tree(request.repository, request.expected_head_sha))
    blobs = _blob_entries(entries)
    all_paths = {_required_string(item, "path", "tree entry") for item in entries}
    commit = backend.get_commit(request.repository, request.expected_head_sha)
    base_tree_sha = _tree_sha(commit, request.expected_head_sha)
    staged: list[tuple[ImplementationProposedFileChange, str]] = []
    tree_entries: list[ImplementationMutationTreeEntry] = []

    for change in request.changes:
        current = blobs.get(change.path)
        if change.kind is ImplementationFileChangeKind.CREATE:
            if change.path in all_paths:
                raise ImplementationDraftPrAmendmentError(
                    f"CREATE path {change.path!r} exists"
                )
        elif current is None or current[0] != change.source_blob_sha or current[1] != "100644":
            raise ImplementationDraftPrAmendmentError(
                f"UPDATE path {change.path!r} does not match the expected head tree"
            )

        blob_sha = backend.create_utf8_blob(request.repository, change.proposed_content)
        expected_content = change.proposed_content.encode("utf-8")
        if backend.get_blob(request.repository, blob_sha) != expected_content:
            raise ImplementationDraftPrAmendmentError("created blob read-back mismatch")
        staged.append((change, blob_sha))
        tree_entries.append(
            ImplementationMutationTreeEntry(path=change.path, blob_sha=blob_sha)
        )

    tree_sha = backend.create_tree(request.repository, base_tree_sha, tuple(tree_entries))
    new_sha = backend.create_commit(
        request.repository,
        message=request.commit_message,
        tree_sha=tree_sha,
        parent_sha=request.expected_head_sha,
    )
    _verify_commit(
        backend.get_commit(request.repository, new_sha),
        new_sha,
        tree_sha,
        request.expected_head_sha,
    )

    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _require_branch(
        backend, request.repository, request.work_branch, request.expected_head_sha
    )
    _require_pr(
        backend.get_pull_request(request.repository, request.pr_number),
        request,
        request.expected_head_sha,
    )
    backend.update_work_branch(
        request.repository,
        request.work_branch,
        request.expected_head_sha,
        new_sha,
    )

    _require_branch(backend, request.repository, request.work_branch, new_sha)
    _require_pr(
        backend.get_pull_request(request.repository, request.pr_number), request, new_sha
    )
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _verify_commit(
        backend.get_commit(request.repository, new_sha),
        new_sha,
        tree_sha,
        request.expected_head_sha,
    )

    results = tuple(
        ImplementationMutationChangeResult(
            ordinal=change.ordinal,
            change_id=change.change_id,
            kind=change.kind,
            path=change.path,
            source_blob_sha=change.source_blob_sha,
            published_blob_sha=blob_sha,
            proposed_content_sha256=hashlib.sha256(
                change.proposed_content.encode("utf-8")
            ).hexdigest(),
        )
        for change, blob_sha in staged
    )
    canonical_request = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    mutation = ImplementationMutationResult(
        repository=request.repository,
        base_branch=request.base_branch,
        base_sha=request.base_sha,
        workspace_sha256=hashlib.sha256(canonical_request).hexdigest(),
        work_branch=request.work_branch,
        commit_sha=new_sha,
        tree_sha=tree_sha,
        changes=results,
        base_head_after_publish=request.base_sha,
        base_fresh_after_publish=True,
    )
    ci = validate_work_branch_ci(mutation, ci_backend)
    if ci.ci_status is not ImplementationCiStatus.PASSED or ci.commit_sha != new_sha:
        raise ImplementationDraftPrAmendmentError(
            "fresh ci.yml did not pass on the exact new head"
        )
    _require_pr(
        backend.get_pull_request(request.repository, request.pr_number), request, new_sha
    )
    return ImplementationDraftPrAmendmentResult(
        repository=request.repository,
        pr_number=request.pr_number,
        base_branch=request.base_branch,
        base_sha=request.base_sha,
        work_branch=request.work_branch,
        old_head_sha=request.expected_head_sha,
        new_head_sha=new_sha,
        tree_sha=tree_sha,
        changes=results,
        ci=ci,
    )


def _require_pr(
    payload: Mapping[str, object] | None,
    request: ImplementationDraftPrAmendmentRequest,
    head_sha: str,
) -> None:
    if payload is None:
        raise ImplementationDraftPrAmendmentError("pull request is missing")
    if (
        payload.get("state") != "open"
        or payload.get("draft") is not True
        or payload.get("merged") is not False
    ):
        raise ImplementationDraftPrAmendmentError(
            "pull request must be open, Draft, and unmerged"
        )
    if payload.get("number") != request.pr_number:
        raise ImplementationDraftPrAmendmentError("pull request identity mismatch")
    base = _required_mapping(payload, "base", "pull request")
    head = _required_mapping(payload, "head", "pull request")
    if (
        _required_string(base, "ref", "PR base") != request.base_branch
        or _required_string(base, "sha", "PR base") != request.base_sha
    ):
        raise ImplementationDraftPrAmendmentError("pull request base drifted")
    if (
        _required_string(head, "ref", "PR head") != request.work_branch
        or _required_string(head, "sha", "PR head") != head_sha
    ):
        raise ImplementationDraftPrAmendmentError("pull request head drifted")


def _require_branch(
    backend: ImplementationDraftPrAmendmentBackend,
    repository: str,
    branch: str,
    expected: str,
) -> None:
    payload = backend.get_branch(repository, branch)
    if payload is None:
        raise ImplementationDraftPrAmendmentError(f"branch {branch!r} is missing")
    commit = _required_mapping(payload, "commit", "branch")
    if _required_string(commit, "sha", "branch commit") != expected:
        raise ImplementationDraftPrAmendmentError(f"branch {branch!r} drifted")


def _verify_commit(
    payload: Mapping[str, object], sha: str, tree: str, parent: str
) -> None:
    if _required_string(payload, "sha", "commit") != sha:
        raise ImplementationDraftPrAmendmentError("commit identity mismatch")
    if _tree_sha(payload, sha) != tree:
        raise ImplementationDraftPrAmendmentError("commit tree read-back mismatch")
    parents = payload.get("parents")
    if (
        not isinstance(parents, Sequence)
        or isinstance(parents, (str, bytes))
        or len(parents) != 1
    ):
        raise ImplementationDraftPrAmendmentError(
            "amendment commit must have one parent"
        )
    item = parents[0]
    if not isinstance(item, Mapping) or item.get("sha") != parent:
        raise ImplementationDraftPrAmendmentError("amendment commit parent mismatch")


def _tree_sha(payload: Mapping[str, object], sha: str) -> str:
    if _required_string(payload, "sha", "commit") != sha:
        raise ImplementationDraftPrAmendmentError("commit identity mismatch")
    tree = _required_mapping(payload, "tree", "commit")
    return _required_string(tree, "sha", "commit tree")


def _blob_entries(
    entries: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for item in entries:
        if item.get("type") != "blob":
            continue
        path = _required_string(item, "path", "tree entry")
        result[path] = (
            _required_string(item, "sha", f"tree entry {path!r}"),
            _required_string(item, "mode", f"tree entry {path!r}"),
        )
    return result


def _required_mapping(
    value: Mapping[str, object], key: str, context: str
) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise ImplementationDraftPrAmendmentError(f"{context} has no valid {key}")
    return cast(Mapping[str, object], item)


def _required_string(value: Mapping[str, object], key: str, context: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ImplementationDraftPrAmendmentError(f"{context} has no valid {key}")
    return item
