from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.catalog import CommandId
from cisco_assessment.runner import AssessmentPlan, AssessmentPlanItem


def test_assessment_plan_preserves_command_order() -> None:
    plan = AssessmentPlan(
        plan_id="ordered",
        version="0.2",
        commands=(
            AssessmentPlanItem(command_id=CommandId.SYSTEM_VERSION),
            AssessmentPlanItem(command_id=CommandId.SYSTEM_STACK),
            AssessmentPlanItem(command_id=CommandId.TIME_NTP_STATUS),
        ),
    )

    assert plan.command_ids == (
        CommandId.SYSTEM_VERSION,
        CommandId.SYSTEM_STACK,
        CommandId.TIME_NTP_STATUS,
    )


def test_assessment_plan_rejects_duplicate_commands() -> None:
    with pytest.raises(ValidationError, match="duplicate command IDs"):
        AssessmentPlan(
            plan_id="duplicates",
            version="0.2",
            commands=(
                AssessmentPlanItem(command_id=CommandId.SYSTEM_VERSION),
                AssessmentPlanItem(command_id=CommandId.SYSTEM_VERSION),
            ),
        )


def test_assessment_plan_rejects_empty_command_sequence() -> None:
    with pytest.raises(ValidationError, match="at least one command"):
        AssessmentPlan(
            plan_id="empty",
            version="0.2",
            commands=(),
        )
