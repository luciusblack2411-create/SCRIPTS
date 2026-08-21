from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    AssessmentRun,
    AssessmentRunStatus,
    Device,
    PlatformFamily,
)


def test_assessment_run_keeps_device_reference_and_target_snapshot() -> None:
    device = Device(
        management_address="10.10.10.20",
        hostname="SW-CORE-01",
        platform_family=PlatformFamily.IOS_XE,
    )

    run = AssessmentRun(
        device_id=device.id,
        framework_version="0.1.0",
        target_snapshot=device.snapshot(),
        status=AssessmentRunStatus.RUNNING,
    )

    assert run.device_id == device.id
    assert run.target_snapshot.hostname == "SW-CORE-01"
    assert run.schema_version == "0.1"


def test_assessment_run_normalizes_aware_timestamp_to_utc() -> None:
    local = timezone(timedelta(hours=-6))
    started = datetime(2026, 8, 21, 17, 14, tzinfo=local)
    device = Device(management_address="10.10.10.20")

    run = AssessmentRun(
        device_id=device.id,
        framework_version="0.1.0",
        target_snapshot=device.snapshot(),
        started_at=started,
    )

    assert run.started_at.hour == 23
    assert run.started_at.utcoffset() == timedelta(0)


def test_assessment_run_rejects_naive_timestamp() -> None:
    device = Device(management_address="10.10.10.20")

    with pytest.raises(ValidationError):
        AssessmentRun(
            device_id=device.id,
            framework_version="0.1.0",
            target_snapshot=device.snapshot(),
            started_at=datetime(2026, 8, 21, 17, 14),
        )


def test_assessment_run_rejects_finish_before_start() -> None:
    device = Device(management_address="10.10.10.20")
    started = datetime(2026, 8, 21, 23, 14, tzinfo=timezone.utc)

    with pytest.raises(ValidationError):
        AssessmentRun(
            device_id=device.id,
            framework_version="0.1.0",
            target_snapshot=device.snapshot(),
            started_at=started,
            finished_at=started - timedelta(seconds=1),
        )
