"""Authorized command execution and canonical result construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from cisco_assessment.catalog import CommandCatalog, CommandDefinition, CommandId
from cisco_assessment.collector.exceptions import (
    CollectorError,
    CommandCliError,
    CommandPolicyError,
    CommandTimeoutError,
    RawPersistenceError,
    SessionError,
    TransportError,
)
from cisco_assessment.collector.policy import ReadOnlyPolicy
from cisco_assessment.collector.session.base import NetworkSession
from cisco_assessment.models import (
    CommandExecution,
    CommandExecutionStatus,
    Device,
    RawCommandOutput,
)
from cisco_assessment.models.base import utc_now
from cisco_assessment.raw.repository import RawRepository


@dataclass(frozen=True, slots=True)
class CommandCollectionResult:
    execution: CommandExecution
    raw_output: RawCommandOutput | None
    raw_path: Path | None


class CommandExecutor:
    """Execute catalog commands only and preserve all received evidence."""

    def __init__(self, *, policy: ReadOnlyPolicy, raw_repository: RawRepository) -> None:
        self._policy = policy
        self._raw_repository = raw_repository

    def execute(
        self,
        *,
        assessment_run_id: UUID,
        device: Device,
        catalog: CommandCatalog,
        command_id: CommandId,
        sequence: int,
        session: NetworkSession,
        timeout: float,
    ) -> CommandCollectionResult:
        started_at = utc_now()
        execution_id = uuid4()

        try:
            authorized = self._policy.authorize(
                catalog=catalog,
                command_id=command_id,
                platform=device.platform_family,
            )
        except CommandPolicyError as exc:
            definition = catalog.get(command_id)
            command = self._metadata_command(definition=definition, device=device)
            return self._result(
                execution_id=execution_id,
                assessment_run_id=assessment_run_id,
                command_key=command_id.value,
                command=command,
                sequence=sequence,
                started_at=started_at,
                status=CommandExecutionStatus.SKIPPED,
                error_type=exc.error_type,
                error_message=str(exc),
            )

        command = authorized.variant.cli_command
        raw: bytes | None = None
        is_truncated = False
        status = CommandExecutionStatus.SUCCESS
        error_type: str | None = None
        error_message: str | None = None

        try:
            raw = session.execute(command, timeout=timeout).raw
        except CommandTimeoutError as exc:
            raw = exc.partial_raw
            is_truncated = True
            status = CommandExecutionStatus.TIMEOUT
            error_type = exc.error_type
            error_message = str(exc)
        except CommandCliError as exc:
            raw = exc.partial_raw
            status = CommandExecutionStatus.CLI_ERROR
            error_type = exc.cli_error_type
            error_message = str(exc)
        except (TransportError, SessionError) as exc:
            status = CommandExecutionStatus.TRANSPORT_ERROR
            error_type = exc.error_type
            error_message = str(exc)
        except CollectorError as exc:
            status = CommandExecutionStatus.TRANSPORT_ERROR
            error_type = exc.error_type
            error_message = str(exc)

        raw_output: RawCommandOutput | None = None
        raw_path: Path | None = None
        if raw is not None:
            try:
                persisted = self._raw_repository.save(
                    assessment_run_id=assessment_run_id,
                    device_id=device.id,
                    command_execution_id=execution_id,
                    command_key=command_id.value,
                    sequence=sequence,
                    content=raw,
                    is_truncated=is_truncated,
                )
                raw_output = persisted.output
                raw_path = persisted.path
            except RawPersistenceError as exc:
                status = CommandExecutionStatus.TRANSPORT_ERROR
                error_type = exc.error_type
                error_message = str(exc)
                raw_output = None
                raw_path = None

        return self._result(
            execution_id=execution_id,
            assessment_run_id=assessment_run_id,
            command_key=command_id.value,
            command=command,
            sequence=sequence,
            started_at=started_at,
            status=status,
            error_type=error_type,
            error_message=error_message,
            raw_output=raw_output,
            raw_path=raw_path,
        )

    def failed_before_command(
        self,
        *,
        assessment_run_id: UUID,
        device: Device,
        catalog: CommandCatalog,
        command_id: CommandId,
        sequence: int,
        error: CollectorError,
    ) -> CommandCollectionResult:
        started_at = utc_now()
        definition = catalog.get(command_id)
        command = self._metadata_command(definition=definition, device=device)
        status = (
            CommandExecutionStatus.SKIPPED
            if isinstance(error, CommandPolicyError)
            else CommandExecutionStatus.TRANSPORT_ERROR
        )
        return self._result(
            execution_id=uuid4(),
            assessment_run_id=assessment_run_id,
            command_key=command_id.value,
            command=command,
            sequence=sequence,
            started_at=started_at,
            status=status,
            error_type=error.error_type,
            error_message=str(error),
        )

    @staticmethod
    def _metadata_command(*, definition: CommandDefinition, device: Device) -> str:
        variant = definition.variants.get(device.platform_family)
        if variant is not None:
            return str(variant.cli_command)
        return "show <unsupported>"

    @staticmethod
    def _result(
        *,
        execution_id: UUID,
        assessment_run_id: UUID,
        command_key: str,
        command: str,
        sequence: int,
        started_at: datetime,
        status: CommandExecutionStatus,
        error_type: str | None,
        error_message: str | None,
        raw_output: RawCommandOutput | None = None,
        raw_path: Path | None = None,
    ) -> CommandCollectionResult:
        finished_at = utc_now()
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        execution = CommandExecution(
            id=execution_id,
            assessment_run_id=assessment_run_id,
            command_key=command_key,
            command=command,
            sequence=sequence,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            status=status,
            error_type=error_type,
            error_message=error_message,
        )
        return CommandCollectionResult(
            execution=execution,
            raw_output=raw_output,
            raw_path=raw_path,
        )
