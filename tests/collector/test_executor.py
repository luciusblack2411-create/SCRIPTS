from cisco_switch_assessment.catalog import MVP_COMMAND_CATALOG, CommandId, CommandSpec
from cisco_switch_assessment.collector.exceptions import CommandTimeoutError
from cisco_switch_assessment.collector.executor import CommandExecutor
from cisco_switch_assessment.collector.policy import ReadOnlyPolicy
from cisco_switch_assessment.models import CommandExecutionStatus, Device, Platform
from .fakes import FakeSession, InMemoryRawRepository

def device(): return Device(id="sw-core-01", host="192.0.2.10", platform=Platform.IOS_XE, username="assessment", password="secret")

def test_show_version_preserves_raw_byte_for_byte():
    raw=b"show version\r\nCisco IOS XE Software  \r\n\x1b[0mSW1#"; repo=InMemoryRawRepository(); executor=CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=repo)
    result=executor.execute(run_id="run-001", device=device(), catalog=MVP_COMMAND_CATALOG, command=MVP_COMMAND_CATALOG.get(CommandId.SHOW_VERSION), session=FakeSession(raw))
    assert result.execution.status is CommandExecutionStatus.SUCCESS; assert repo.saved == raw; assert result.raw_output is not None

def test_timeout_persists_partial_raw():
    partial=b"show version\r\nCisco IOS XE Software"; repo=InMemoryRawRepository(); executor=CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=repo)
    result=executor.execute(run_id="run-001", device=device(), catalog=MVP_COMMAND_CATALOG, command=MVP_COMMAND_CATALOG.get(CommandId.SHOW_VERSION), session=FakeSession(CommandTimeoutError("timeout", partial_raw=partial)))
    assert result.execution.status is CommandExecutionStatus.TIMEOUT; assert repo.saved == partial

def test_unregistered_command_is_rejected_without_execution():
    repo=InMemoryRawRepository(); executor=CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=repo); unsafe=CommandSpec(id=CommandId.SHOW_VERSION, cli="reload", platforms=frozenset({Platform.IOS_XE}), purpose="unsafe"); session=FakeSession(b"never")
    result=executor.execute(run_id="run-001", device=device(), catalog=MVP_COMMAND_CATALOG, command=unsafe, session=session)
    assert result.execution.status is CommandExecutionStatus.POLICY_REJECTED; assert session.calls == []; assert repo.saved is None
