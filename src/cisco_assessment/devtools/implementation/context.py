"""Read-only repository context acquisition for Implementation Agent v0.1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from ..pr_review import ComponentId, classify_changed_path
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel, ImplementationRequest


class ImplementationContextError(RuntimeError):
    """Raised when implementation context cannot be observed deterministically."""


class ImplementationReadBackend(Protocol):
    """Read-only repository evidence required to build implementation context."""

    def get_branch(
        self, repository: str, branch: str
    ) -> Mapping[str, object] | None:
        """Return branch metadata, or None when the branch cannot be observed."""
        ...

    def list_tree(
        self, repository: str, commit_sha: str
    ) -> Sequence[Mapping[str, object]]:
        """Return repository tree entries for an exact commit SHA."""
        ...


class ImplementationContextFile(FrozenImplementationModel):
    """One repository file observed at the implementation base commit."""

    path: str = Field(min_length=1)
    component: ComponentId
    blob_sha: str = Field(min_length=1)
    size: int | None = Field(default=None, ge=0)


class ImplementationContext(FrozenImplementationModel):
    """Canonical read-only repository context for one implementation request."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    files: tuple[ImplementationContextFile, ...]
    observed_components: tuple[ComponentId, ...]

    @model_validator(mode="after")
    def validate_canonical_files(self) -> ImplementationContext:
        """Require unique repository paths in canonical lexical order."""
        paths = tuple(item.path for item in self.files)
        if len(set(paths)) != len(paths):
            raise ValueError("implementation context file paths must be unique")
        if paths != tuple(sorted(paths)):
            raise ValueError("implementation context files must be sorted by repository path")
        return self


def load_implementation_context(
    request: ImplementationRequest,
    backend: ImplementationReadBackend,
) -> ImplementationContext:
    """Observe the exact base HEAD and authorized repository paths without mutation."""
    branch = backend.get_branch(request.repository, request.expected_base_branch)
    if branch is None:
        raise ImplementationContextError(
            f"cannot observe base branch {request.expected_base_branch!r}"
        )
    base_sha = _branch_sha(branch)
    entries = backend.list_tree(request.repository, base_sha)
    allowed = set(request.authorized_components)
    prohibited = set(request.prohibited_components)

    files: list[ImplementationContextFile] = []
    for entry in entries:
        if entry.get("type") != "blob":
            continue
        path = _required_string(entry, "path", context="tree entry")
        blob_sha = _required_string(entry, "sha", context=f"tree entry {path!r}")
        component = classify_changed_path(path)
        if component not in allowed or component in prohibited:
            continue
        size_value = entry.get("size")
        if size_value is not None and (not isinstance(size_value, int) or size_value < 0):
            raise ImplementationContextError(
                f"tree entry {path!r} has invalid size metadata"
            )
        files.append(
            ImplementationContextFile(
                path=path,
                component=component,
                blob_sha=blob_sha,
                size=size_value,
            )
        )

    ordered_files = tuple(sorted(files, key=lambda item: item.path))
    observed = {item.component for item in ordered_files}
    observed_components = tuple(
        component for component in ComponentId if component in observed
    )
    return ImplementationContext(
        repository=request.repository,
        base_branch=request.expected_base_branch,
        base_sha=base_sha,
        files=ordered_files,
        observed_components=observed_components,
    )


def _branch_sha(branch: Mapping[str, object]) -> str:
    commit_value = branch.get("commit")
    if not isinstance(commit_value, Mapping):
        raise ImplementationContextError("base branch metadata has no commit object")
    commit = cast(Mapping[str, object], commit_value)
    return _required_string(commit, "sha", context="base branch commit")


def _required_string(
    value: Mapping[str, object], key: str, *, context: str
) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ImplementationContextError(f"{context} has no valid {key}")
    return raw
