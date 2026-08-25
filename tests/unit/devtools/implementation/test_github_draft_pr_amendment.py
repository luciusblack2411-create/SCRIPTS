from __future__ import annotations

import inspect
from collections.abc import Mapping

from cisco_assessment.devtools.implementation.github_draft_pr_amendment import (
    UrllibGitHubDraftPrAmendmentTransport,
)


def test_patch_ref_public_surface_has_no_force_argument() -> None:
    signature = inspect.signature(UrllibGitHubDraftPrAmendmentTransport.patch_ref)
    assert "force" not in signature.parameters


def test_patch_ref_emits_force_false(monkeypatch: object) -> None:
    captured: list[tuple[str, str, Mapping[str, object]]] = []
    transport = UrllibGitHubDraftPrAmendmentTransport(token="secret")

    def request(method: str, path: str, payload: Mapping[str, object]) -> object:
        captured.append((method, path, payload))
        return {
            "ref": "refs/heads/agent/implementation/fix",
            "object": {"sha": "new"},
        }

    monkeypatch.setattr(transport, "_json_request", request)
    transport.patch_ref(
        "/repos/owner/repo/git/refs/heads/agent%2Fimplementation%2Ffix", "new"
    )
    assert captured == [
        (
            "PATCH",
            "/repos/owner/repo/git/refs/heads/agent%2Fimplementation%2Ffix",
            {"sha": "new", "force": False},
        )
    ]
