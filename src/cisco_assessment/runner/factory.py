"""Dependency composition for the end-to-end runner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from cisco_assessment import __version__
from cisco_assessment.assessment import (
    AssessmentEngine,
    RuleCatalog,
    device_info_rule_catalog,
    hardware_inventory_rule_catalog,
)
from cisco_assessment.catalog import COMMAND_CATALOG_V0_1, CommandCatalog
from cisco_assessment.collector import CommandExecutor, DeviceCollector, ReadOnlyPolicy
from cisco_assessment.collector.session.factory import SessionFactory
from cisco_assessment.collector.transport import (
    ParamikoSSHTransport,
    SSHConnectionOptions,
    SSHTransport,
)
from cisco_assessment.models import DeviceInfo, HardwareInventory
from cisco_assessment.parsers import ParserRegistry, build_parser_registry
from cisco_assessment.raw import FilesystemRawRepository
from cisco_assessment.reporting import AssessmentReportBuilder, JsonReportRenderer

from .hardware import HardwareInventoryAssessmentRunner
from .plan import SHOW_VERSION_PLAN_V0_2, AssessmentPlan
from .service import AssessmentRunner


def _ruleset_version(*catalogs: RuleCatalog[Any]) -> str:
    versions = sorted({rule.metadata.version for catalog in catalogs for rule in catalog.rules})
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
    command_catalog: CommandCatalog = COMMAND_CATALOG_V0_1,
    parser_registry: ParserRegistry | None = None,
    default_plan: AssessmentPlan = SHOW_VERSION_PLAN_V0_2,
) -> AssessmentRunner:
    """Compose the productive pipeline while allowing test dependency injection."""
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
    device_rules = device_info_rule_catalog()
    hardware_rules = hardware_inventory_rule_catalog()
    return HardwareInventoryAssessmentRunner(
        framework_version=__version__,
        collector=collector,
        parser_registry=parser_registry or build_parser_registry(),
        command_catalog=command_catalog,
        assessment_engine=AssessmentEngine[DeviceInfo](device_rules),
        hardware_inventory_engine=AssessmentEngine[HardwareInventory](hardware_rules),
        report_builder=AssessmentReportBuilder(),
        report_renderer=JsonReportRenderer(),
        report_root=Path(output_root),
        ruleset_version=_ruleset_version(device_rules, hardware_rules),
        default_plan=default_plan,
    )


def build_default_runner(
    *,
    output_root: Path,
    port: int = 22,
    strict_host_key: bool = True,
    command_timeout: float = 30.0,
    default_plan: AssessmentPlan = SHOW_VERSION_PLAN_V0_2,
) -> AssessmentRunner:
    """Compose the production runner using Paramiko and the selected plan."""

    def transport_factory() -> SSHTransport:
        return ParamikoSSHTransport()

    return build_runner(
        output_root=output_root,
        transport_factory=transport_factory,
        port=port,
        strict_host_key=strict_host_key,
        command_timeout=command_timeout,
        default_plan=default_plan,
    )
