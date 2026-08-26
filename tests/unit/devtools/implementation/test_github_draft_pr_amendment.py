from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Self

import pytest
from typer.testing import CliRunner

from cisco_assessment.devtools.implementation import draft_pr_amendment_control_plane_cli as cli
from cisco_assessment.devtools.implementation.draft_pr_amendment import (
    ImplementationDraftPrAmendmentError,
)
from cisco_assessment.devtools.implementation.github_draft_pr_amendment import (
    GitHubImplementationDraftPrAmendmentBackend,
)


class Transport:
    def __init__(self) -> None:
        self.gets: list[str] = []
        self.patches: list[tuple[str, str]] = []
        self.dispatches: list[tuple[str, Mapping[str, object]]] = []
        self.responses: dict[str, object] = {}

    def get_json(self, path: str) -> object:
        self.gets.append(path)
        return self.responses[path]

    def get_text(self, path: str, *, accept: str) -> str:
        del path, accept
        raise AssertionError("text reads are not used")

    def post_json(self, path: str, payload: Mapping[str, object]) -> object:
        del payload
        return self.responses[path]

    def patch_ref_fast_forward(self, path: str, new_sha: str) -> object:
        self.patches.append((path, new_sha))
        return {"ref": "refs/heads/feat/m14-switchport-observation-data-model", "object": {"sha": new_sha}}

    def post_no_content(self, path: str, payload: Mapping[str, object]) -> None:
        self.dispatches.append((path, payload))


def test_backend_checks_old_sha_then_uses_non_force_patch_contract() -> None:
    transport = Transport()
    branch = "feat/m14-switchport-observation-data-model"
    transport.responses["/repos/owner/repo/branches/feat%2Fm14-switchport-observation-data-model"] = {"commit": {"sha": "old"}}
    backend = GitHubImplementationDraftPrAmendmentBackend(token="dedicated", transport=transport)
    backend.update_existing_ref_fast_forward("owner/repo", branch, "old", "new")
    assert transport.patches == [("/repos/owner/repo/git/refs/heads/feat%2Fm14-switchport-observation-data-model", "new")]


def test_backend_rejects_concurrent_ref_change_before_patch() -> None:
    transport = Transport()
    branch = "feat/m14-switchport-observation-data-model"
    transport.responses["/repos/owner/repo/branches/feat%2Fm14-switchport-observation-data-model"] = {"commit": {"sha": "racer"}}
    backend = GitHubImplementationDraftPrAmendmentBackend(token="dedicated", transport=transport)
    with pytest.raises(ImplementationDraftPrAmendmentError, match="moved before PATCH"):
        backend.update_existing_ref_fast_forward("owner/repo", branch, "old", "new")
    assert transport.patches == []


def test_dispatch_uses_no_content_transport_exactly_once() -> None:
    transport = Transport()
    backend = GitHubImplementationDraftPrAmendmentBackend(token="dedicated", transport=transport)
    backend.dispatch_amendment_ci("owner/repo", "ci.yml", "feat/m14-switchport-observation-data-model")
    assert transport.dispatches == [("/repos/owner/repo/actions/workflows/ci.yml/dispatches", {"ref": "feat/m14-switchport-observation-data-model"})]


def test_jobs_are_paginated_completely() -> None:
    transport = Transport()
    first = "/repos/owner/repo/actions/runs/7/jobs?per_page=100&page=1"
    second = "/repos/owner/repo/actions/runs/7/jobs?per_page=100&page=2"
    transport.responses[first] = {"jobs": [{"id": index} for index in range(100)]}
    transport.responses[second] = {"jobs": [{"id": 101}]}
    backend = GitHubImplementationDraftPrAmendmentBackend(token="dedicated", transport=transport)
    assert len(backend.list_amendment_ci_jobs("owner/repo", 7)) == 101
    assert transport.gets == [first, second]


def test_cli_success_and_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    operation_file = tmp_path / "operation.json"
    operation_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "load_amendment_operation", lambda path: object())

    class Result:
        def model_dump_json(self, *, indent: int) -> str:
            assert indent == 2
            return '{"ready_for_review":false}'

    monkeypatch.setattr(cli, "execute_amendment_control_plane", lambda operation: Result())
    runner = CliRunner()
    success = runner.invoke(cli.app, ["run", str(operation_file)])
    assert success.exit_code == 0
    assert '"ready_for_review":false' in success.stdout

    def fail(operation: object) -> object:
        del operation
        raise ImplementationDraftPrAmendmentError("blocked")

    monkeypatch.setattr(cli, "execute_amendment_control_plane", fail)
    failure = runner.invoke(cli.app, ["run", str(operation_file)])
    assert failure.exit_code == 4
    assert "ERROR: blocked" in failure.stderr


class _RecordedHttpResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self._status = status
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body


def test_product_transport_accepts_exact_204_empty_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from urllib.request import Request

    from cisco_assessment.devtools.implementation import (
        github_draft_pr_amendment as github_amendment,
    )
    from cisco_assessment.devtools.implementation.github_draft_pr_amendment import (
        UrllibGitHubDraftPrAmendmentTransport,
    )

    requests: list[Request] = []

    def fake_urlopen(
        request: Request,
        *,
        timeout: float,
    ) -> _RecordedHttpResponse:
        assert timeout == 7.0
        requests.append(request)
        return _RecordedHttpResponse(204, b"")

    monkeypatch.setattr(
        github_amendment,
        "urlopen",
        fake_urlopen,
    )

    branch = "feat/m14-switchport-observation-data-model"
    transport = UrllibGitHubDraftPrAmendmentTransport(
        token="dedicated",
        api_base_url="https://api.example.test",
        timeout_seconds=7.0,
    )

    transport.post_no_content(
        "/repos/owner/repo/actions/workflows/ci.yml/dispatches",
        {"ref": branch},
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "POST"
    assert (
        request.full_url
        == "https://api.example.test/repos/owner/repo/"
        "actions/workflows/ci.yml/dispatches"
    )
    assert request.data is not None
    assert json.loads(request.data.decode("utf-8")) == {"ref": branch}


def test_product_transport_patch_payload_is_non_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from urllib.request import Request

    from cisco_assessment.devtools.implementation import (
        github_draft_pr_amendment as github_amendment,
    )
    from cisco_assessment.devtools.implementation.github_draft_pr_amendment import (
        UrllibGitHubDraftPrAmendmentTransport,
    )

    requests: list[Request] = []

    def fake_urlopen(
        request: Request,
        *,
        timeout: float,
    ) -> _RecordedHttpResponse:
        assert timeout == 11.0
        requests.append(request)
        body = json.dumps(
            {
                "ref": (
                    "refs/heads/"
                    "feat/m14-switchport-observation-data-model"
                ),
                "object": {"sha": "new-head"},
            }
        ).encode("utf-8")
        return _RecordedHttpResponse(200, body)

    monkeypatch.setattr(
        github_amendment,
        "urlopen",
        fake_urlopen,
    )

    transport = UrllibGitHubDraftPrAmendmentTransport(
        token="dedicated",
        api_base_url="https://api.example.test",
        timeout_seconds=11.0,
    )

    result = transport.patch_ref_fast_forward(
        "/repos/owner/repo/git/refs/heads/"
        "feat%2Fm14-switchport-observation-data-model",
        "new-head",
    )

    assert isinstance(result, dict)
    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "PATCH"
    assert request.data is not None
    assert json.loads(request.data.decode("utf-8")) == {
        "sha": "new-head",
        "force": False,
    }

