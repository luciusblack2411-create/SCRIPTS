from collections.abc import Callable, Iterable
from dataclasses import dataclass
from cisco_switch_assessment.catalog import CommandCatalog, CommandId
from cisco_switch_assessment.collector.exceptions import CollectorError
from cisco_switch_assessment.collector.executor import CommandCollectionResult, CommandExecutor
from cisco_switch_assessment.collector.session.factory import SessionFactory
from cisco_switch_assessment.collector.transport.base import SSHTimeouts, SSHTransport
from cisco_switch_assessment.models import Device

@dataclass(frozen=True, slots=True)
class DeviceCollectionResult:
    device_id: str
    commands: tuple[CommandCollectionResult, ...]

class DeviceCollector:
    def __init__(self, *, transport_factory: Callable[[], SSHTransport], session_factory: SessionFactory, executor: CommandExecutor, ssh_timeouts: SSHTimeouts | None = None) -> None:
        self._transport_factory, self._session_factory, self._executor = transport_factory, session_factory, executor
        self._ssh_timeouts = ssh_timeouts or SSHTimeouts()

    def collect(self, *, run_id: str, device: Device, catalog: CommandCatalog, command_ids: Iterable[CommandId] = (CommandId.SHOW_VERSION,)) -> DeviceCollectionResult:
        commands = tuple(catalog.get(command_id) for command_id in command_ids)
        transport = self._transport_factory(); session = None; results: list[CommandCollectionResult] = []
        try:
            transport.connect(device, self._ssh_timeouts)
            session = self._session_factory.create(device.platform, transport)
            session.open()
            for command in commands:
                results.append(self._executor.execute(run_id=run_id, device=device, catalog=catalog, command=command, session=session))
        except CollectorError as exc:
            completed_ids = {result.execution.command_id for result in results}
            for command in commands:
                if command.id.value not in completed_ids:
                    results.append(self._executor.failed_before_command(run_id=run_id, device=device, command=command, error=exc))
        finally:
            session.close() if session is not None else transport.close()
        return DeviceCollectionResult(device_id=device.id, commands=tuple(results))
