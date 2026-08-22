from uuid import uuid4

import pytest

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    FindingSeverity,
    IOSXEBootModeRule,
    NonDefaultHostnameRule,
    NormalizedFieldSource,
    RuleCatalog,
    RuleCategory,
    SoftwareVersionObservedRule,
    SourceTrace,
    device_info_rule_catalog,
)
from cisco_assessment.models import DeviceInfo
from cisco_assessment.models.enums import PlatformFamily


def _device(
    *,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
    hostname: str | None = "SW-CORE-01",
    boot_mode: str | None = "INSTALL",
) -> DeviceInfo:
    return DeviceInfo(
        platform=platform,
        hostname=hostname,
        software_version="17.09.04a",
        model="C9300-48P",
        serial_number="FCW00000001",
        system_image="flash:packages.conf",
        uptime_text="2 weeks, 1 day, 3 hours, 4 minutes",
        boot_mode=boot_mode,
    )


def _context(
    *,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
    fields: tuple[str, ...] = ("hostname", "boot_mode", "software_version", "system_image"),
) -> AssessmentContext:
    run_id = uuid4()
    source = SourceTrace(
        assessment_run_id=run_id,
        command_execution_id=uuid4(),
        raw_output_id=uuid4(),
        raw_sha256="a" * 64,
        parser_id="ios_show_version_v1",
        parser_version="0.1.0",
        platform=platform,
        extractor="show_version",
        line_start=1,
        line_end=12,
    )
    return AssessmentContext(
        assessment_run_id=run_id,
        device_id=uuid4(),
        platform=platform,
        source_evidence=tuple(
            NormalizedFieldSource(
                normalized_model="DeviceInfo",
                field_path=field,
                source=source,
            )
            for field in fields
        ),
    )


def _evaluate(rule: object, device: DeviceInfo, context: AssessmentContext):
    return AssessmentEngine(RuleCatalog[DeviceInfo]([rule])).evaluate(device, context).outcomes[0]


def test_device_info_catalog_has_stable_ids_and_declared_contract() -> None:
    catalog = device_info_rule_catalog()

    assert tuple(rule.metadata.rule_id for rule in catalog.rules) == (
        "SYS-001",
        "SYS-002",
        "SYS-003",
    )
    assert all(rule.metadata.category == RuleCategory.SYSTEM for rule in catalog.rules)
    assert all(rule.metadata.evidence_fields for rule in catalog.rules)
    assert all(rule.metadata.recommendation for rule in catalog.rules)
    assert catalog.rules[0].metadata.severity is FindingSeverity.LOW


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("SW-CORE-01", AssessmentStatus.PASS),
        ("Switch", AssessmentStatus.FAIL),
        ("router", AssessmentStatus.FAIL),
    ],
)
def test_sys_001_hostname_rule_is_deterministic(hostname: str, expected: AssessmentStatus) -> None:
    outcome = _evaluate(NonDefaultHostnameRule(), _device(hostname=hostname), _context())

    assert outcome.rule_id == "SYS-001"
    assert outcome.status is expected
    assert outcome.evidence[0].field_path == "hostname"
    assert outcome.evidence[0].observed_value == hostname


def test_sys_001_finding_preserves_normalized_to_raw_traceability() -> None:
    context = _context()
    outcome = _evaluate(NonDefaultHostnameRule(), _device(hostname="Switch"), context)

    assert outcome.status is AssessmentStatus.FAIL
    assert len(outcome.evidence[0].sources) == 1
    assert outcome.evidence[0].sources[0].raw_output_id == (
        context.source_evidence[0].source.raw_output_id
    )
    assert outcome.evidence[0].sources[0].command_execution_id == (
        context.source_evidence[0].source.command_execution_id
    )
    assert outcome.evidence[0].sources[0].raw_sha256 == "a" * 64


def test_sys_001_missing_hostname_is_error_not_false_fail() -> None:
    outcome = _evaluate(
        NonDefaultHostnameRule(),
        _device(hostname=None),
        _context(fields=("software_version",)),
    )

    assert outcome.status is AssessmentStatus.ERROR
    assert outcome.reason_code == "missing_required_data"
    assert outcome.evidence[0].field_path == "hostname"
    assert outcome.evidence[0].observed_value is None


@pytest.mark.parametrize(
    ("boot_mode", "expected"),
    [
        ("INSTALL", AssessmentStatus.PASS),
        ("BUNDLE", AssessmentStatus.WARNING),
        ("UNKNOWN", AssessmentStatus.INFO),
    ],
)
def test_sys_002_iosxe_boot_mode_statuses(boot_mode: str, expected: AssessmentStatus) -> None:
    outcome = _evaluate(IOSXEBootModeRule(), _device(boot_mode=boot_mode), _context())

    assert outcome.status is expected
    assert outcome.evidence[0].field_path == "boot_mode"
    assert outcome.recommendation is not None


def test_sys_002_is_not_applicable_to_ios() -> None:
    outcome = _evaluate(
        IOSXEBootModeRule(),
        _device(platform=PlatformFamily.IOS, boot_mode=None),
        _context(platform=PlatformFamily.IOS, fields=("software_version",)),
    )

    assert outcome.status is AssessmentStatus.NOT_APPLICABLE
    assert outcome.reason_code == "unsupported_platform"


def test_sys_002_missing_boot_mode_is_not_applicable() -> None:
    outcome = _evaluate(
        IOSXEBootModeRule(),
        _device(boot_mode=None),
        _context(fields=("software_version",)),
    )

    assert outcome.status is AssessmentStatus.NOT_APPLICABLE
    assert outcome.reason_code == "missing_required_data"


def test_sys_003_is_informational_and_keeps_software_evidence() -> None:
    outcome = _evaluate(SoftwareVersionObservedRule(), _device(), _context())

    assert outcome.status is AssessmentStatus.INFO
    assert tuple(item.field_path for item in outcome.evidence) == (
        "software_version",
        "system_image",
    )
    assert outcome.evidence[0].sources
    assert outcome.recommendation is not None
