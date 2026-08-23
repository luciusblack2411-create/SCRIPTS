"""Deterministic pull-request metadata checks for PR Review Agent v0.1."""

from __future__ import annotations

from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.enums import (
    ReviewCheckStatus,
    ReviewEvidenceKind,
    ReviewFindingSeverity,
)
from cisco_assessment.devtools.pr_review.github import PullRequestContext
from cisco_assessment.devtools.pr_review.models import (
    ReviewCheck,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
)


def evaluate_metadata_checks(
    request: ReviewRequest,
    context: PullRequestContext,
) -> tuple[ReviewCheck, ...]:
    """Evaluate PR state needed before trusting later diff-based checks."""
    return (
        _evaluate_base_branch(request, context),
        _evaluate_open_state(context),
        _evaluate_mergeability(context),
        _evaluate_diff_availability(context),
        _evaluate_base_head_freshness(context),
    )


def _evaluate_base_branch(request: ReviewRequest, context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.GIT_001
    if context.base_branch == request.expected_base_branch:
        return _pass(check_id, "Pull request targets the expected base branch")

    evidence = _metadata_evidence(
        check_id,
        "PR base branch differs from the review request.",
        context.base_branch,
        request.expected_base_branch,
    )
    finding = ReviewFinding(
        finding_id=f"{check_id.value}:001",
        check_id=check_id,
        severity=ReviewFindingSeverity.BLOCKING,
        title="Pull request targets an unexpected base branch",
        observation=(
            f"The PR targets {context.base_branch!r}; the review request requires "
            f"{request.expected_base_branch!r}."
        ),
        evidence=(evidence,),
        recommendation="Retarget the PR or issue a review request for the actual base branch.",
    )
    return _fail(check_id, "Pull request targets the expected base branch", evidence, finding)


def _evaluate_open_state(context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.GIT_002
    if context.state == "open":
        return _pass(check_id, "Pull request is open")

    evidence = _metadata_evidence(
        check_id,
        "PR state must be open for an integration review.",
        context.state,
        "open",
    )
    finding = ReviewFinding(
        finding_id=f"{check_id.value}:001",
        check_id=check_id,
        severity=ReviewFindingSeverity.BLOCKING,
        title="Pull request is not open",
        observation=f"The PR state is {context.state!r}.",
        evidence=(evidence,),
        recommendation="Review an open pull request head instead.",
    )
    return _fail(check_id, "Pull request is open", evidence, finding)


def _evaluate_mergeability(context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.GIT_003
    if context.mergeable is True:
        return _pass(check_id, "Pull request is mergeable")
    if context.mergeable is None:
        return ReviewCheck(
            check_id=check_id,
            name="Pull request is mergeable",
            category="GIT",
            status=ReviewCheckStatus.UNKNOWN,
            applicable=True,
            summary="GitHub has not established mergeability yet.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    evidence = _metadata_evidence(
        check_id,
        "GitHub reports that the pull request is not mergeable.",
        "false",
        "true",
    )
    finding = ReviewFinding(
        finding_id=f"{check_id.value}:001",
        check_id=check_id,
        severity=ReviewFindingSeverity.BLOCKING,
        title="Pull request is not mergeable",
        observation="GitHub reports mergeable=false for the current PR head.",
        evidence=(evidence,),
        recommendation="Resolve the merge conflict or other mergeability blocker before integration.",
    )
    return _fail(check_id, "Pull request is mergeable", evidence, finding)


def _evaluate_diff_availability(context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.GIT_004
    if not context.changed_files:
        return ReviewCheck(
            check_id=check_id,
            name="Effective PR diff is available",
            category="GIT",
            status=ReviewCheckStatus.UNKNOWN,
            applicable=True,
            summary="The PR has no changed-file evidence to review.",
            evidence=(),
            findings=(),
            blocking=True,
        )
    if context.diff_text.strip():
        return _pass(check_id, "Effective PR diff is available")
    return ReviewCheck(
        check_id=check_id,
        name="Effective PR diff is available",
        category="GIT",
        status=ReviewCheckStatus.UNKNOWN,
        applicable=True,
        summary="Changed files exist but the effective PR diff is unavailable.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _evaluate_base_head_freshness(context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.GIT_005
    name = "Current base branch HEAD is independently observed"
    if context.base_branch_head_sha is None:
        return ReviewCheck(
            check_id=check_id,
            name=name,
            category="GIT",
            status=ReviewCheckStatus.UNKNOWN,
            applicable=True,
            summary=(
                f"The current HEAD of base branch {context.base_branch!r} could not be observed."
            ),
            evidence=(),
            findings=(),
            blocking=True,
        )

    evidence = ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:001",
        kind=ReviewEvidenceKind.COMMIT,
        description=(
            "Independent current base-branch HEAD compared with the base SHA embedded in the PR payload."
        ),
        commit_sha=context.base_branch_head_sha,
        check_id=check_id,
        observed_value=context.base_branch_head_sha,
        expected_value=context.base_sha,
    )
    if context.base_branch_head_sha == context.base_sha:
        return ReviewCheck(
            check_id=check_id,
            name=name,
            category="GIT",
            status=ReviewCheckStatus.PASS,
            applicable=True,
            summary="PR base SHA matches the independently observed current base-branch HEAD.",
            evidence=(evidence,),
            findings=(),
            blocking=False,
        )

    finding = ReviewFinding(
        finding_id=f"{check_id.value}:001",
        check_id=check_id,
        severity=ReviewFindingSeverity.WARNING,
        title="Base branch advanced beyond the PR base snapshot",
        observation=(
            f"The PR payload records base SHA {context.base_sha}, while current "
            f"{context.base_branch!r} HEAD is {context.base_branch_head_sha}."
        ),
        evidence=(evidence,),
        recommendation=(
            "Treat base advancement as factual review context. CI-003 separately determines "
            "whether a successful pull-request workflow proved the current base/head merge checkout."
        ),
    )
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category="GIT",
        status=ReviewCheckStatus.WARNING,
        applicable=True,
        summary="Current base HEAD differs from the base SHA recorded in the PR payload.",
        evidence=(evidence,),
        findings=(finding,),
        blocking=False,
    )


def _metadata_evidence(
    check_id: ReviewCheckId,
    description: str,
    observed_value: str,
    expected_value: str,
) -> ReviewEvidence:
    return ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:001",
        kind=ReviewEvidenceKind.PR_METADATA,
        description=description,
        check_id=check_id,
        observed_value=observed_value,
        expected_value=expected_value,
    )


def _pass(check_id: ReviewCheckId, name: str) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category="GIT",
        status=ReviewCheckStatus.PASS,
        applicable=True,
        summary=f"{name}.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _fail(
    check_id: ReviewCheckId,
    name: str,
    evidence: ReviewEvidence,
    finding: ReviewFinding,
) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category="GIT",
        status=ReviewCheckStatus.FAIL,
        applicable=True,
        summary=f"{name} check failed.",
        evidence=(evidence,),
        findings=(finding,),
        blocking=True,
    )
