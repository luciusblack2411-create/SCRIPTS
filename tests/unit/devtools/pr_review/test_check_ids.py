from cisco_assessment.devtools.pr_review import ReviewCheckId


def test_check_ids_are_unique_and_stable() -> None:
    values = [check_id.value for check_id in ReviewCheckId]

    assert len(values) == len(set(values))
    assert ReviewCheckId.GIT_001.value == "GIT-001"
    assert ReviewCheckId.SAFE_001.value == "SAFE-001"
    assert ReviewCheckId.PARSER_012.value == "PARSER-012"
    assert ReviewCheckId.CONTRACT_009.value == "CONTRACT-009"
