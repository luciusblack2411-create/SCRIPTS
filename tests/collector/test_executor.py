from uuid import uuid4

from cisco_assessment.catalog import COMMAND_CATALOG_V0_1, CommandId
from cisco_assessment.collector.exceptions import CommandCliError, CommandTimeoutError
from cisco_assessment.collector.executor import CommandExecutor
from cisco_assessment.collector.policy import ReadOnlyPolicy
from cisco_assessment.models import CommandExecutionStatus, Device, PlatformFamily

from .fakes import FakeSession, InMemoryRawRepository


def _device() -> Device:
    return Device(management_address="192.0.2.10", platform_family=PlatformFamily.IOS_XE)


def test_show_version_produces_current_models_and_preserves_exact_raw() -> None:
    raw = b"show version\r\nCisco IOS XE Software  \r\n\x1b[0mSW1#"
    repository = InMemoryRawRepository()
    executor = CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=repository)

    result = executor.execute(
        assessment_run_id=uuid4(),
        device=_device(),
        catalog=COMMAND_CATALOG_V0_1,
        command_id=CommandId.SYSTEM_VERSION,
        sequence=1,
        session=FakeSession(raw),
        timeout=30.0,
    )

    assert result.execution.status is CommandExecutionStatus.SUCCESS
    assert result.execution.command_key == CommandId.SYSTEM_VERSION.value
    assert result.execution.command == "show version"
    assert repository.saved == raw
    assert result.raw_output is not None
    assert result.raw_output.content.encode(result.raw_output.encoding) == raw


def test_timeout_persists_partial_raw_as_truncated() -> None:
    partial = b"show version\r\nCisco IOS XE Software"
    repository = InMemoryRawRepository()
    executor = CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=repository)

    result = executor.execute(
        assessment_run_id=uuid4(),
        device=_device(),
        catalog=COMMAND_CATALOG_V0_1,
        command_id=CommandId.SYSTEM_VERSION,
        sequence=1,
        session=FakeSession(CommandTimeoutError("timeout", partial_raw=partial)),
        timeout=1.0,
    )

    assert result.execution.status is CommandExecutionStatus.TIMEOUT
    assert repository.saved == partial
    assert repository.truncated is True
    assert result.raw_output is not None and result.raw_output.is_truncated is True


def test_cli_error_persists_device_response() -> None:
    raw = b"show version\r\n% Authorization failed\r\nSW1#"
    repository = InMemoryRawRepository()
    executor = CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=repository)
    error = CommandCliError(
        "denied",
        cli_error_type="command_authorization_failed",
        partial_raw=raw,
    )

    result = executor.execute(
        assessment_run_id=uuid4(),
        device=_device(),
        catalog=COMMAND_CATALOG_V0_1,
        command_id=CommandId.SYSTEM_VERSION,
        sequence=1,
        session=FakeSession(error),
        timeout=30.0,
    )

    assert result.execution.status is CommandExecutionStatus.CLI_ERROR
    assert result.execution.error_type == "command_authorization_failed"
    assert repository.saved == raw
