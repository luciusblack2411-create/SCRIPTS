from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation import (
    ImplementationFileChangeKind,
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
)


def _change(*, ordinal: int, path: str) -> ImplementationMutationChangeResult:
    return ImplementationMutationChangeResult(
        ordinal=ordinal,
        change_id=f"impl-change:{ordinal:04d}",
        kind=ImplementationFileChangeKind.CREATE,
        path=path,
        published_blob_sha=f"blob-{ordinal}",
        proposed_content_sha256="0" * 64,
    )


def test_change_result_requires_stable_change_id() -> None:
    with pytest.raises(ValidationError, match="change_id"):
        ImplementationMutationChangeResult(
            ordinal=1,
            change_id="wrong",
            kind=ImplementationFileChangeKind.CREATE,
            path="tests/unit/example.py",
            published_blob_sha="blob",
            proposed_content_sha256="0" * 64,
        )


def test_mutation_result_requires_lexical_unique_paths() -> None:
    with pytest.raises(ValidationError, match="lexical order"):
        ImplementationMutationResult(
            repository="owner/repo",
            base_branch="main",
            base_sha="base",
            workspace_sha256="0" * 64,
            work_branch="agent/implementation/example",
            commit_sha="commit",
            tree_sha="tree",
            changes=(
                _change(ordinal=1, path="tests/z.py"),
                _change(ordinal=2, path="tests/a.py"),
            ),
            base_head_after_publish="base",
            base_fresh_after_publish=True,
        )


def test_mutation_result_requires_freshness_flag_to_match_observed_head() -> None:
    with pytest.raises(ValidationError, match="base_fresh_after_publish"):
        ImplementationMutationResult(
            repository="owner/repo",
            base_branch="main",
            base_sha="base",
            workspace_sha256="0" * 64,
            work_branch="agent/implementation/example",
            commit_sha="commit",
            tree_sha="tree",
            changes=(_change(ordinal=1, path="tests/a.py"),),
            base_head_after_publish="advanced",
            base_fresh_after_publish=True,
        )
