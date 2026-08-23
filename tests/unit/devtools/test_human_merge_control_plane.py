from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisco_assessment.devtools.human_merge_control_plane import (
    HUMAN_MERGE_TOKEN_ENV,
    PR_REVIEW_TOKEN_ENV,
    HumanMergeControlPlaneError,
    load_human_merge_operation,
    resolve_human_merge_tokens,
)
from cisco_assessment.devtools.human_merge_gate import HumanMergeOperation
from cisco_assessment.devtools.pr_review.enums import ComponentId
from cisco_assessment.devtools.pr_review.models import ReviewRequest


def test_resolver_requires_two_distinct_dedicated_tokens() -> None:
    review, merge = resolve_human_merge_tokens(
        {PR_REVIEW_TOKEN_ENV: "review-token", HUMAN_MERGE_TOKEN_ENV: "merge-token"}
    )
    assert review == "review-token"
    assert merge == "merge-token"

    with pytest.raises(HumanMergeControlPlaneError, match="must be distinct"):
        resolve_human_merge_tokens(
            {PR_REVIEW_TOKEN_ENV: "same-token", HUMAN_MERGE_TOKEN_ENV: "same-token"}
        )


def test_resolver_never_falls_back_to_ambient_github_tokens() -> None:
    with pytest.raises(HumanMergeControlPlaneError, match=PR_REVIEW_TOKEN_ENV):
        resolve_human_merge_tokens({"GITHUB_TOKEN": "ambient", "GH_TOKEN": "ambient-too"})


def test_operation_file_is_strict_and_round_trips(tmp_path: Path) -> None:
    operation = HumanMergeOperation.model_validate(
        {
            "review_request": ReviewRequest(
                repository="luciusblack2411-create/SCRIPTS",
                pr_number=71,
                objective="Approved feature",
                expected_components=(ComponentId.TESTING_FIXTURES,),
            ),
            "authorization": {
                "decision": "MERGE_APPROVED",
                "repository": "luciusblack2411-create/SCRIPTS",
                "pr_number": 71,
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "authorized_by": "human-operator",
                "rationale": "Explicit approval",
            },
        }
    )
    path = tmp_path / "merge.json"
    path.write_text(operation.model_dump_json(indent=2), encoding="utf-8")

    loaded = load_human_merge_operation(path)

    assert loaded == operation

    invalid = json.loads(operation.model_dump_json())
    invalid["unexpected"] = True
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(Exception, match="invalid human merge operation"):
        load_human_merge_operation(path)
