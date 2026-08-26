from inspect import signature

from cisco_assessment.devtools.implementation.draft_pr_amendment import (
    PR_BINDING_TIMEOUT_SECONDS,
    execute_draft_pr_amendment,
)


def test_pr_binding_timeout_is_distinct_from_ci_timeout() -> None:
    parameters = signature(execute_draft_pr_amendment).parameters

    assert PR_BINDING_TIMEOUT_SECONDS == 30.0
    assert parameters["timeout_seconds"].default == 900.0
    assert (
        parameters["pr_binding_timeout_seconds"].default
        == PR_BINDING_TIMEOUT_SECONDS
    )
