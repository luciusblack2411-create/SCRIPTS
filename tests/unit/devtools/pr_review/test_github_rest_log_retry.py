from __future__ import annotations

from collections.abc import Mapping

import pytest

from cisco_assessment.devtools.pr_review import GitHubRestError, GitHubRestReadBackend, github_rest


class FlakyWorkflowLogTransport:
    def __init__(self, *, failures: int, status_code: int = 404) -> None:
        self.failures = failures
        self.status_code = status_code
        self.text_calls = 0

    def get_json(self, path: str) -> object:
        assert path == "/repos/owner/repo/actions/runs/134/jobs?per_page=100"
        return {"jobs": [{"id": 971}]}

    def get_text(self, path: str, *, accept: str) -> str:
        assert path == "/repos/owner/repo/actions/jobs/971/logs"
        assert accept == "application/vnd.github+json"
        self.text_calls += 1
        if self.text_calls <= self.failures:
            raise GitHubRestError("workflow log blob unavailable", status_code=self.status_code)
        return (
            "git fetch origin "
            "+1111111111111111111111111111111111111111:refs/remotes/pull/37/merge\n"
            "git checkout --force refs/remotes/pull/37/merge\n"
            "HEAD is now at 1111111 Merge "
            "2222222222222222222222222222222222222222 into "
            "3333333333333333333333333333333333333333\n"
        )


def test_workflow_log_transient_404_is_retried_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FlakyWorkflowLogTransport(failures=1)
    delays: list[float] = []
    monkeypatch.setattr(github_rest, "sleep", delays.append)

    provenance: Mapping[str, object] | None = GitHubRestReadBackend(
        transport
    ).get_workflow_checkout_provenance("owner/repo", 134)

    assert provenance == {
        "ref": "refs/remotes/pull/37/merge",
        "sha": "1111111111111111111111111111111111111111",
        "base_sha": "3333333333333333333333333333333333333333",
        "head_sha": "2222222222222222222222222222222222222222",
    }
    assert transport.text_calls == 2
    assert delays == [2.0]


def test_workflow_log_persistent_404_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FlakyWorkflowLogTransport(failures=99)
    delays: list[float] = []
    monkeypatch.setattr(github_rest, "sleep", delays.append)

    with pytest.raises(GitHubRestError, match="workflow log blob unavailable"):
        GitHubRestReadBackend(transport).get_workflow_checkout_provenance(
            "owner/repo", 134
        )

    assert transport.text_calls == 5
    assert delays == [2.0, 2.0, 2.0, 2.0]


def test_workflow_log_non_404_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FlakyWorkflowLogTransport(failures=1, status_code=403)
    delays: list[float] = []
    monkeypatch.setattr(github_rest, "sleep", delays.append)

    with pytest.raises(GitHubRestError, match="workflow log blob unavailable"):
        GitHubRestReadBackend(transport).get_workflow_checkout_provenance(
            "owner/repo", 134
        )

    assert transport.text_calls == 1
    assert delays == []
