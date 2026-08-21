import re
from cisco_switch_assessment.catalog import CommandCatalog, CommandSpec, ExecutionClass
from cisco_switch_assessment.collector.exceptions import CommandPolicyError
from cisco_switch_assessment.models import Platform

_SAFE_QUERY_RE = re.compile(r"^show(?:\s|$)", re.IGNORECASE)
_FORBIDDEN_TOKENS = ("\n", "\r", ";", "&&", "||")

class ReadOnlyPolicy:
    def validate(self, *, catalog: CommandCatalog, command: CommandSpec, platform: Platform) -> None:
        if not catalog.contains(command): raise CommandPolicyError("command spec is not the registered catalog entry")
        if command.execution_class is not ExecutionClass.QUERY: raise CommandPolicyError("collector only executes query commands")
        if not command.supports(platform): raise CommandPolicyError(f"command {command.id} does not support {platform}")
        if any(token in command.cli for token in _FORBIDDEN_TOKENS): raise CommandPolicyError("command contains chaining or newline characters")
        if not _SAFE_QUERY_RE.match(command.cli.strip()): raise CommandPolicyError("v0.1 collector only permits show commands")
