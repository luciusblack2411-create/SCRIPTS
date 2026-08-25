from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation.draft_pr_amendment import (
    ImplementationDraftPrAmendmentRequest,
    amend_implementation_draft_pr,
)
from cisco_assessment.devtools.pr_review.enums import ComponentId


def test_public_amendment_api_has_no_force_argument() -> None:
    assert "force" not in inspect.signature(amend_implementation_draft_pr).parameters


def test_request_rejects_unauthorized_path() -> None:
    with pytest.raises(ValidationError, match="authorized scope"):
        ImplementationDraftPrAmendmentRequest.model_validate(
            {
                "repository": "owner/repo",
                "objective": "fix CI",
                "pr_number": 7,
                "base_branch": "main",
                "base_sha": "base",
                "work_branch": "agent/implementation/fix",
                "expected_head_sha": "old",
                "commit_message": "fix: CI",
                "authorized_components": [ComponentId.TESTING_FIXTURES],
                "changes": [
                    {
                        "ordinal": 1,
                        "change_id": "impl-change:0001",
                        "kind": "CREATE",
                        "path": "src/cisco_assessment/cli.py",
                        "component": ComponentId.RUNNER_CLI,
                        "proposed_content": "x = 1\n",
                        "proposed_content_sha256": "9e26bf369911c45c243c684147b23fc9e1dcfcf257d299a1c632016a6fcd33f4",
                        "proposed_byte_size": 6,
                        "rationale": "bad scope",
                        "acceptance_criteria": ["passes"],
                    }
                ],
            }
        )
