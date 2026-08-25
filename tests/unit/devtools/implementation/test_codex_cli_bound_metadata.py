from __future__ import annotations

import json

from cisco_assessment.devtools.implementation.codex_cli_backend import (
    _codex_structured_output_schema,
)


def test_local_codex_schema_binds_echoed_metadata_to_exact_prompt_values() -> None:
    objective = (
        "Add a TESTING_FIXTURES-only regression for Pydantic serialization of "
        "LocalFeatureExecutionPreflight while using local_feature_execution.py "
        "exclusively as read-only evidence."
    )
    prompt = json.dumps(
        {
            "instructions": "proposal only",
            "input": {
                "repository": "luciusblack2411-create/SCRIPTS",
                "base_sha": "72ea3dffd9e31f2367768675317338414108dab1",
                "objective": objective,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    schema = _codex_structured_output_schema(prompt)

    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["repository"]["const"] == "luciusblack2411-create/SCRIPTS"
    assert (
        properties["base_sha"]["const"]
        == "72ea3dffd9e31f2367768675317338414108dab1"
    )
    assert properties["objective"]["const"] == objective


def test_local_codex_schema_keeps_fail_closed_output_contract_for_unbound_prompt() -> None:
    schema = _codex_structured_output_schema("non-json prompt")

    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert "const" not in properties["repository"]
    assert "const" not in properties["base_sha"]
    assert "const" not in properties["objective"]
    assert properties["repository_mutation_requested"]["const"] is False
    assert properties["contract_approval_claimed"]["const"] is False
    assert properties["cisco_execution_allowed"]["const"] is False
