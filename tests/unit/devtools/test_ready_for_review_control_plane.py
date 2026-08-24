from __future__ import annotations

import json

import pytest

from cisco_assessment.devtools.pr_review.enums import ComponentId
from cisco_assessment.devtools.pr_review.models import ReviewRequest
from cisco_assessment.devtools.ready_for_review import (
    ReadyForReviewAuthorization,
    ReadyForReviewOperation,
)
from cisco_assessment.devtools.ready_for_review_control_plane import (
    PR_REVIEW_TOKEN_ENV,
    READY_FOR_REVIEW_TOKEN_ENV,
    ReadyForReviewControlPlaneError,
    resolve_ready_for_review_tokens,
)


def test_resolver_requires_two_distinct_explicit_credentials() -> None:
    review, transition = resolve_ready_for_review_tokens(
        {
            PR_REVIEW_TOKEN_ENV: "review-token",
            READY_FOR_REVIEW_TOKEN_ENV: "transition-token",
            "GITHUB_TOKEN": "runner-token",
            "GH_TOKEN": "gh-token",
        }
    )

    assert review == "review-token"
    assert transition == "transition-token"


def test_resolver_never_falls_back_to_runner_credentials() -> None:
    with pytest.raises(ReadyForReviewControlPlaneError, match=PR_REVIEW_TOKEN_ENV):
        resolve_ready_for_review_tokens(
            {
                "GITHUB_TOKEN": "runner-token",
                "GH_TOKEN": "gh-token",
                READY_FOR_REVIEW_TOKEN_ENV: "transition-token",
            }
        )


def test_resolver_rejects_shared_read_write_credential() -> None:
    with pytest.raises(ReadyForReviewControlPlaneError, match="must be distinct"):
        resolve_ready_for_review_tokens(
            {
                PR_REVIEW_TOKEN_ENV: "same-token",
                READY_FOR_REVIEW_TOKEN_ENV: "same-token",
            }
        )


def test_operation_contains_scope_and_authorization_but_no_credentials() -> None:
    operation = ReadyForReviewOperation(
        review_request=ReviewRequest(
            repository="luciusblack2411-create/SCRIPTS",
            pr_number=61,
            objective="Validate review handoff.",
            expected_components=(ComponentId.TESTING_FIXTURES,),
        ),
        authorization=ReadyForReviewAuthorization.READY_FOR_REVIEW,
    )

    payload = json.loads(operation.model_dump_json())
    serialized = operation.model_dump_json()
    assert payload["authorization"] == "READY_FOR_REVIEW"
    assert PR_REVIEW_TOKEN_ENV not in serialized
    assert READY_FOR_REVIEW_TOKEN_ENV not in serialized
    assert "token" not in serialized.lower()
