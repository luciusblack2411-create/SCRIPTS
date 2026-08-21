import pytest
from cisco_switch_assessment.catalog import CommandCatalog, CommandId, CommandSpec, ExecutionClass, MVP_COMMAND_CATALOG
from cisco_switch_assessment.collector.exceptions import CommandPolicyError
from cisco_switch_assessment.collector.policy import ReadOnlyPolicy
from cisco_switch_assessment.models import Platform

def test_registered_show_version_is_allowed():
    ReadOnlyPolicy().validate(catalog=MVP_COMMAND_CATALOG, command=MVP_COMMAND_CATALOG.get(CommandId.SHOW_VERSION), platform=Platform.IOS)

@pytest.mark.parametrize("cli", ["show version\nreload", "show version; reload", "configure terminal", "reload"])
def test_non_read_only_or_chained_command_is_rejected(cli):
    spec=CommandSpec(id=CommandId.SHOW_VERSION, cli=cli, platforms=frozenset({Platform.IOS}), purpose="unsafe"); catalog=CommandCatalog((spec,))
    with pytest.raises(CommandPolicyError): ReadOnlyPolicy().validate(catalog=catalog, command=spec, platform=Platform.IOS)

def test_session_control_rejected_by_executor_policy():
    spec=CommandSpec(id=CommandId.SHOW_VERSION, cli="show version", platforms=frozenset({Platform.IOS}), purpose="test", execution_class=ExecutionClass.SESSION_CONTROL); catalog=CommandCatalog((spec,))
    with pytest.raises(CommandPolicyError): ReadOnlyPolicy().validate(catalog=catalog, command=spec, platform=Platform.IOS)
