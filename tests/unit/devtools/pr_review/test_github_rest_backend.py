from __future__ import annotations

from collections.abc import Mapping
from email.message import Message
from typing import Self
from urllib.request import HTTPRedirectHandler, Request

import pytest

from cisco_assessment.devtools.pr_review import (
    GitHubRestError,
    GitHubRestReadBackend,
    UrllibGitHubTransport,
    github_rest,
)


class FakeTransport:
    def __init__(self) -> None:
        self.json_responses: dict[str, list[object]] = {}
        self.text_responses: dict[tuple[str, str], str] = {}
        self.json_calls: list[str] = []
        self.text_calls: list[tuple[str, str]] = []

    def add_json(self, path: str, *responses: object) -> None:
        self.json_responses[path] = list(responses)

    def add_text(self, path: str, *, accept: str, response: str) -> None:
        self.text_responses[(path, accept)] = response

    def get_json(self, path: str) -> object:
        self.json_calls.append(path)
        responses = self.json_responses[path]
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]

    def get_text(self, path: str, *, accept: str) -> str:
        self.text_calls.append((path, accept))
        return self.text_responses[(path, accept)]


def _pr_payload(*, mergeable: bool | None) -> Mapping[str, object]:
    return {
        "number": 37,
        "title": "Synthetic PR",
        "body": None,
        "state": "open",
        "draft": True,
        "mergeable": mergeable,
        "base": {"ref": "main", "sha": "base-sha"},
        "head": {"ref": "feature", "sha": "head-sha"},
    }


def test_single_false_mergeability_is_rechecked_before_becoming_evidence() -> None:
    transport = FakeTransport()
    path = "/repos/owner/repo/pulls/37"
    transport.add_json(path, _pr_payload(mergeable=False), _pr_payload(mergeable=True))

    payload = GitHubRestReadBackend(transport).get_pull_request("owner/repo", 37)

    assert payload["mergeable"] is True
    assert transport.json_calls == [path, path]


def test_two_consistent_false_mergeability_reads_remain_false() -> None:
    transport = FakeTransport()
    path = "/repos/owner/repo/pulls/37"
    transport.add_json(path, _pr_payload(mergeable=False), _pr_payload(mergeable=False))

    payload = GitHubRestReadBackend(transport).get_pull_request("owner/repo", 37)

    assert payload["mergeable"] is False
    assert transport.json_calls == [path, path]


def test_non_false_mergeability_is_not_requeried() -> None:
    transport = FakeTransport()
    path = "/repos/owner/repo/pulls/37"
    transport.add_json(path, _pr_payload(mergeable=None))

    payload = GitHubRestReadBackend(transport).get_pull_request("owner/repo", 37)

    assert payload["mergeable"] is None
    assert transport.json_calls == [path]


def test_backend_paginates_pull_request_files_in_api_order() -> None:
    transport = FakeTransport()
    page_one_path = "/repos/owner/repo/pulls/37/files?per_page=100&page=1"
    page_two_path = "/repos/owner/repo/pulls/37/files?per_page=100&page=2"
    first_page = [
        {
            "filename": f"file-{index}.py",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "changes": 1,
        }
        for index in range(100)
    ]
    second_page = [
        {
            "filename": "file-100.py",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "changes": 1,
        }
    ]
    transport.add_json(page_one_path, first_page)
    transport.add_json(page_two_path, second_page)

    files = GitHubRestReadBackend(transport).list_pull_request_files("owner/repo", 37)

    assert len(files) == 101
    assert files[0]["filename"] == "file-0.py"
    assert files[-1]["filename"] == "file-100.py"
    assert transport.json_calls == [page_one_path, page_two_path]


def test_workflow_checkout_provenance_prefers_exact_merge_log_over_event_snapshot() -> None:
    transport = FakeTransport()
    head_sha = "94c9bc459cd9123d5a066229b7fdab688c04c54f"
    historical_base = "58d02cfc6e169386834252b4855f04057bb8ba5b"
    current_base = "0f1a9c1bc25272c82fe5264981a2afc82abca7f6"
    merge_sha = "770e92162f43cd63dc4f20be2531b7c36080b7a6"
    runs_path = (
        "/repos/luciusblack2411-create/SCRIPTS/actions/runs"
        f"?event=pull_request&head_sha={head_sha}&per_page=100&page=1"
    )
    jobs_path = "/repos/luciusblack2411-create/SCRIPTS/actions/runs/33014164215/jobs?per_page=100"
    logs_path = "/repos/luciusblack2411-create/SCRIPTS/actions/jobs/98327922176/logs"
    transport.add_json(
        runs_path,
        {
            "workflow_runs": [
                {
                    "id": 33014164215,
                    "name": "CI",
                    "head_sha": head_sha,
                    "status": "completed",
                    "conclusion": "success",
                    "event": "pull_request",
                    "pull_requests": [
                        {
                            "number": 93,
                            "base": {"sha": historical_base},
                            "head": {"sha": head_sha},
                        }
                    ],
                }
            ]
        },
    )
    transport.add_json(jobs_path, {"jobs": [{"id": 98327922176}]})
    transport.add_text(
        logs_path,
        accept="application/vnd.github+json",
        response=(
            "git -c protocol.version=2 fetch --no-tags origin "
            f"+{merge_sha}:refs/remotes/pull/93/merge\n"
            "git checkout --progress --force refs/remotes/pull/93/merge\n"
            f"HEAD is now at 770e921 Merge {head_sha} into {current_base}\n"
        ),
    )

    backend = GitHubRestReadBackend(transport)
    runs = backend.list_commit_workflow_runs(
        "luciusblack2411-create/SCRIPTS", head_sha
    )
    provenance = backend.get_workflow_checkout_provenance(
        "luciusblack2411-create/SCRIPTS", 33014164215
    )

    assert len(runs) == 1
    assert provenance == {
        "ref": "refs/remotes/pull/93/merge",
        "sha": merge_sha,
        "base_sha": current_base,
        "head_sha": head_sha,
    }
    assert transport.text_calls == [(logs_path, "application/vnd.github+json")]


def test_workflow_checkout_provenance_does_not_infer_merge_parents_from_event_metadata() -> None:
    transport = FakeTransport()
    runs_path = (
        "/repos/owner/repo/actions/runs"
        "?event=pull_request&head_sha=head-sha&per_page=100&page=1"
    )
    jobs_path = "/repos/owner/repo/actions/runs/134/jobs?per_page=100"
    logs_path = "/repos/owner/repo/actions/jobs/971/logs"
    transport.add_json(
        runs_path,
        {
            "workflow_runs": [
                {
                    "id": 134,
                    "name": "CI",
                    "head_sha": "head-sha",
                    "status": "completed",
                    "conclusion": "success",
                    "event": "pull_request",
                    "pull_requests": [
                        {
                            "number": 37,
                            "base": {"sha": "base-sha"},
                            "head": {"sha": "head-sha"},
                        }
                    ],
                }
            ]
        },
    )
    transport.add_json(jobs_path, {"jobs": [{"id": 971}]})
    transport.add_text(
        logs_path,
        accept="application/vnd.github+json",
        response=(
            "git -c protocol.version=2 fetch --no-tags origin "
            "+1111111111111111111111111111111111111111:refs/remotes/pull/37/merge\n"
            "git checkout --progress --force refs/remotes/pull/37/merge\n"
        ),
    )

    backend = GitHubRestReadBackend(transport)
    runs = backend.list_commit_workflow_runs("owner/repo", "head-sha")
    provenance = backend.get_workflow_checkout_provenance("owner/repo", 134)

    assert len(runs) == 1
    assert provenance is None
    assert transport.text_calls == [(logs_path, "application/vnd.github+json")]


def test_checkout_provenance_can_use_exact_merge_message_without_event_metadata() -> None:
    transport = FakeTransport()
    jobs_path = "/repos/owner/repo/actions/runs/134/jobs?per_page=100"
    logs_path = "/repos/owner/repo/actions/jobs/971/logs"
    transport.add_json(jobs_path, {"jobs": [{"id": 971}]})
    transport.add_text(
        logs_path,
        accept="application/vnd.github+json",
        response=(
            "git fetch origin "
            "+1111111111111111111111111111111111111111:refs/remotes/pull/37/merge\n"
            "git checkout --force refs/remotes/pull/37/merge\n"
            "HEAD is now at 1111111 Merge "
            "2222222222222222222222222222222222222222 into "
            "3333333333333333333333333333333333333333\n"
        ),
    )

    provenance = GitHubRestReadBackend(transport).get_workflow_checkout_provenance(
        "owner/repo", 134
    )

    assert provenance == {
        "ref": "refs/remotes/pull/37/merge",
        "sha": "1111111111111111111111111111111111111111",
        "base_sha": "3333333333333333333333333333333333333333",
        "head_sha": "2222222222222222222222222222222222222222",
    }
    assert transport.text_calls == [(logs_path, "application/vnd.github+json")]


def test_checkout_provenance_rejects_non_merge_checkout() -> None:
    transport = FakeTransport()
    jobs_path = "/repos/owner/repo/actions/runs/134/jobs?per_page=100"
    logs_path = "/repos/owner/repo/actions/jobs/971/logs"
    transport.add_json(jobs_path, {"jobs": [{"id": 971}]})
    transport.add_text(
        logs_path,
        accept="application/vnd.github+json",
        response="git checkout --force refs/heads/main\n",
    )

    provenance = GitHubRestReadBackend(transport).get_workflow_checkout_provenance(
        "owner/repo", 134
    )

    assert provenance is None
    assert transport.text_calls == [(logs_path, "application/vnd.github+json")]


def test_authorization_is_not_forwarded_by_urllib_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []

    class FakeResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"log-content"

    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        requests.append(request)
        assert timeout == 20.0
        return FakeResponse()

    monkeypatch.setattr(github_rest, "urlopen", fake_urlopen)

    content = UrllibGitHubTransport(token="secret-token").get_text(
        "/repos/owner/repo/actions/jobs/971/logs",
        accept="application/vnd.github+json",
    )

    assert content == "log-content"
    assert len(requests) == 1
    initial = requests[0]
    assert initial.get_header("Authorization") == "Bearer secret-token"
    assert "Authorization" not in initial.headers
    assert initial.unredirected_hdrs["Authorization"] == "Bearer secret-token"

    redirected = HTTPRedirectHandler().redirect_request(
        initial,
        None,
        302,
        "Found",
        Message(),
        "https://results.example.invalid/signed-job-log",
    )

    assert redirected is not None
    assert redirected.get_header("Authorization") is None


def test_branch_404_is_observed_as_unavailable_without_inference() -> None:
    class MissingBranchTransport(FakeTransport):
        def get_json(self, path: str) -> object:
            self.json_calls.append(path)
            raise GitHubRestError("missing", status_code=404)

    transport = MissingBranchTransport()

    branch = GitHubRestReadBackend(transport).get_branch("owner/repo", "main")

    assert branch is None


def test_repository_name_must_use_owner_name_form() -> None:
    transport = FakeTransport()

    with pytest.raises(GitHubRestError, match="owner/name"):
        GitHubRestReadBackend(transport).get_pull_request("owner/repo/extra", 37)
