from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import pytest

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationContext,
    ImplementationContextFile,
)
from cisco_assessment.devtools.implementation.source_inspection import (
    ImplementationSourceInspectionError,
    inspect_implementation_sources,
)


class FakeSourceBackend:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.blob_calls: list[tuple[str, str]] = []

    def get_branch(
        self,
        repository: str,
        branch: str,
    ) -> Mapping[str, object] | None:
        raise AssertionError(f"unexpected branch request: {repository} {branch}")

    def list_tree(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        raise AssertionError(f"unexpected tree request: {repository} {commit_sha}")

    def get_blob(self, repository: str, blob_sha: str) -> bytes:
        self.blob_calls.append((repository, blob_sha))
        return self.blobs[blob_sha]


def _context() -> ImplementationContext:
    parser_bytes = b"def parse():\r\n    return 1\r\n"
    test_bytes = b"def test_parse():\n    assert True\n"
    raw_bytes = b"switch#show example\r\n"
    return ImplementationContext(
        repository="owner/repo",
        base_branch="main",
        base_sha="a" * 40,
        files=(
            ImplementationContextFile(
                path="src/cisco_assessment/parsers/example.py",
                component=ComponentId.PARSER,
                blob_sha="b" * 40,
                size=len(parser_bytes),
            ),
            ImplementationContextFile(
                path="tests/fixtures/example.raw",
                component=ComponentId.TESTING_FIXTURES,
                blob_sha="d" * 40,
                size=len(raw_bytes),
            ),
            ImplementationContextFile(
                path="tests/unit/parsers/test_example.py",
                component=ComponentId.TESTING_FIXTURES,
                blob_sha="c" * 40,
                size=len(test_bytes),
            ),
        ),
        observed_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
    )


def test_source_inspection_is_explicit_sorted_and_byte_traceable() -> None:
    parser_bytes = b"def parse():\r\n    return 1\r\n"
    test_bytes = b"def test_parse():\n    assert True\n"
    backend = FakeSourceBackend(
        {
            "b" * 40: parser_bytes,
            "c" * 40: test_bytes,
        }
    )

    inspection = inspect_implementation_sources(
        _context(),
        backend,
        (
            "tests/unit/parsers/test_example.py",
            "src/cisco_assessment/parsers/example.py",
        ),
    )

    assert tuple(item.path for item in inspection.files) == (
        "src/cisco_assessment/parsers/example.py",
        "tests/unit/parsers/test_example.py",
    )
    assert inspection.files[0].content == parser_bytes.decode("utf-8")
    assert inspection.files[0].sha256 == hashlib.sha256(parser_bytes).hexdigest()
    assert inspection.files[0].byte_size == len(parser_bytes)
    assert inspection.total_bytes == len(parser_bytes) + len(test_bytes)
    assert backend.blob_calls == [
        ("owner/repo", "b" * 40),
        ("owner/repo", "c" * 40),
    ]


def test_source_inspection_rejects_path_outside_authorized_context() -> None:
    backend = FakeSourceBackend({})

    with pytest.raises(ImplementationSourceInspectionError, match="not present"):
        inspect_implementation_sources(_context(), backend, ("src/other.py",))

    assert backend.blob_calls == []


def test_source_inspection_does_not_treat_raw_fixture_as_source_text() -> None:
    backend = FakeSourceBackend({"d" * 40: b"switch#show example\r\n"})

    with pytest.raises(ImplementationSourceInspectionError, match="approved source-text"):
        inspect_implementation_sources(
            _context(),
            backend,
            ("tests/fixtures/example.raw",),
        )

    assert backend.blob_calls == []


def test_source_inspection_rejects_duplicate_selection_and_size_mismatch() -> None:
    parser_path = "src/cisco_assessment/parsers/example.py"
    backend = FakeSourceBackend({"b" * 40: b"short"})

    with pytest.raises(ImplementationSourceInspectionError, match="unique"):
        inspect_implementation_sources(_context(), backend, (parser_path, parser_path))

    with pytest.raises(ImplementationSourceInspectionError, match="byte size"):
        inspect_implementation_sources(_context(), backend, (parser_path,))


def test_source_inspection_enforces_per_file_and_total_limits() -> None:
    parser_bytes = b"def parse():\r\n    return 1\r\n"
    test_bytes = b"def test_parse():\n    assert True\n"
    backend = FakeSourceBackend(
        {
            "b" * 40: parser_bytes,
            "c" * 40: test_bytes,
        }
    )

    with pytest.raises(ImplementationSourceInspectionError, match="per-file"):
        inspect_implementation_sources(
            _context(),
            backend,
            ("src/cisco_assessment/parsers/example.py",),
            max_file_bytes=1,
        )

    with pytest.raises(ImplementationSourceInspectionError, match="total"):
        inspect_implementation_sources(
            _context(),
            backend,
            (
                "src/cisco_assessment/parsers/example.py",
                "tests/unit/parsers/test_example.py",
            ),
            max_total_bytes=len(parser_bytes),
        )
