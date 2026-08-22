"""Dependency composition for the end-to-end runner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cisco_assessment import __version__
from cisco_assessment.assessment import AssessmentEngine, RuleCatalog, device_info_rule_catalog
from cisco_assessment.catalog import COMMAND_CATALOG_V0_1
from cisco_assessment.collector import CommandExecutor, DeviceCollector, ReadOnlyPolicy
from cisco_assessment.collector.session.factory import SessionFactory
from cisco_assessment.collector.transport import (
    ParamikoSSHTransport,
    SSHConnectionOptions,
    SSHTransport,
)
from cisco_assessment.models import DeviceInfo
from cisco_assessment.parsers import build_parser_registry
from cisco_assessment.raw import FilesystemRawRepository
from cisco_assessment.reporting import AssessmentReportBuilder, JsonReportRenderer

from .service import AssessmentRunner


def _ruleset_version(catalog: RuleCatalog[DeviceInfo]) -> str:
    versions = sorted({rule.metadata.version for rule in catalog.rules})
    if not versions:
        return "0.1.0"
    return "+".join(versions)


def build_runner(
    *,
    output_root: Path,
    transport_factory: Callable[[], SSHTransport],
    port: int = 22,
    strict_host_key: bool = True,
    command_timeout: float = 30.0,
) -> AssessmentRunner:
    """Compose the v0.1 pipeline while allowing transport injection for tests."""
    policy = ReadOnlyPolicy()
    raw_repository = FilesystemRawRepository(Path(output_root))
    executor = CommandExecutor(policy=policy, raw_repository=raw_repository)
    collector = DeviceCollector(
        transport_factory=transport_factory,
        session_factory=SessionFactory(),
        executor=executor,
        policy=policy,
        connection_options=SSHConnectionOptions(
            port=port,
            strict_host_key=strict_host_key,
        ),
        command_timeout=command_timeout,
    )
    rule_catalog = device_info_rule_catalog()
    return AssessmentRunner(
        framework_version=__version__,
        collector=collector,
        parser_registry=build_parser_registry(),
        command_catalog=COMMAND_CATALOG_V0_1,
        assessment_engine=AssessmentEngine[DeviceInfo](rule_catalog),
        report_builder=AssessmentReportBuilder(),
        report_renderer=JsonReportRenderer(),
        report_root=Path(output_root),
        ruleset_version=_ruleset_version(rule_catalog),
    )


def build_default_runner(
    *,
    output_root: Path,
    port: int = 22,
    strict_host_key: bool = True,
    command_timeout: float = 30.0,
) -> AssessmentRunner:
    """Compose the production runner using the existing Paramiko transport."""

    def transport_factory() -> SSHTransport:
        return ParamikoSSHTransport()

    return build_runner(
        output_root=output_root,
        transport_factory=transport_factory,
        port=port,
        strict_host_key=strict_host_key,
        command_timeout=command_timeout,
    )
