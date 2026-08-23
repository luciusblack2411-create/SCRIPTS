"""Contracts and readiness logic for Implementation Agent v0.1."""

from ..pr_review import ComponentId
from .ci_validation import (
    ImplementationCiBackend,
    ImplementationCiJobResult,
    ImplementationCiStatus,
    ImplementationCiValidationError,
    ImplementationCiValidationResult,
    ImplementationOperationalDecision,
    validate_work_branch_ci,
)
from .context import (
    ImplementationContext,
    ImplementationContextError,
    ImplementationContextFile,
    ImplementationReadBackend,
    load_implementation_context,
)
from .draft_pr import (
    ImplementationDraftPrBackend,
    ImplementationDraftPrDecision,
    ImplementationDraftPrError,
    ImplementationDraftPrRequest,
    ImplementationDraftPrResult,
    prepare_implementation_draft_pr,
)
from .enums import (
    ImplementationAuthorization,
    ImplementationDecision,
    ImplementationEvidenceKind,
    ImplementationFileChangeKind,
    ImplementationGateStatus,
    ImplementationPlanStepKind,
)
from .gate_ids import ImplementationGateId
from .github_ci import (
    GitHubImplementationCiBackend,
    GitHubImplementationCiHttpTransport,
    ImplementationGitHubCiError,
    UrllibGitHubImplementationCiTransport,
)
from .github_draft_pr import (
    GitHubImplementationDraftPrBackend,
    GitHubImplementationDraftPrHttpTransport,
    ImplementationGitHubDraftPrError,
    UrllibGitHubImplementationDraftPrTransport,
)
from .github_mutation import (
    GitHubImplementationMutationBackend,
    GitHubImplementationMutationHttpTransport,
    ImplementationGitHubMutationError,
    UrllibGitHubImplementationMutationTransport,
)
from .github_rest import GitHubImplementationReadBackend, ImplementationGitHubRestError
from .models import (
    ImplementationEvidence,
    ImplementationGate,
    ImplementationReadinessReport,
    ImplementationRequest,
)
from .mutation import (
    ImplementationMutationBackend,
    ImplementationMutationChangeResult,
    ImplementationMutationError,
    ImplementationMutationResult,
    ImplementationMutationTreeEntry,
    execute_work_branch_mutation,
)
from .operational import (
    ImplementationOperation,
    ImplementationOperationalResult,
    ImplementationOperationFileError,
    execute_implementation_operation,
    load_implementation_operation,
    render_implementation_result_human,
    render_implementation_result_json,
)
from .planning import (
    ImplementationPlan,
    ImplementationPlanningError,
    ImplementationPlanStep,
    build_implementation_plan,
)
from .readiness import evaluate_implementation_readiness
from .source_inspection import (
    ImplementationSourceFile,
    ImplementationSourceInspection,
    ImplementationSourceInspectionError,
    ImplementationSourceReadBackend,
    inspect_implementation_sources,
)
from .workspace import (
    ImplementationFileChangeDraft,
    ImplementationProposedFileChange,
    ImplementationWorkspace,
    ImplementationWorkspaceError,
    build_implementation_workspace,
)

__all__ = [
    "ComponentId",
    "GitHubImplementationCiBackend",
    "GitHubImplementationCiHttpTransport",
    "GitHubImplementationDraftPrBackend",
    "GitHubImplementationDraftPrHttpTransport",
    "GitHubImplementationMutationBackend",
    "GitHubImplementationMutationHttpTransport",
    "GitHubImplementationReadBackend",
    "ImplementationAuthorization",
    "ImplementationCiBackend",
    "ImplementationCiJobResult",
    "ImplementationCiStatus",
    "ImplementationCiValidationError",
    "ImplementationCiValidationResult",
    "ImplementationContext",
    "ImplementationContextError",
    "ImplementationContextFile",
    "ImplementationDecision",
    "ImplementationDraftPrBackend",
    "ImplementationDraftPrDecision",
    "ImplementationDraftPrError",
    "ImplementationDraftPrRequest",
    "ImplementationDraftPrResult",
    "ImplementationEvidence",
    "ImplementationEvidenceKind",
    "ImplementationFileChangeDraft",
    "ImplementationFileChangeKind",
    "ImplementationGate",
    "ImplementationGateId",
    "ImplementationGateStatus",
    "ImplementationGitHubCiError",
    "ImplementationGitHubDraftPrError",
    "ImplementationGitHubMutationError",
    "ImplementationGitHubRestError",
    "ImplementationMutationBackend",
    "ImplementationMutationChangeResult",
    "ImplementationMutationError",
    "ImplementationMutationResult",
    "ImplementationMutationTreeEntry",
    "ImplementationOperation",
    "ImplementationOperationFileError",
    "ImplementationOperationalDecision",
    "ImplementationOperationalResult",
    "ImplementationPlan",
    "ImplementationPlanStep",
    "ImplementationPlanStepKind",
    "ImplementationPlanningError",
    "ImplementationProposedFileChange",
    "ImplementationReadBackend",
    "ImplementationReadinessReport",
    "ImplementationRequest",
    "ImplementationSourceFile",
    "ImplementationSourceInspection",
    "ImplementationSourceInspectionError",
    "ImplementationSourceReadBackend",
    "ImplementationWorkspace",
    "ImplementationWorkspaceError",
    "UrllibGitHubImplementationCiTransport",
    "UrllibGitHubImplementationDraftPrTransport",
    "UrllibGitHubImplementationMutationTransport",
    "build_implementation_plan",
    "build_implementation_workspace",
    "evaluate_implementation_readiness",
    "execute_implementation_operation",
    "execute_work_branch_mutation",
    "inspect_implementation_sources",
    "load_implementation_context",
    "load_implementation_operation",
    "prepare_implementation_draft_pr",
    "render_implementation_result_human",
    "render_implementation_result_json",
    "validate_work_branch_ci",
]
