from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.catalog import CommandId
from cisco_assessment.runner import (
    HARDWARE_INVENTORY_PLAN_V0_1,
    SHOW_VERSION_PLAN_V0_2,
    AssessmentPlan,
    AssessmentPlanItem,
    ProductiveAssessmentPlanId,
    resolve_productive_assessment_plan,
)


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


def test_productive_hardware_inventory_plan_runs_version_then_inventory() -> None:
    assert HARDWARE_INVENTORY_PLAN_V0_1.command_ids == (
        CommandId.SYSTEM_VERSION,
        CommandId.SYSTEM_INVENTORY,
    )
    assert SHOW_VERSION_PLAN_V0_2.command_ids == (CommandId.SYSTEM_VERSION,)


def test_productive_plan_registry_resolves_only_whitelisted_plans() -> None:
    assert (
        resolve_productive_assessment_plan(ProductiveAssessmentPlanId.SHOW_VERSION)
        is SHOW_VERSION_PLAN_V0_2
    )
    assert (
        resolve_productive_assessment_plan(ProductiveAssessmentPlanId.HARDWARE_INVENTORY)
        is HARDWARE_INVENTORY_PLAN_V0_1
    )
    with pytest.raises(ValueError):
        ProductiveAssessmentPlanId("show inventory")


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
