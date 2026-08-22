"""Per-device Collector orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from cisco_assessment.catalog import CommandCatalog, CommandId
from cisco_assessment.collector.exceptions import CollectorError, CommandPolicyError
from cisco_assessment.collector.executor import CommandCollectionResult, CommandExecutor
from cisco_assessment.collector.policy import ReadOnlyPolicy
from cisco_assessment.collector.session.base import NetworkSession
from cisco_assessment.collector.session.factory import SessionFactory
from cisco_assessment.collector.transport.base import (
    SSHConnectionOptions,
    SSHCredentials,
    SSHTimeouts,
    SSHTransport,
)
from cisco_assessment.models import Device


@dataclass(frozen=True, slots=True)
class DeviceCollectionResult:
    device_id: UUID
    commands: tuple[CommandCollectionResult, ...]


class DeviceCollector:
    """Collect catalog-defined queries from exactly one device/session."""

    def __init__(
        self,
        *,
        transport_factory: Callable[[], SSHTransport],
        session_factory: SessionFactory,
        executor: CommandExecutor,
        policy: ReadOnlyPolicy,
        ssh_timeouts: SSHTimeouts | None = None,
        connection_options: SSHConnectionOptions | None = None,
        command_timeout: float = 30.0,
    ) -> None:
        if command_timeout <= 0:
            raise ValueError("command timeout must be greater than zero")
        self._transport_factory = transport_factory
        self._session_factory = session_factory
        self._executor = executor
        self._policy = policy
        self._ssh_timeouts = ssh_timeouts or SSHTimeouts()
        self._connection_options = connection_options or SSHConnectionOptions()
        self._command_timeout = command_timeout

    def collect(
        self,
        *,
        assessment_run_id: UUID,
        device: Device,
        credentials: SSHCredentials,
        catalog: CommandCatalog,
        command_ids: Iterable[CommandId] = (CommandId.SYSTEM_VERSION,),
    ) -> DeviceCollectionResult:
        requested = tuple(command_ids)
        preflight_errors: dict[CommandId, CommandPolicyError] = {}
        executable: list[CommandId] = []

        for command_id in requested:
            try:
                self._policy.authorize(
                    catalog=catalog,
                    command_id=command_id,
                    platform=device.platform_family,
                )
                executable.append(command_id)
            except CommandPolicyError as exc:
                preflight_errors[command_id] = exc

        results: list[CommandCollectionResult] = []
        for sequence, command_id in enumerate(requested, start=1):
            if command_id in preflight_errors:
                results.append(
                    self._executor.failed_before_command(
                        assessment_run_id=assessment_run_id,
                        device=device,
                        catalog=catalog,
                        command_id=command_id,
                        sequence=sequence,
                        error=preflight_errors[command_id],
                    )
                )

        if not executable:
            return DeviceCollectionResult(device_id=device.id, commands=tuple(results))

        transport = self._transport_factory()
        session: NetworkSession | None = None
        try:
            transport.connect(
                device=device,
                credentials=credentials,
                options=self._connection_options,
                timeouts=self._ssh_timeouts,
            )
            session = self._session_factory.create(
                platform=device.platform_family,
                transport=transport,
            )
            session.open()

            for sequence, command_id in enumerate(requested, start=1):
                if command_id not in executable:
                    continue
                results.append(
                    self._executor.execute(
                        assessment_run_id=assessment_run_id,
                        device=device,
                        catalog=catalog,
                        command_id=command_id,
                        sequence=sequence,
                        session=session,
                        timeout=self._command_timeout,
                    )
                )
        except CollectorError as exc:
            completed = {result.execution.command_key for result in results}
            for sequence, command_id in enumerate(requested, start=1):
                if command_id not in executable or command_id.value in completed:
                    continue
                results.append(
                    self._executor.failed_before_command(
                        assessment_run_id=assessment_run_id,
                        device=device,
                        catalog=catalog,
                        command_id=command_id,
                        sequence=sequence,
                        error=exc,
                    )
                )
        finally:
            if session is not None:
                session.close()
            else:
                transport.close()

        results.sort(key=lambda result: result.execution.sequence)
        return DeviceCollectionResult(device_id=device.id, commands=tuple(results))
