from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.return_to_draft import (
    ReturnToDraftAuthorization,
    ReturnToDraftOperation,
)
from cisco_assessment.devtools.return_to_draft_control_plane import (
    PR_REVIEW_TOKEN_ENV,
    RETURN_TO_DRAFT_TOKEN_ENV,
    ReturnToDraftControlPlaneError,
    resolve_return_to_draft_tokens,
)
from cisco_assessment.devtools.return_to_draft_control_plane_cli import app


def operation() -> ReturnToDraftOperation:
    return ReturnToDraftOperation(
        repository="luciusblack2411-create/SCRIPTS",
        pr_number=61,
        base_branch="main",
        historical_pr_base_sha="a" * 40,
        expected_live_base_sha="b" * 40,
        head_branch="agent/implementation/example",
        head_sha="c" * 40,
        authorization=ReturnToDraftAuthorization.RETURN_TO_DRAFT,
    )


def test_resolver_uses_two_distinct_dedicated_credentials() -> None:
    assert resolve_return_to_draft_tokens(
        {PR_REVIEW_TOKEN_ENV: "read", RETURN_TO_DRAFT_TOKEN_ENV: "write"}
    ) == ("read", "write")


def test_resolver_has_no_github_fallback() -> None:
    with pytest.raises(ReturnToDraftControlPlaneError, match=PR_REVIEW_TOKEN_ENV):
        resolve_return_to_draft_tokens(
            {"GITHUB_TOKEN": "runner", "GH_TOKEN": "gh", RETURN_TO_DRAFT_TOKEN_ENV: "write"}
        )


def test_resolver_rejects_shared_credential() -> None:
    with pytest.raises(ReturnToDraftControlPlaneError, match="distinct"):
        resolve_return_to_draft_tokens(
            {PR_REVIEW_TOKEN_ENV: "same", RETURN_TO_DRAFT_TOKEN_ENV: "same"}
        )


def test_contract_rejects_extra_fields_and_wrong_authorization() -> None:
    payload = operation().model_dump(mode="python")
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ReturnToDraftOperation.model_validate(payload)
    payload.pop("unexpected")
    payload["authorization"] = "READY_FOR_REVIEW"
    with pytest.raises(ValidationError):
        ReturnToDraftOperation.model_validate(payload)


def test_contract_is_frozen_and_contains_no_secret() -> None:
    value = operation()
    with pytest.raises(ValidationError):
        value.pr_number = 62
    serialized = json.dumps(value.model_dump(mode="json"))
    assert "token" not in serialized.lower()
    assert "secret" not in serialized.lower()


def test_cli_app_imports_with_expected_name() -> None:
    assert app.info.name == "cisco-return-to-draft-control"
