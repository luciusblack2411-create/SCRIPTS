from __future__ import annotations

import inspect
from collections.abc import Mapping

from cisco_assessment.devtools.implementation.github_draft_pr_amendment import GitHubImplementationDraftPrAmendmentBackend


class Transport:
    def __init__(self) -> None:
        self.patches: list[tuple[str, Mapping[str, object]]] = []

    def get_json(self, path: str) -> object:
        if "/branches/" in path:
            return {"commit": {"sha": "old"}}
        raise AssertionError(path)

    def get_text(self, path: str, *, accept: str) -> str:
        raise AssertionError((path, accept))

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        raise AssertionError((path, payload))

    def patch_json(self, path: str, payload: Mapping[str, object]) -> object:
        self.patches.append((path, payload))
        return {"ref": "refs/heads/agent/implementation/example", "object": {"sha": "new"}}


def test_ref_update_has_no_force_api_and_always_emits_false() -> None:
    transport = Transport()
    backend = GitHubImplementationDraftPrAmendmentBackend(transport)
    assert "force" not in inspect.signature(backend.advance_branch).parameters
    backend.advance_branch("owner/repo", "agent/implementation/example", old_sha="old", new_sha="new")
    assert transport.patches == [("/repos/owner/repo/git/refs/heads/agent%2Fimplementation%2Fexample", {"sha": "new", "force": False})]
    assert all(payload.get("force") is not True for _, payload in transport.patches)
