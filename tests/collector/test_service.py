from cisco_switch_assessment.catalog import MVP_COMMAND_CATALOG
from cisco_switch_assessment.collector.exceptions import AuthenticationError
from cisco_switch_assessment.collector.executor import CommandExecutor
from cisco_switch_assessment.collector.policy import ReadOnlyPolicy
from cisco_switch_assessment.collector.service import DeviceCollector
from cisco_switch_assessment.collector.session.factory import SessionFactory
from cisco_switch_assessment.models import CommandExecutionStatus, Device, Platform
from .fakes import InMemoryRawRepository

class FailingConnectTransport:
    def __init__(self): self.closed=False
    def connect(self, device, timeouts): raise AuthenticationError("bad credentials")
    def close(self): self.closed=True

def test_connection_failure_still_produces_command_execution():
    transport=FailingConnectTransport(); collector=DeviceCollector(transport_factory=lambda: transport, session_factory=SessionFactory(), executor=CommandExecutor(policy=ReadOnlyPolicy(), raw_repository=InMemoryRawRepository()))
    device=Device(id="sw-core-01", host="192.0.2.10", platform=Platform.IOS_XE, username="assessment", password="wrong")
    result=collector.collect(run_id="run-001", device=device, catalog=MVP_COMMAND_CATALOG)
    assert len(result.commands)==1; assert result.commands[0].execution.status is CommandExecutionStatus.FAILED; assert result.commands[0].execution.error_code == "AUTHENTICATION_FAILED"; assert transport.closed
