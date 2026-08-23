"""Contracts and readiness logic for Implementation Agent v0.1."""

from ..pr_review import ComponentId
from .context import (
    ImplementationContext,
    ImplementationContextError,
    ImplementationContextFile,
    ImplementationReadBackend,
    load_implementation_context,
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
    "GitHubImplementationMutationBackend",
    "GitHubImplementationMutationHttpTransport",
    "GitHubImplementationReadBackend",
    "ImplementationAuthorization",
    "ImplementationContext",
    "ImplementationContextError",
    "ImplementationContextFile",
    "ImplementationDecision",
    "ImplementationEvidence",
    "ImplementationEvidenceKind",
    "ImplementationFileChangeDraft",
    "ImplementationFileChangeKind",
    "ImplementationGate",
    "ImplementationGateId",
    "ImplementationGateStatus",
    "ImplementationGitHubMutationError",
    "ImplementationGitHubRestError",
    "ImplementationMutationBackend",
    "ImplementationMutationChangeResult",
    "ImplementationMutationError",
    "ImplementationMutationResult",
    "ImplementationMutationTreeEntry",
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
    "UrllibGitHubImplementationMutationTransport",
    "build_implementation_plan",
    "build_implementation_workspace",
    "evaluate_implementation_readiness",
    "execute_work_branch_mutation",
    "inspect_implementation_sources",
    "load_implementation_context",
]
