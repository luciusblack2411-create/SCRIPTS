"""CONTROLLED_DRAFT_PR_AMENDMENT_V1 orchestration and fresh-CI gate."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import model_validator

from .ci_validation import ImplementationCiBackend, ImplementationCiStatus, ImplementationCiValidationResult, validate_work_branch_ci
from .draft_pr_amendment import ImplementationDraftPrAmendmentBackend, ImplementationDraftPrAmendmentOperation, ImplementationDraftPrAmendmentResult, execute_draft_pr_amendment
from .enums import ImplementationFileChangeKind
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .mutation import ImplementationMutationChangeResult, ImplementationMutationResult

CONTROL_PLANE_ID: Literal["CONTROLLED_DRAFT_PR_AMENDMENT_V1"] = "CONTROLLED_DRAFT_PR_AMENDMENT_V1"


class ControlledDraftPrAmendmentOperation(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_DRAFT_PR_AMENDMENT_V1"] = CONTROL_PLANE_ID
    amendment: ImplementationDraftPrAmendmentOperation


class ControlledDraftPrAmendmentResult(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    control_plane_id: Literal["CONTROLLED_DRAFT_PR_AMENDMENT_V1"] = CONTROL_PLANE_ID
    amendment: ImplementationDraftPrAmendmentResult
    ci: ImplementationCiValidationResult
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def require_passed_exact_ci(self) -> ControlledDraftPrAmendmentResult:
        if self.ci.ci_status is not ImplementationCiStatus.PASSED or self.ci.commit_sha != self.amendment.new_head_sha or self.ci.workflow_file != "ci.yml":
            raise ValueError("successful amendment result requires PASSED ci.yml on exact new head")
        return self


def execute_controlled_draft_pr_amendment(operation: ControlledDraftPrAmendmentOperation, amendment_backend: ImplementationDraftPrAmendmentBackend, ci_backend: ImplementationCiBackend, *, ci_validator: Callable[[ImplementationMutationResult, ImplementationCiBackend], ImplementationCiValidationResult] = validate_work_branch_ci) -> ControlledDraftPrAmendmentResult:
    op = ControlledDraftPrAmendmentOperation.model_validate(operation.model_dump(mode="python"))
    amended = execute_draft_pr_amendment(op.amendment, amendment_backend)
    synthetic = ImplementationMutationResult(repository=amended.repository, base_branch=amended.base_branch, base_sha=amended.base_sha, workspace_sha256="0" * 64, work_branch=amended.work_branch, commit_sha=amended.new_head_sha, tree_sha=amended.tree_sha, changes=tuple(ImplementationMutationChangeResult(ordinal=index, change_id=f"impl-change:{index:04d}", kind=ImplementationFileChangeKind.UPDATE, path=path, published_blob_sha="verified-by-amendment", proposed_content_sha256="0" * 64) for index, path in enumerate(amended.changed_paths, 1)), base_head_after_publish=amended.base_sha, base_fresh_after_publish=True)
    ci = ci_validator(synthetic, ci_backend)
    if ci.ci_status is not ImplementationCiStatus.PASSED:
        raise RuntimeError("fresh ci.yml did not pass on the exact amended head")
    return ControlledDraftPrAmendmentResult(amendment=amended, ci=ci)
