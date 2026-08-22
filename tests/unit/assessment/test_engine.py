from dataclasses import dataclass
from uuid import uuid4

import pytest

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    DuplicateRuleError,
    EvidenceRequest,
    FindingSeverity,
    NormalizedFieldSource,
    RuleCatalog,
    RuleDecision,
    RuleMetadata,
    SourceTrace,
)
from cisco_assessment.models import DeviceInfo
from cisco_assessment.models.enums import PlatformFamily


@dataclass
class StubRule:
    _metadata: RuleMetadata
    decision: RuleDecision | None = None
    error: Exception | None = None
    calls: int = 0

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: DeviceInfo, context: AssessmentContext) -> RuleDecision:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision


def _metadata(
    rule_id: str,
    *,
    platforms: frozenset[PlatformFamily] | None = None,
    normalized_model: str = "DeviceInfo",
) -> RuleMetadata:
    return RuleMetadata(
        rule_id=rule_id,
        version="0.1.0",
        title=f"Rule {rule_id}",
        description="Test-only rule.",
        category="test",
        severity=FindingSeverity.MEDIUM,
        normalized_model=normalized_model,
        supported_platforms=platforms
        or frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
    )


def _device() -> DeviceInfo:
    return DeviceInfo(
        platform=PlatformFamily.IOS_XE,
        hostname="SW-CORE-01",
        software_version="17.09.04a",
        model="C9300-48P",
    )


def _context() -> AssessmentContext:
    run_id = uuid4()
    source = SourceTrace(
        assessment_run_id=run_id,
        command_execution_id=uuid4(),
        raw_output_id=uuid4(),
        raw_sha256="a" * 64,
        parser_id="ios_show_version_v1",
        parser_version="0.1.0",
        platform=PlatformFamily.IOS_XE,
        extractor="iosxe_version_header",
        line_start=1,
        line_end=1,
    )
    return AssessmentContext(
        assessment_run_id=run_id,
        device_id=uuid4(),
        platform=PlatformFamily.IOS_XE,
        source_evidence=(
            NormalizedFieldSource(
                normalized_model="DeviceInfo",
                field_path="software_version",
                source=source,
            ),
        ),
    )


def test_engine_preserves_all_supported_statuses_and_builds_findings() -> None:
    statuses = (
        AssessmentStatus.PASS,
        AssessmentStatus.FAIL,
        AssessmentStatus.WARNING,
        AssessmentStatus.INFO,
        AssessmentStatus.NOT_APPLICABLE,
        AssessmentStatus.ERROR,
    )
    rules = [
        StubRule(
            _metadata(f"TEST-{index:03d}"),
            RuleDecision(status=status, message=f"result {status.value}"),
        )
        for index, status in enumerate(statuses, start=1)
    ]
    result = AssessmentEngine(RuleCatalog[DeviceInfo](rules)).evaluate(_device(), _context())

    assert tuple(outcome.status for outcome in result.outcomes) == statuses
    assert {finding.status for finding in result.findings} == {
        AssessmentStatus.FAIL,
        AssessmentStatus.WARNING,
        AssessmentStatus.INFO,
        AssessmentStatus.ERROR,
    }


def test_engine_resolves_normalized_field_to_raw_source_trace() -> None:
    context = _context()
    rule = StubRule(
        _metadata("TRACE-001"),
        RuleDecision(
            status=AssessmentStatus.FAIL,
            message="Software version requires review.",
            evidence=(
                EvidenceRequest(
                    field_path="software_version",
                    observed_value="17.09.04a",
                ),
            ),
        ),
    )

    result = AssessmentEngine(RuleCatalog[DeviceInfo]([rule])).evaluate(_device(), context)

    evidence = result.outcomes[0].evidence[0]
    assert evidence.normalized_model == "DeviceInfo"
    assert evidence.field_path == "software_version"
    assert evidence.observed_value == "17.09.04a"
    assert evidence.sources[0].assessment_run_id == context.assessment_run_id
    assert evidence.sources[0].raw_output_id == context.source_evidence[0].source.raw_output_id
    assert evidence.sources[0].command_execution_id == (
        context.source_evidence[0].source.command_execution_id
    )


def test_rule_exception_is_isolated_and_later_rule_still_executes() -> None:
    broken = StubRule(_metadata("ERROR-001"), error=RuntimeError("boom"))
    passing = StubRule(
        _metadata("PASS-002"),
        RuleDecision(status=AssessmentStatus.PASS, message="ok"),
    )

    result = AssessmentEngine(RuleCatalog[DeviceInfo]([passing, broken])).evaluate(
        _device(),
        _context(),
    )

    assert tuple(outcome.rule_id for outcome in result.outcomes) == ("ERROR-001", "PASS-002")
    assert result.outcomes[0].status is AssessmentStatus.ERROR
    assert result.outcomes[0].reason_code == "rule_execution_error"
    assert result.outcomes[0].error_type == "RuntimeError"
    assert result.outcomes[0].error_message == "boom"
    assert passing.calls == 1


def test_unsupported_platform_returns_not_applicable_without_calling_rule() -> None:
    rule = StubRule(
        _metadata("IOS-ONLY", platforms=frozenset({PlatformFamily.IOS})),
        RuleDecision(status=AssessmentStatus.FAIL, message="should not run"),
    )

    result = AssessmentEngine(RuleCatalog[DeviceInfo]([rule])).evaluate(_device(), _context())

    assert result.outcomes[0].status is AssessmentStatus.NOT_APPLICABLE
    assert result.outcomes[0].reason_code == "unsupported_platform"
    assert rule.calls == 0
    assert result.findings == ()


def test_wrong_normalized_model_is_not_applicable() -> None:
    rule = StubRule(
        _metadata("MODEL-001", normalized_model="InterfaceInfo"),
        RuleDecision(status=AssessmentStatus.FAIL, message="should not run"),
    )

    result = AssessmentEngine(RuleCatalog[DeviceInfo]([rule])).evaluate(_device(), _context())

    assert result.outcomes[0].status is AssessmentStatus.NOT_APPLICABLE
    assert result.outcomes[0].reason_code == "unsupported_normalized_model"
    assert rule.calls == 0


def test_finding_id_is_deterministic_for_same_run_device_and_rule() -> None:
    context = _context()
    rule = StubRule(
        _metadata("DET-001"),
        RuleDecision(status=AssessmentStatus.WARNING, message="review"),
    )
    engine = AssessmentEngine(RuleCatalog[DeviceInfo]([rule]))

    first = engine.evaluate(_device(), context)
    second = engine.evaluate(_device(), context)

    assert first.findings[0].finding_id == second.findings[0].finding_id


def test_catalog_rejects_duplicate_rule_ids() -> None:
    first = StubRule(
        _metadata("DUP-001"),
        RuleDecision(status=AssessmentStatus.PASS, message="one"),
    )
    second = StubRule(
        _metadata("DUP-001"),
        RuleDecision(status=AssessmentStatus.PASS, message="two"),
    )

    with pytest.raises(DuplicateRuleError):
        RuleCatalog[DeviceInfo]([first, second])


def test_context_rejects_source_evidence_from_another_assessment_run() -> None:
    source = SourceTrace(
        assessment_run_id=uuid4(),
        command_execution_id=uuid4(),
        raw_output_id=uuid4(),
        raw_sha256="b" * 64,
        parser_id="ios_show_version_v1",
        parser_version="0.1.0",
        platform=PlatformFamily.IOS_XE,
    )

    with pytest.raises(ValueError, match="assessment_run_id"):
        AssessmentContext(
            assessment_run_id=uuid4(),
            device_id=uuid4(),
            platform=PlatformFamily.IOS_XE,
            source_evidence=(
                NormalizedFieldSource(
                    normalized_model="DeviceInfo",
                    field_path="software_version",
                    source=source,
                ),
            ),
        )
