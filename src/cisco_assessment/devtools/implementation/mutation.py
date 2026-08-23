"""Controlled work-branch repository mutation for Implementation Agent v0.1."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from ..pr_review import classify_changed_path
from .enums import ImplementationAuthorization, ImplementationDecision, ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel, ImplementationRequest
from .readiness import evaluate_implementation_readiness
from .workspace import ImplementationProposedFileChange, ImplementationWorkspace


class ImplementationMutationError(RuntimeError):
    """Raised when a controlled work-branch mutation cannot proceed safely."""


class ImplementationMutationTreeEntry(FrozenImplementationModel):
    """One regular-file tree entry staged for the dedicated work branch."""

    path: str = Field(min_length=1)
    mode: Literal["100644"] = "100644"
    blob_sha: str = Field(min_length=1)


class ImplementationMutationBackend(Protocol):
    """Repository operations exposed to the v0.1 work-branch executor only."""

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Observe one branch without mutation."""
        ...

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        """Observe a complete recursive tree for one exact commit."""
        ...

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        """Return the root tree SHA for one exact commit."""
        ...

    def create_utf8_blob(self, repository: str, content: str) -> str:
        """Stage one UTF-8 blob and return its Git object SHA."""
        ...

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        """Read back one exact blob for post-stage verification."""
        ...

    def create_tree(
        self,
        repository: str,
        base_tree_sha: str,
        entries: Sequence[ImplementationMutationTreeEntry],
    ) -> str:
        """Create one tree derived from the exact base tree."""
        ...

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str:
        """Create one commit with the exact implementation base as sole parent."""
        ...

    def create_branch(self, repository: str, branch: str, commit_sha: str) -> None:
        """Publish a new dedicated branch ref; existing refs must not be moved."""
        ...


class ImplementationMutationChangeResult(FrozenImplementationModel):
    """One proposed change verified in the published work-branch commit."""

    ordinal: int = Field(gt=0)
    change_id: str = Field(min_length=1)
    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    source_blob_sha: str | None = None
    published_blob_sha: str = Field(min_length=1)
    proposed_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified: Literal[True] = True


class ImplementationMutationResult(FrozenImplementationModel):
    """Canonical evidence that an approved workspace was published to a work branch."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    workspace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    tree_sha: str = Field(min_length=1)
    changes: tuple[ImplementationMutationChangeResult, ...] = Field(min_length=1)
    base_head_after_publish: str = Field(min_length=1)
    base_fresh_after_publish: bool
    repository_mutation_executed: Literal[True] = True
    pull_request_created: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_change_order(self) -> ImplementationMutationResult:
        ordinals = tuple(item.ordinal for item in self.changes)
        if ordinals != tuple(range(1, len(self.changes) + 1)):
            raise ValueError("mutation change ordinals must be contiguous from 1")
        return self


def execute_work_branch_mutation(
    request: ImplementationRequest,
    workspace: ImplementationWorkspace,
    backend: ImplementationMutationBackend,
    *,
    work_branch: str,
    commit_message: str,
) -> ImplementationMutationResult:
    """Publish approved CREATE/UPDATE proposals to a new work branch and nowhere else."""
    request = ImplementationRequest.model_validate(request.model_dump(mode="python"))
    workspace = ImplementationWorkspace.model_validate(workspace.model_dump(mode="python"))
    _validate_execution_contract(request, workspace, work_branch, commit_message)

    repository = request.repository
    base_sha = workspace.base_sha
    _require_branch_sha(backend.get_branch(repository, workspace.base_branch), workspace.base_branch, base_sha)
    if backend.get_branch(repository, work_branch) is not None:
        raise ImplementationMutationError(f"work branch {work_branch!r} already exists")

    base_entries = tuple(backend.list_tree(repository, base_sha))
    _validate_base_tree(workspace, base_entries)
    base_tree_sha = backend.get_commit_tree_sha(repository, base_sha)

    staged: list[tuple[ImplementationProposedFileChange, str]] = []
    tree_entries: list[ImplementationMutationTreeEntry] = []
    for change in workspace.changes:
        blob_sha = backend.create_utf8_blob(repository, change.proposed_content)
        observed = backend.get_blob(repository, blob_sha)
        expected = change.proposed_content.encode("utf-8")
        if observed != expected:
            raise ImplementationMutationError(
                f"staged blob for {change.path!r} does not match approved proposed content"
            )
        staged.append((change, blob_sha))
        tree_entries.append(ImplementationMutationTreeEntry(path=change.path, blob_sha=blob_sha))

    tree_sha = backend.create_tree(repository, base_tree_sha, tuple(tree_entries))
    commit_sha = backend.create_commit(
        repository,
        message=commit_message,
        tree_sha=tree_sha,
        parent_sha=base_sha,
    )

    # Re-check immediately before publishing the branch ref. Staged Git objects may exist,
    # but no repository ref is published when the approved base has advanced.
    _require_branch_sha(backend.get_branch(repository, workspace.base_branch), workspace.base_branch, base_sha)
    if backend.get_branch(repository, work_branch) is not None:
        raise ImplementationMutationError(f"work branch {work_branch!r} appeared before publish")

    backend.create_branch(repository, work_branch, commit_sha)
    _require_branch_sha(backend.get_branch(repository, work_branch), work_branch, commit_sha)

    published_entries = _blob_entries(backend.list_tree(repository, commit_sha))
    results: list[ImplementationMutationChangeResult] = []
    for change, blob_sha in staged:
        published = published_entries.get(change.path)
        if published is None or published[0] != blob_sha or published[1] != "100644":
            raise ImplementationMutationError(
                f"published tree for {change.path!r} does not match staged regular-file blob"
            )
        results.append(
            ImplementationMutationChangeResult(
                ordinal=change.ordinal,
                change_id=change.change_id,
                kind=change.kind,
                path=change.path,
                source_blob_sha=change.source_blob_sha,
                published_blob_sha=blob_sha,
                proposed_content_sha256=change.proposed_content_sha256,
            )
        )

    base_after = _observed_branch_sha(
        backend.get_branch(repository, workspace.base_branch), workspace.base_branch
    )
    return ImplementationMutationResult(
        repository=repository,
        base_branch=workspace.base_branch,
        base_sha=base_sha,
        workspace_sha256=_workspace_sha256(workspace),
        work_branch=work_branch,
        commit_sha=commit_sha,
        tree_sha=tree_sha,
        changes=tuple(results),
        base_head_after_publish=base_after,
        base_fresh_after_publish=base_after == base_sha,
    )


def _validate_execution_contract(
    request: ImplementationRequest,
    workspace: ImplementationWorkspace,
    work_branch: str,
    commit_message: str,
) -> None:
    readiness = evaluate_implementation_readiness(request)
    if readiness.decision is not ImplementationDecision.READY:
        raise ImplementationMutationError(
            f"implementation request is not ready: {readiness.decision.value}"
        )
    if request.authorization is not ImplementationAuthorization.WORK_BRANCH:
        raise ImplementationMutationError("v0.1 mutation requires WORK_BRANCH authorization exactly")
    if workspace.authorization is not ImplementationAuthorization.WORK_BRANCH:
        raise ImplementationMutationError("workspace is not authorized for WORK_BRANCH mutation")
    if (
        workspace.repository != request.repository
        or workspace.base_branch != request.expected_base_branch
        or workspace.objective != request.objective
        or workspace.contracts_to_preserve != request.contracts_to_preserve
        or workspace.contracts_to_change != request.contracts_to_change
        or workspace.acceptance_criteria != request.acceptance_criteria
    ):
        raise ImplementationMutationError("workspace metadata does not match the approved request")
    if not commit_message.strip():
        raise ImplementationMutationError("commit_message must not be empty")
    _validate_work_branch_name(work_branch, workspace.base_branch)

    allowed = set(request.authorized_components)
    prohibited = set(request.prohibited_components)
    for change in workspace.changes:
        component = classify_changed_path(change.path)
        if component != change.component or component not in allowed or component in prohibited:
            raise ImplementationMutationError(
                f"workspace path {change.path!r} is outside the approved component scope"
            )


def _validate_work_branch_name(work_branch: str, base_branch: str) -> None:
    prefix = "agent/implementation/"
    if work_branch == base_branch or not work_branch.startswith(prefix):
        raise ImplementationMutationError(
            f"work branch must use dedicated {prefix!r} namespace and differ from base"
        )
    if (
        work_branch.endswith(("/", "."))
        or ".." in work_branch
        or "//" in work_branch
        or any(char.isspace() for char in work_branch)
    ):
        raise ImplementationMutationError("work branch name is not canonical")


def _validate_base_tree(
    workspace: ImplementationWorkspace,
    entries: Sequence[Mapping[str, object]],
) -> None:
    all_paths = {_required_string(entry, "path", "tree entry") for entry in entries}
    blobs = _blob_entries(entries)
    for change in workspace.changes:
        current = blobs.get(change.path)
        if change.kind is ImplementationFileChangeKind.CREATE:
            if change.path in all_paths:
                raise ImplementationMutationError(
                    f"CREATE path {change.path!r} already exists in the exact base tree"
                )
            continue
        if current is None:
            raise ImplementationMutationError(
                f"UPDATE path {change.path!r} is absent from the exact base tree"
            )
        current_sha, mode = current
        if current_sha != change.source_blob_sha:
            raise ImplementationMutationError(
                f"UPDATE path {change.path!r} source blob does not match exact base tree"
            )
        if mode != "100644":
            raise ImplementationMutationError(
                f"UPDATE path {change.path!r} is not a regular non-executable file in v0.1"
            )


def _blob_entries(entries: Sequence[Mapping[str, object]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if entry.get("type") != "blob":
            continue
        path = _required_string(entry, "path", "tree entry")
        sha = _required_string(entry, "sha", f"tree entry {path!r}")
        mode = _required_string(entry, "mode", f"tree entry {path!r}")
        result[path] = (sha, mode)
    return result


def _require_branch_sha(
    branch: Mapping[str, object] | None,
    branch_name: str,
    expected_sha: str,
) -> None:
    observed = _observed_branch_sha(branch, branch_name)
    if observed != expected_sha:
        raise ImplementationMutationError(
            f"branch {branch_name!r} moved: expected {expected_sha}, observed {observed}"
        )


def _observed_branch_sha(branch: Mapping[str, object] | None, branch_name: str) -> str:
    if branch is None:
        raise ImplementationMutationError(f"cannot observe branch {branch_name!r}")
    commit_value = branch.get("commit")
    if not isinstance(commit_value, Mapping):
        raise ImplementationMutationError(f"branch {branch_name!r} has no commit object")
    return _required_string(cast(Mapping[str, object], commit_value), "sha", "branch commit")


def _required_string(value: Mapping[str, object], key: str, context: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ImplementationMutationError(f"{context} has no valid {key}")
    return raw


def _workspace_sha256(workspace: ImplementationWorkspace) -> str:
    import hashlib

    canonical = json.dumps(
        workspace.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
