"""Contracts and deterministic decision logic for PR Review Agent v0.1."""

from .architecture import DiffAddedLine, evaluate_architecture_safety_checks, extract_added_lines
from .check_ids import ReviewCheckId
from .ci_provenance import evaluate_ci_merge_provenance
from .contract_ci import DiffRemovedLine, evaluate_contract_quality_ci_checks, extract_removed_lines
from .decision import DecisionOutcome, derive_review_decision
from .enums import (
    ComponentId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewEvidenceKind,
    ReviewFindingSeverity,
)
from .github import (
    GitHubChangedFile,
    GitHubCheckoutProvenance,
    GitHubCommit,
    GitHubContextError,
    GitHubReadAdapter,
    GitHubReadBackend,
    GitHubWorkflowRun,
    PullRequestContext,
)
from .github_rest import GitHubRestError, GitHubRestReadBackend, UrllibGitHubTransport
from .metadata import evaluate_metadata_checks
from .models import ReviewCheck, ReviewEvidence, ReviewFinding, ReviewReport, ReviewRequest
from .reviewer import build_review_report, review_pr
from .scope import (
    ChangedFileClassification,
    classify_changed_files,
    classify_changed_path,
    detected_components,
    evaluate_scope_checks,
)

__all__ = [
    "ChangedFileClassification",
    "ComponentId",
    "DecisionOutcome",
    "DiffAddedLine",
    "DiffRemovedLine",
    "GitHubChangedFile",
    "GitHubCheckoutProvenance",
    "GitHubCommit",
    "GitHubContextError",
    "GitHubReadAdapter",
    "GitHubReadBackend",
    "GitHubRestError",
    "GitHubRestReadBackend",
    "GitHubWorkflowRun",
    "PullRequestContext",
    "ReviewCheck",
    "ReviewCheckId",
    "ReviewCheckStatus",
    "ReviewDecision",
    "ReviewEvidence",
    "ReviewEvidenceKind",
    "ReviewFinding",
    "ReviewFindingSeverity",
    "ReviewReport",
    "ReviewRequest",
    "UrllibGitHubTransport",
    "build_review_report",
    "classify_changed_files",
    "classify_changed_path",
    "derive_review_decision",
    "detected_components",
    "evaluate_architecture_safety_checks",
    "evaluate_ci_merge_provenance",
    "evaluate_contract_quality_ci_checks",
    "evaluate_metadata_checks",
    "evaluate_scope_checks",
    "extract_added_lines",
    "extract_removed_lines",
    "review_pr",
]
