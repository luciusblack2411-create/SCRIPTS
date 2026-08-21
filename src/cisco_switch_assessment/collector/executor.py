from dataclasses import dataclass
from cisco_switch_assessment.catalog import CommandCatalog, CommandSpec
from cisco_switch_assessment.collector.exceptions import CollectorError, CommandAuthorizationError, CommandPolicyError, CommandTimeoutError, CommandUnsupportedError
from cisco_switch_assessment.collector.policy import ReadOnlyPolicy
from cisco_switch_assessment.collector.raw.repository import RawRepository
from cisco_switch_assessment.collector.session.base import NetworkSession
from cisco_switch_assessment.models import CommandExecution, CommandExecutionStatus, Device, RawCommandOutput, utcnow

@dataclass(frozen=True, slots=True)
class CommandCollectionResult:
    execution: CommandExecution
    raw_output: RawCommandOutput | None

class CommandExecutor:
    def __init__(self, *, policy: ReadOnlyPolicy, raw_repository: RawRepository) -> None:
        self._policy, self._raw_repository = policy, raw_repository

    def failed_before_command(self, *, run_id: str, device: Device, command: CommandSpec, error: CollectorError) -> CommandCollectionResult:
        now = utcnow()
        execution = CommandExecution(id=CommandExecution.new_id(), assessment_run_id=run_id, device_id=device.id, command_id=command.id.value, status=CommandExecutionStatus.FAILED, started_at=now, finished_at=now, error_code=error.error_code, error_message=str(error), raw_output_id=None)
        return CommandCollectionResult(execution=execution, raw_output=None)

    def execute(self, *, run_id: str, device: Device, catalog: CommandCatalog, command: CommandSpec, session: NetworkSession) -> CommandCollectionResult:
        execution_id, started_at = CommandExecution.new_id(), utcnow()
        raw = None; status = CommandExecutionStatus.FAILED; error_code = error_message = None
        try:
            self._policy.validate(catalog=catalog, command=command, platform=device.platform)
            raw = session.execute(command.cli, timeout=command.timeout_seconds).raw
            status = CommandExecutionStatus.SUCCESS
        except CommandPolicyError as exc:
            status, error_code, error_message = CommandExecutionStatus.POLICY_REJECTED, exc.error_code, str(exc)
        except CommandUnsupportedError as exc:
            raw, status, error_code, error_message = exc.partial_raw, CommandExecutionStatus.UNSUPPORTED, exc.error_code, str(exc)
        except CommandTimeoutError as exc:
            raw, status, error_code, error_message = exc.partial_raw, CommandExecutionStatus.TIMEOUT, exc.error_code, str(exc)
        except CommandAuthorizationError as exc:
            raw, status, error_code, error_message = exc.partial_raw, CommandExecutionStatus.AUTHORIZATION_FAILED, exc.error_code, str(exc)
        except CollectorError as exc:
            status, error_code, error_message = CommandExecutionStatus.FAILED, exc.error_code, str(exc)
        raw_output = None
        if raw is not None:
            try:
                raw_output = self._raw_repository.save(run_id=run_id, device_id=device.id, execution_id=execution_id, command=command, content=raw)
            except CollectorError as exc:
                status, error_code, error_message, raw_output = CommandExecutionStatus.FAILED, exc.error_code, str(exc), None
        finished_at = utcnow()
        execution = CommandExecution(id=execution_id, assessment_run_id=run_id, device_id=device.id, command_id=command.id.value, status=status, started_at=started_at, finished_at=finished_at, error_code=error_code, error_message=error_message, raw_output_id=raw_output.id if raw_output else None)
        return CommandCollectionResult(execution=execution, raw_output=raw_output)
