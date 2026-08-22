"""Allowlist-first enforcement for commands executed by the collector."""

from __future__ import annotations

from dataclasses import dataclass

from cisco_assessment.catalog import CommandCatalog, CommandDefinition, CommandId, CommandVariant
from cisco_assessment.collector.exceptions import CommandPolicyError
from cisco_assessment.models import PlatformFamily

_FORBIDDEN_TOKENS = ("\n", "\r", ";", "|", "&", ">", "<", "`")


@dataclass(frozen=True, slots=True)
class AuthorizedCommand:
    """Canonical catalog definition and platform-specific CLI variant."""

    definition: CommandDefinition
    variant: CommandVariant


class ReadOnlyPolicy:
    """Resolve only canonical catalog commands that are safe to execute."""

    def authorize(
        self,
        *,
        catalog: CommandCatalog,
        command_id: CommandId,
        platform: PlatformFamily,
    ) -> AuthorizedCommand:
        definition = catalog.get(command_id)
        if not definition.read_only:
            raise CommandPolicyError(f"command {command_id} is not marked read-only")

        variant = catalog.resolve(command_id, platform)
        if variant is None:
            raise CommandPolicyError(
                f"command {command_id} has no authorized variant for platform {platform}"
            )

        cli = variant.cli_command
        if any(token in cli for token in _FORBIDDEN_TOKENS):
            raise CommandPolicyError(f"command {command_id} contains a forbidden CLI token")
        if not cli.lower().startswith("show "):
            raise CommandPolicyError(f"command {command_id} is not a show query")

        return AuthorizedCommand(definition=definition, variant=variant)
