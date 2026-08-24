from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.human_merge_gate import HumanMergeAuthorization


def test_human_merge_authorization_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HumanMergeAuthorization.model_validate(
            {
                "decision": "MERGE_APPROVED",
                "repository": "luciusblack2411-create/SCRIPTS",
                "pr_number": 1,
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "authorized_by": "human-operator",
                "rationale": "Explicit human approval.",
                "auto_merge": True,
            }
        )
