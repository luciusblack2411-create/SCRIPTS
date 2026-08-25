from __future__ import annotations

import json

from cisco_assessment.devtools.implementation.codex_cli_backend import (
    _codex_structured_output_schema,
)


def _property(schema: dict[str, object], name: str) -> dict[str, object]:
    properties = schema["properties"]
    assert isinstance(properties, dict)
    field_schema = properties[name]
    assert isinstance(field_schema, dict)
    return field_schema


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

    assert _property(schema, "repository")["const"] == "luciusblack2411-create/SCRIPTS"
    assert (
        _property(schema, "base_sha")["const"]
        == "72ea3dffd9e31f2367768675317338414108dab1"
    )
    assert _property(schema, "objective")["const"] == objective


def test_local_codex_schema_keeps_fail_closed_output_contract_for_unbound_prompt() -> None:
    schema = _codex_structured_output_schema("non-json prompt")

    assert "const" not in _property(schema, "repository")
    assert "const" not in _property(schema, "base_sha")
    assert "const" not in _property(schema, "objective")
    assert _property(schema, "repository_mutation_requested")["const"] is False
    assert _property(schema, "contract_approval_claimed")["const"] is False
    assert _property(schema, "cisco_execution_allowed")["const"] is False
