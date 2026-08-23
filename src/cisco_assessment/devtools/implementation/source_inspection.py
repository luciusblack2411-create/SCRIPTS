"""Controlled source-content inspection for Implementation Agent v0.1."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..pr_review import ComponentId
from .context import ImplementationContext, ImplementationReadBackend
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel

DEFAULT_MAX_SOURCE_FILE_BYTES = 256 * 1024
DEFAULT_MAX_SOURCE_TOTAL_BYTES = 1024 * 1024
SUPPORTED_SOURCE_SUFFIXES = frozenset(
    {
        ".ini",
        ".json",
        ".md",
        ".py",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)


class ImplementationSourceInspectionError(RuntimeError):
    """Raised when controlled source inspection cannot be completed safely."""


class ImplementationSourceReadBackend(ImplementationReadBackend, Protocol):
    """Read-only backend that can also return bytes for an exact Git blob SHA."""

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        """Return byte-exact Git blob content for the requested SHA."""
        ...


class ImplementationSourceFile(FrozenImplementationModel):
    """One inspected source file pinned to its exact Git blob identity."""

    path: str = Field(min_length=1)
    component: ComponentId
    blob_sha: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoding: Literal["utf-8"] = "utf-8"
    content: str


class ImplementationSourceInspection(FrozenImplementationModel):
    """Canonical source snapshot selected from an authorized implementation context."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    files: tuple[ImplementationSourceFile, ...] = Field(min_length=1)
    total_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_canonical_files(self) -> ImplementationSourceInspection:
        """Require unique lexical paths and an exact aggregate byte count."""
        paths = tuple(item.path for item in self.files)
        if len(set(paths)) != len(paths):
            raise ValueError("source inspection file paths must be unique")
        if paths != tuple(sorted(paths)):
            raise ValueError("source inspection files must be sorted by repository path")
        if self.total_bytes != sum(item.byte_size for item in self.files):
            raise ValueError("source inspection total_bytes must equal inspected file sizes")
        return self


def inspect_implementation_sources(
    context: ImplementationContext,
    backend: ImplementationSourceReadBackend,
    selected_paths: Sequence[str],
    *,
    max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_SOURCE_TOTAL_BYTES,
) -> ImplementationSourceInspection:
    """Read an explicit authorized text-file subset without path inference or mutation."""
    if max_file_bytes <= 0 or max_total_bytes <= 0:
        raise ImplementationSourceInspectionError("source inspection byte limits must be positive")

    requested = tuple(selected_paths)
    if not requested:
        raise ImplementationSourceInspectionError("source inspection requires at least one path")
    if len(set(requested)) != len(requested):
        raise ImplementationSourceInspectionError("source inspection paths must be unique")

    context_by_path = {item.path: item for item in context.files}
    inspected: list[ImplementationSourceFile] = []
    total_bytes = 0

    for path in sorted(requested):
        context_file = context_by_path.get(path)
        if context_file is None:
            raise ImplementationSourceInspectionError(
                f"path {path!r} is not present in the authorized implementation context"
            )
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in SUPPORTED_SOURCE_SUFFIXES:
            raise ImplementationSourceInspectionError(
                f"path {path!r} is not an approved source-text file type"
            )
        if context_file.size is not None and context_file.size > max_file_bytes:
            raise ImplementationSourceInspectionError(
                f"path {path!r} exceeds the per-file source inspection limit"
            )

        data = backend.get_blob(context.repository, context_file.blob_sha)
        byte_size = len(data)
        if byte_size > max_file_bytes:
            raise ImplementationSourceInspectionError(
                f"path {path!r} exceeds the per-file source inspection limit"
            )
        if context_file.size is not None and byte_size != context_file.size:
            raise ImplementationSourceInspectionError(
                f"path {path!r} byte size does not match repository tree evidence"
            )
        total_bytes += byte_size
        if total_bytes > max_total_bytes:
            raise ImplementationSourceInspectionError(
                "selected files exceed the total source inspection byte limit"
            )
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImplementationSourceInspectionError(
                f"path {path!r} is not strict UTF-8 text"
            ) from exc

        inspected.append(
            ImplementationSourceFile(
                path=path,
                component=context_file.component,
                blob_sha=context_file.blob_sha,
                byte_size=byte_size,
                sha256=hashlib.sha256(data).hexdigest(),
                content=content,
            )
        )

    return ImplementationSourceInspection(
        repository=context.repository,
        base_sha=context.base_sha,
        files=tuple(inspected),
        total_bytes=total_bytes,
    )
