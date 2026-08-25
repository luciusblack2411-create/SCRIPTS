"""Fail-closed amendment of an existing same-repository Draft PR."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from ..pr_review import classify_changed_path
from ..pr_review.enums import ComponentId
from .enums import ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .mutation import ImplementationMutationTreeEntry


class ImplementationDraftPrAmendmentError(RuntimeError):
    """Raised whenever exact amendment evidence cannot be established."""


class AmendmentCiStatus(StrEnum):
    PASSED = "PASSED"


class AmendmentDecision(StrEnum):
    READY_FOR_DRAFT_PR = "READY_FOR_DRAFT_PR"


class ImplementationDraftPrAmendmentChange(FrozenImplementationModel):
    kind: ImplementationFileChangeKind
    path: str = Field(min_length=1)
    proposed_content: str
    component: ComponentId


class ImplementationDraftPrAmendmentRequest(FrozenImplementationModel):
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
    changes: tuple[ImplementationDraftPrAmendmentChange, ...] = Field(min_length=1)
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_contract(self) -> ImplementationDraftPrAmendmentRequest:
        if self.work_branch == self.base_branch:
            raise ValueError("amendment work branch must differ from base branch")
        if not self.commit_message.strip():
            raise ValueError("commit_message must not be blank")
        if (self.work_branch.startswith("/") or self.work_branch.endswith(("/", "."))
                or ".." in self.work_branch or "//" in self.work_branch
                or any(c.isspace() for c in self.work_branch)):
            raise ValueError("work_branch syntax is not canonical")
        paths = tuple(change.path for change in self.changes)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("amendment paths must be unique and lexically ordered")
        return self


class ImplementationDraftPrAmendmentCiResult(FrozenImplementationModel):
    workflow_file: Literal["ci.yml"] = "ci.yml"
    work_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    run_id: int = Field(gt=0)
    ci_status: Literal[AmendmentCiStatus.PASSED] = AmendmentCiStatus.PASSED
    base_head_after_ci: str = Field(min_length=1)
    base_fresh_after_ci: Literal[True] = True
    decision: Literal[AmendmentDecision.READY_FOR_DRAFT_PR] = AmendmentDecision.READY_FOR_DRAFT_PR


class ImplementationDraftPrAmendmentResult(FrozenImplementationModel):
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
    ci: ImplementationDraftPrAmendmentCiResult
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


class ImplementationDraftPrAmendmentBackend(Protocol):
    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None: ...
    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None: ...
    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]: ...
    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str: ...
    def create_utf8_blob(self, repository: str, content: str) -> str: ...
    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[ImplementationMutationTreeEntry]) -> str: ...
    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str: ...
    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]: ...
    def update_existing_ref_fast_forward(self, repository: str, branch: str, commit_sha: str) -> None: ...
    def dispatch_amendment_ci(self, repository: str, workflow_file: Literal["ci.yml"], branch: str) -> None: ...
    def list_amendment_ci_runs(self, repository: str, workflow_file: Literal["ci.yml"], *, branch: str, head_sha: str) -> Sequence[Mapping[str, object]]: ...
    def list_amendment_ci_jobs(self, repository: str, run_id: int) -> Sequence[Mapping[str, object]]: ...


def execute_draft_pr_amendment(request: ImplementationDraftPrAmendmentRequest, backend: ImplementationDraftPrAmendmentBackend) -> ImplementationDraftPrAmendmentResult:
    request = ImplementationDraftPrAmendmentRequest.model_validate(request.model_dump(mode="python"))
    pr = backend.get_pull_request(request.repository, request.pr_number)
    if pr is None:
        raise ImplementationDraftPrAmendmentError("pull request is missing")
    _require_pr(pr, request, request.expected_head_sha)
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _require_branch(backend, request.repository, request.work_branch, request.expected_head_sha)
    allowed, prohibited = set(request.authorized_components), set(request.prohibited_components)
    source = _blob_map(backend.list_tree(request.repository, request.expected_head_sha))
    entries: list[ImplementationMutationTreeEntry] = []
    for change in request.changes:
        component = classify_changed_path(change.path)
        if component is not change.component or component not in allowed or component in prohibited:
            raise ImplementationDraftPrAmendmentError(f"unauthorized amendment path {change.path!r}")
        present = source.get(change.path)
        if change.kind is ImplementationFileChangeKind.CREATE and present is not None:
            raise ImplementationDraftPrAmendmentError(f"CREATE path {change.path!r} exists")
        if change.kind is ImplementationFileChangeKind.UPDATE and (present is None or present[1] != "100644"):
            raise ImplementationDraftPrAmendmentError(f"UPDATE path {change.path!r} is not a regular file")
        entries.append(ImplementationMutationTreeEntry(path=change.path, blob_sha=backend.create_utf8_blob(request.repository, change.proposed_content)))
    base_tree = backend.get_commit_tree_sha(request.repository, request.expected_head_sha)
    tree_sha = backend.create_tree(request.repository, base_tree, tuple(entries))
    new_head = backend.create_commit(request.repository, message=request.commit_message, tree_sha=tree_sha, parent_sha=request.expected_head_sha)
    commit = backend.get_commit(request.repository, new_head)
    parents = commit.get("parents")
    if commit.get("sha") != new_head or _nested_sha(commit, "tree") != tree_sha or not isinstance(parents, Sequence) or isinstance(parents, (str, bytes)) or len(parents) != 1 or not isinstance(parents[0], Mapping) or parents[0].get("sha") != request.expected_head_sha:
        raise ImplementationDraftPrAmendmentError("created commit tree or sole parent is inconsistent")
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    _require_branch(backend, request.repository, request.work_branch, request.expected_head_sha)
    backend.update_existing_ref_fast_forward(request.repository, request.work_branch, new_head)
    _require_branch(backend, request.repository, request.work_branch, new_head)
    observed = backend.get_pull_request(request.repository, request.pr_number)
    if observed is None:
        raise ImplementationDraftPrAmendmentError("pull request disappeared after amendment")
    _require_pr(observed, request, new_head)
    ci = validate_draft_pr_amendment_ci(request, new_head, backend)
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    return ImplementationDraftPrAmendmentResult(repository=request.repository, pr_number=request.pr_number, base_branch=request.base_branch, base_sha=request.base_sha, work_branch=request.work_branch, old_head_sha=request.expected_head_sha, new_head_sha=new_head, tree_sha=tree_sha, ci=ci)


def validate_draft_pr_amendment_ci(request: ImplementationDraftPrAmendmentRequest, new_head_sha: str, backend: ImplementationDraftPrAmendmentBackend) -> ImplementationDraftPrAmendmentCiResult:
    _require_branch(backend, request.repository, request.base_branch, request.base_sha)
    backend.dispatch_amendment_ci(request.repository, "ci.yml", request.work_branch)
    runs = tuple(run for run in backend.list_amendment_ci_runs(request.repository, "ci.yml", branch=request.work_branch, head_sha=new_head_sha) if run.get("event") == "workflow_dispatch" and run.get("head_branch") == request.work_branch and run.get("head_sha") == new_head_sha and run.get("status") == "completed")
    if len(runs) != 1:
        raise ImplementationDraftPrAmendmentError("exact amendment CI requires one completed run")
    run = runs[0]
    run_id = run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0 or run.get("conclusion") != "success":
        raise ImplementationDraftPrAmendmentError("amendment CI workflow did not pass")
    jobs = tuple(backend.list_amendment_ci_jobs(request.repository, run_id))
    if not jobs or any(job.get("status") != "completed" or job.get("conclusion") != "success" for job in jobs):
        raise ImplementationDraftPrAmendmentError("amendment CI jobs did not all pass")
    base_after = _branch_sha(backend.get_branch(request.repository, request.base_branch), request.base_branch)
    if base_after != request.base_sha:
        raise ImplementationDraftPrAmendmentError("base drifted during amendment CI")
    return ImplementationDraftPrAmendmentCiResult(work_branch=request.work_branch, commit_sha=new_head_sha, run_id=run_id, base_head_after_ci=base_after)


def _require_pr(pr: Mapping[str, object], request: ImplementationDraftPrAmendmentRequest, head_sha: str) -> None:
    if pr.get("number") != request.pr_number or pr.get("state") != "open" or pr.get("draft") is not True or pr.get("merged") is not False:
        raise ImplementationDraftPrAmendmentError("pull request must be open, Draft, and unmerged")
    base, head = pr.get("base"), pr.get("head")
    if not isinstance(base, Mapping) or not isinstance(head, Mapping):
        raise ImplementationDraftPrAmendmentError("pull request base/head evidence is missing")
    repo = head.get("repo")
    full_name = repo.get("full_name") if isinstance(repo, Mapping) else None
    if base.get("ref") != request.base_branch or base.get("sha") != request.base_sha or head.get("ref") != request.work_branch or head.get("sha") != head_sha or full_name != request.repository:
        raise ImplementationDraftPrAmendmentError("pull request binding is stale or cross-repository")


def _require_branch(backend: ImplementationDraftPrAmendmentBackend, repository: str, branch: str, sha: str) -> None:
    observed = _branch_sha(backend.get_branch(repository, branch), branch)
    if observed != sha:
        raise ImplementationDraftPrAmendmentError(f"branch {branch!r} moved: expected {sha}, observed {observed}")


def _branch_sha(value: Mapping[str, object] | None, branch: str) -> str:
    commit = value.get("commit") if value is not None else None
    if not isinstance(commit, Mapping) or not isinstance(commit.get("sha"), str):
        raise ImplementationDraftPrAmendmentError(f"cannot observe branch {branch!r}")
    return cast(str, commit["sha"])


def _nested_sha(value: Mapping[str, object], key: str) -> object:
    nested = value.get(key)
    return nested.get("sha") if isinstance(nested, Mapping) else None


def _blob_map(entries: Sequence[Mapping[str, object]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if entry.get("type") == "blob" and isinstance(entry.get("path"), str) and isinstance(entry.get("sha"), str) and isinstance(entry.get("mode"), str):
            result[cast(str, entry["path"])] = (cast(str, entry["sha"]), cast(str, entry["mode"]))
    return result
