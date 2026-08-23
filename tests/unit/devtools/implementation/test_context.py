from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation import (
    ComponentId,
    ImplementationContext,
    ImplementationContextError,
    ImplementationContextFile,
    ImplementationReadBackend,
    ImplementationRequest,
    load_implementation_context,
)


class FakeBackend(ImplementationReadBackend):
    def __init__(
        self,
        *,
        branch: Mapping[str, object] | None,
        tree: Sequence[Mapping[str, object]],
    ) -> None:
        self.branch = branch
        self.tree = tree
        self.calls: list[tuple[str, str, str]] = []

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        self.calls.append(("branch", repository, branch))
        return self.branch

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        self.calls.append(("tree", repository, commit_sha))
        return self.tree


def _request() -> ImplementationRequest:
    return ImplementationRequest(
        repository="owner/repo",
        objective="Implement approved parser behavior.",
        authorized_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
        prohibited_components=(ComponentId.COLLECTOR,),
        invariants=("Parser remains extraction-only.",),
        acceptance_criteria=("Regression tests pass.",),
    )


def test_context_observes_exact_base_and_only_authorized_paths() -> None:
    backend = FakeBackend(
        branch={"commit": {"sha": "base-123"}},
        tree=(
            {"path": "src/cisco_assessment/parsers/z.py", "type": "blob", "sha": "z", "size": 7},
            {"path": "src/cisco_assessment/collector/session.py", "type": "blob", "sha": "c"},
            {"path": "tests/unit/parsers/test_z.py", "type": "blob", "sha": "tz", "size": 9},
            {"path": "src/cisco_assessment/parsers/a.py", "type": "blob", "sha": "a", "size": 3},
            {"path": "src/cisco_assessment/parsers", "type": "tree", "sha": "dir"},
        ),
    )

    context = load_implementation_context(_request(), backend)

    assert context.base_sha == "base-123"
    assert tuple(item.path for item in context.files) == (
        "src/cisco_assessment/parsers/a.py",
        "src/cisco_assessment/parsers/z.py",
        "tests/unit/parsers/test_z.py",
    )
    assert context.observed_components == (
        ComponentId.PARSER,
        ComponentId.TESTING_FIXTURES,
    )
    assert backend.calls == [
        ("branch", "owner/repo", "main"),
        ("tree", "owner/repo", "base-123"),
    ]


def test_context_does_not_infer_missing_branch_or_malformed_metadata() -> None:
    with pytest.raises(ImplementationContextError, match="cannot observe base branch"):
        load_implementation_context(_request(), FakeBackend(branch=None, tree=()))

    with pytest.raises(ImplementationContextError, match="no commit object"):
        load_implementation_context(_request(), FakeBackend(branch={}, tree=()))

    with pytest.raises(ImplementationContextError, match="invalid size"):
        load_implementation_context(
            _request(),
            FakeBackend(
                branch={"commit": {"sha": "base"}},
                tree=(
                    {
                        "path": "src/cisco_assessment/parsers/a.py",
                        "type": "blob",
                        "sha": "a",
                        "size": -1,
                    },
                ),
            ),
        )


def test_context_model_requires_unique_sorted_paths() -> None:
    first = ImplementationContextFile(
        path="tests/z.py",
        component=ComponentId.TESTING_FIXTURES,
        blob_sha="z",
    )
    second = ImplementationContextFile(
        path="tests/a.py",
        component=ComponentId.TESTING_FIXTURES,
        blob_sha="a",
    )

    with pytest.raises(ValidationError, match="sorted"):
        ImplementationContext(
            repository="owner/repo",
            base_branch="main",
            base_sha="base",
            files=(first, second),
            observed_components=(ComponentId.TESTING_FIXTURES,),
        )

    with pytest.raises(ValidationError, match="unique"):
        ImplementationContext(
            repository="owner/repo",
            base_branch="main",
            base_sha="base",
            files=(first, first),
            observed_components=(ComponentId.TESTING_FIXTURES,),
        )
