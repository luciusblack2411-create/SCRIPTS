"""Atomic filesystem persistence for byte-exact RAW command evidence."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from uuid import UUID

from cisco_assessment.collector.exceptions import RawPersistenceError
from cisco_assessment.models import RawCommandOutput
from cisco_assessment.raw.repository import PersistedRawOutput


def _safe_component(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    if not cleaned or cleaned in {".", ".."}:
        raise RawPersistenceError("invalid RAW path component")
    return cleaned


def _decode_reversibly(content: bytes) -> tuple[str, str]:
    """Map bytes to the existing text RAW model without losing round-trip fidelity."""

    try:
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("latin-1"), "latin-1"


class FilesystemRawRepository:
    """Persist exact bytes and return the existing RawCommandOutput model."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def save(
        self,
        *,
        assessment_run_id: UUID,
        device_id: UUID,
        command_execution_id: UUID,
        command_key: str,
        sequence: int,
        content: bytes,
        is_truncated: bool = False,
    ) -> PersistedRawOutput:
        text, encoding = _decode_reversibly(content)
        output = RawCommandOutput.from_text(
            command_execution_id=command_execution_id,
            content=text,
            encoding=encoding,
            is_truncated=is_truncated,
        )

        expected_hash = hashlib.sha256(content).hexdigest()
        if output.sha256 != expected_hash or output.byte_length != len(content):
            raise RawPersistenceError("RAW model integrity metadata does not match captured bytes")

        directory = (
            self._root
            / _safe_component(str(assessment_run_id))
            / "devices"
            / _safe_component(str(device_id))
            / "raw"
        )
        filename = (
            f"{sequence:03d}_{_safe_component(command_key)}_{command_execution_id}.raw"
        )
        final_path = directory / filename

        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary_name = tempfile.mkstemp(prefix=f".{filename}.", dir=directory)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary_name, 0o600)
                os.replace(temporary_name, final_path)
            except Exception:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
        except OSError as exc:
            raise RawPersistenceError(f"failed to persist RAW output: {exc}") from exc

        return PersistedRawOutput(output=output, path=final_path)
