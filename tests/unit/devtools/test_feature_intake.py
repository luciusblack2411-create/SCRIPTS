from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation.enums import ImplementationAuthorization
from cisco_assessment.devtools.implementation.feature_intake import (
    FeatureContractApproval,
    FeatureContractProposalDraft,
    FeatureIntakeError,
    FeatureRequest,
    approve_feature_contract,
    build_feature_contract_proposal,
    feature_contract_proposal_sha256,
)
from cisco_assessment.devtools.implementation.models import (
    ImplementationEvidence,
    ImplementationEvidenceKind,
)
from cisco_assessment.devtools.pr_review import ComponentId


def _request(
    *,
    max_authorization: ImplementationAuthorization = ImplementationAuthorization.DRAFT_PR,
) -> FeatureRequest:
    return FeatureRequest(
        repository="luciusblack2411-create/SCRIPTS",
        request_text="Implement a deterministic feature contract intake boundary.",
        requested_max_authorization=max_authorization,
        explicit_evidence=(
            ImplementationEvidence(
                evidence_id="source:main",
                kind=ImplementationEvidenceKind.SOURCE,
                description="Current main source tree.",
                commit_sha="a" * 40,
            ),
        ),
        related_issue_ids=("#777",),
    )


def _draft(
    *,
    maximum_authorization: ImplementationAuthorization = ImplementationAuthorization.DRAFT_PR,
) -> FeatureContractProposalDraft:
    return FeatureContractProposalDraft(
        objective="Add Feature Intake / Contract Proposal v0.1.",
        authorized_components=(ComponentId.CI_TOOLING, ComponentId.TESTING_FIXTURES),
        prohibited_components=(ComponentId.COLLECTOR, ComponentId.RUNNER_CLI),
        contracts_to_preserve=("IMPLEMENTATION_AGENT_V1",),
        contracts_to_change=("FEATURE_INTAKE_V1",),
        invariants=(
            "No Cisco execution.",
            "Human merge gate remains mandatory.",
        ),
        acceptance_criteria=(
            "Proposal never sets contract_approved=true.",
            "Exact human approval creates ImplementationRequest.",
        ),
        required_evidence_ids=("source:main",),
        ambiguities=("Semantic proposal remains human-reviewable.",),
        maximum_authorization=maximum_authorization,
    )


def test_feature_request_is_strict_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        FeatureRequest.model_validate(
            {
                "repository": "luciusblack2411-create/SCRIPTS",
                "request_text": "Feature",
                "auto_approve": True,
            }
        )


def test_feature_request_rejects_duplicate_explicit_evidence_ids() -> None:
    evidence = ImplementationEvidence(
        evidence_id="source:main",
        kind=ImplementationEvidenceKind.SOURCE,
        description="Source.",
    )
    with pytest.raises(ValidationError, match="must be unique"):
        FeatureRequest(
            repository="luciusblack2411-create/SCRIPTS",
            request_text="Feature",
            explicit_evidence=(evidence, evidence),
        )


def test_proposal_rejects_unknown_authorized_component() -> None:
    draft = _draft().model_copy(
        update={"authorized_components": (ComponentId.UNKNOWN,)}
    )
    with pytest.raises(FeatureIntakeError, match="must not contain UNKNOWN"):
        build_feature_contract_proposal(_request(), draft, base_sha="b" * 40)


def test_proposal_rejects_scope_overlap() -> None:
    draft = _draft().model_copy(
        update={
            "authorized_components": (ComponentId.CI_TOOLING,),
            "prohibited_components": (ComponentId.CI_TOOLING,),
        }
    )
    with pytest.raises(FeatureIntakeError, match="must not overlap"):
        build_feature_contract_proposal(_request(), draft, base_sha="b" * 40)


def test_proposal_cannot_exceed_request_mutation_bound() -> None:
    request = _request(max_authorization=ImplementationAuthorization.WORK_BRANCH)
    with pytest.raises(FeatureIntakeError, match="exceeds the FeatureRequest mutation bound"):
        build_feature_contract_proposal(request, _draft(), base_sha="b" * 40)


def test_proposal_preserves_only_explicit_evidence_and_requires_human_approval() -> None:
    proposal = build_feature_contract_proposal(
        _request(),
        _draft(),
        base_sha="b" * 40,
    )

    assert proposal.contract_approved is False
    assert proposal.requires_human_approval is True
    assert proposal.human_merge_gate_required is True
    assert proposal.cisco_execution_allowed is False
    assert tuple(item.evidence_id for item in proposal.request.explicit_evidence) == (
        "source:main",
    )


def test_proposal_sha256_is_deterministic() -> None:
    proposal = build_feature_contract_proposal(
        _request(),
        _draft(),
        base_sha="b" * 40,
    )

    first = feature_contract_proposal_sha256(proposal)
    second = feature_contract_proposal_sha256(proposal)

    assert first == second
    assert len(first) == 64


def test_approval_must_bind_exact_proposal_hash_and_base() -> None:
    proposal = build_feature_contract_proposal(
        _request(),
        _draft(),
        base_sha="b" * 40,
    )
    approval = FeatureContractApproval(
        decision="CONTRACT_APPROVED",
        repository=proposal.request.repository,
        base_sha=proposal.base_sha,
        proposal_sha256="0" * 64,
        authorization=ImplementationAuthorization.DRAFT_PR,
        authorized_by="human-operator",
        rationale="Approve exact proposal.",
    )

    with pytest.raises(FeatureIntakeError, match="proposal_sha256"):
        approve_feature_contract(proposal, approval)


def test_approval_cannot_exceed_proposal_authorization() -> None:
    proposal = build_feature_contract_proposal(
        _request(),
        _draft(maximum_authorization=ImplementationAuthorization.WORK_BRANCH),
        base_sha="b" * 40,
    )
    approval = FeatureContractApproval(
        decision="CONTRACT_APPROVED",
        repository=proposal.request.repository,
        base_sha=proposal.base_sha,
        proposal_sha256=feature_contract_proposal_sha256(proposal),
        authorization=ImplementationAuthorization.DRAFT_PR,
        authorized_by="human-operator",
        rationale="Approve exact proposal.",
    )

    with pytest.raises(FeatureIntakeError, match="exceeds the proposal"):
        approve_feature_contract(proposal, approval)


def test_exact_approval_produces_existing_implementation_request_contract() -> None:
    proposal = build_feature_contract_proposal(
        _request(),
        _draft(),
        base_sha="b" * 40,
    )
    approval = FeatureContractApproval(
        decision="CONTRACT_APPROVED",
        repository=proposal.request.repository,
        base_sha=proposal.base_sha,
        proposal_sha256=feature_contract_proposal_sha256(proposal),
        authorization=ImplementationAuthorization.DRAFT_PR,
        authorized_by="human-operator",
        rationale="Approve exact proposal and bounded Draft PR authority.",
    )

    implementation = approve_feature_contract(proposal, approval)

    assert implementation.contract_approved is True
    assert implementation.authorization is ImplementationAuthorization.DRAFT_PR
    assert implementation.authorized_components == proposal.authorized_components
    assert implementation.prohibited_components == proposal.prohibited_components
    assert implementation.contracts_to_preserve == proposal.contracts_to_preserve
    assert implementation.contracts_to_change == proposal.contracts_to_change
    assert implementation.required_evidence_ids == ("source:main",)
    assert tuple(item.evidence_id for item in implementation.available_evidence) == (
        "source:main",
    )
    assert implementation.human_merge_gate_required is True
    assert implementation.cisco_execution_allowed is False
