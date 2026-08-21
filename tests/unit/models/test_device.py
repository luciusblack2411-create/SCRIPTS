from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from cisco_assessment.models import Device, PlatformFamily


def test_device_generates_id_and_utc_timestamps() -> None:
    device = Device(
        management_address="10.10.10.20",
        hostname=" SW-CORE-01 ",
        platform_family=PlatformFamily.IOS_XE,
    )

    assert device.id is not None
    assert device.hostname == "SW-CORE-01"
    assert device.vendor == "cisco"
    assert device.created_at.utcoffset() == timedelta(0)
    assert device.updated_at.utcoffset() == timedelta(0)


def test_device_rejects_blank_management_address() -> None:
    with pytest.raises(ValidationError):
        Device(management_address="   ")


def test_device_rejects_updated_at_before_created_at() -> None:
    created = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        Device(
            management_address="10.10.10.20",
            created_at=created,
            updated_at=created - timedelta(seconds=1),
        )


def test_device_snapshot_does_not_include_observed_deviceinfo_fields() -> None:
    device = Device(
        management_address="10.10.10.20",
        hostname="SW-CORE-01",
        platform_family=PlatformFamily.IOS_XE,
    )

    snapshot = device.snapshot()

    assert snapshot.management_address == device.management_address
    assert snapshot.hostname == device.hostname
    assert "id" not in snapshot.model_fields_set
    assert not hasattr(snapshot, "serial_number")
    assert not hasattr(snapshot, "os_version")
