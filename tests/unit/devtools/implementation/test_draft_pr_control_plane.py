from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cisco_assessment.devtools.implementation.ci_validation import (
    ImplementationCiJobResult,
    ImplementationCiStatus,
    ImplementationCiValidationResult,
    ImplementationOperationalDecision,
)
from cisco_assessment.devtools.implementation.draft_pr import ImplementationDraftPrRequest
from cisco_assessment.devtools.implementation.draft_pr_control_plane import (
    DRAFT_PR_CONTROL_PLANE_TOKEN_ENV,
    ImplementationDraftPrControlPlaneError,
    ImplementationDraftPrControlPlaneFileError,
    ImplementationDraftPrControlPlaneOperation,
    execute_draft_pr_control_plane,
    load_draft_pr_control_plane_operation,
    render_draft_pr_control_plane_result_json,
    resolve_draft_pr_control_plane_token,
)
from cisco_assessment.devtools.implementation.enums import (
    ImplementationAuthorization,
    ImplementationFileChangeKind,
)
from cisco_assessment.devtools.implementation.mutation import (
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
)
from cisco_assessment.devtools.implementation.operational import ImplementationOperationalResult

BASE_SHA = "base-123"
COMMIT_SHA = "commit-456"
WORK_BRANCH = "agent/implementation/control-plane-example"
OBJECTIVE = "Create a Draft PR through a separate least-privilege control plane."
TITLE = "feat(devtools): control-plane example"
BODY = "Prepared from exact READY_FOR_DRAFT_PR evidence."
DEDICATED_TOKEN = "dedicated-pr-token"


def _operational() -> ImplementationOperationalResult:
    content = b"test = True\n"
    mutation = ImplementationMutationResult(
        repository="owner/repo",
        base_branch="main",
        base_sha=BASE_SHA,
        workspace_sha256="a" * 64,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        tree_sha="tree-789",
        changes=(
            ImplementationMutationChangeResult(
                ordinal=1,
                change_id="impl-change:0001",
                kind=ImplementationFileChangeKind.CREATE,
                path="tests/unit/devtools/implementation/test_control_plane_generated.py",
                published_blob_sha="blob-new",
                proposed_content_sha256=hashlib.sha256(content).hexdigest(),
            ),
        ),
        base_head_after_publish=BASE_SHA,
        base_fresh_after_publish=True,
    )
    ci = ImplementationCiValidationResult(
        repository="owner/repo",
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        run_id=101,
        ci_status=ImplementationCiStatus.PASSED,
        workflow_conclusion="success",
        jobs=(
            ImplementationCiJobResult(
                job_id=11,
                name="quality (3.11)",
                conclusion="success",
            ),
        ),
        base_head_after_ci=BASE_SHA,
        base_fresh_after_ci=True,
        decision=ImplementationOperationalDecision.READY_FOR_DRAFT_PR,
    )
    return ImplementationOperationalResult(
        repository="owner/repo",
        objective=OBJECTIVE,
        mutation=mutation,
        ci_validation=ci,
        decision=ImplementationOperationalDecision.READY_FOR_DRAFT_PR,
    )


def _request() -> ImplementationDraftPrRequest:
    return ImplementationDraftPrRequest(
        repository="owner/repo",
        objective=OBJECTIVE,
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        title=TITLE,
        body=BODY,
        authorization=ImplementationAuthorization.DRAFT_PR,
    )


def _operation() -> ImplementationDraftPrControlPlaneOperation:
    return ImplementationDraftPrControlPlaneOperation(
        operational_result=_operational(),
        request=_request(),
    )


def _branch(sha: str) -> Mapping[str, object]:
    return {"commit": {"sha": sha}}


def _pr_payload() -> Mapping[str, object]:
    return {
        "number": 60,
        "html_url": "https://github.com/owner/repo/pull/60",
        "title": TITLE,
        "body": BODY,
        "state": "open",
        "draft": True,
        "base": {"ref": "main", "sha": BASE_SHA},
        "head": {"ref": WORK_BRANCH, "sha": COMMIT_SHA},
    }


class FakeDraftPrBackend:
    def __init__(self) -> None:
        self.create_calls = 0

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        assert repository == "owner/repo"
        if branch == "main":
            return _branch(BASE_SHA)
        if branch == WORK_BRANCH:
            return _branch(COMMIT_SHA)
        return None

    def list_open_pull_requests(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> Sequence[Mapping[str, object]]:
        assert repository == "owner/repo"
        assert base_branch == "main"
        assert head_branch == WORK_BRANCH
        return ()

    def create_draft_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
    ) -> Mapping[str, object]:
        assert repository == "owner/repo"
        assert (title, body, base_branch, head_branch) == (TITLE, BODY, "main", WORK_BRANCH)
        self.create_calls += 1
        return _pr_payload()

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == "owner/repo"
        assert pr_number == 60
        return _pr_payload()


def test_resolver_never_falls_back_to_runner_credentials() -> None:
    with pytest.raises(ImplementationDraftPrControlPlaneError, match="intentionally not accepted"):
        resolve_draft_pr_control_plane_token(
            {"GITHUB_TOKEN": "runner-token", "GH_TOKEN": "ambient-gh-token"}
        )


def test_resolver_uses_only_dedicated_control_plane_token() -> None:
    token = resolve_draft_pr_control_plane_token(
        {
            DRAFT_PR_CONTROL_PLANE_TOKEN_ENV: DEDICATED_TOKEN,
            "GITHUB_TOKEN": "runner-token",
            "GH_TOKEN": "ambient-gh-token",
        }
    )

    assert token == DEDICATED_TOKEN


def test_execute_injects_dedicated_token_and_never_renders_secret() -> None:
    captured_tokens: list[str] = []
    backend = FakeDraftPrBackend()

    def backend_factory(token: str) -> FakeDraftPrBackend:
        captured_tokens.append(token)
        return backend

    result = execute_draft_pr_control_plane(
        _operation(),
        environ={
            DRAFT_PR_CONTROL_PLANE_TOKEN_ENV: DEDICATED_TOKEN,
            "GITHUB_TOKEN": "runner-token",
        },
        backend_factory=backend_factory,
    )

    rendered = render_draft_pr_control_plane_result_json(result)
    assert captured_tokens == [DEDICATED_TOKEN]
    assert backend.create_calls == 1
    assert result.credential_source == DRAFT_PR_CONTROL_PLANE_TOKEN_ENV
    assert result.draft_pr.pull_request_created is True
    assert result.draft_pr.pull_request_ready_for_review is False
    assert result.draft_pr.review_executed is False
    assert result.draft_pr.merge_performed is False
    assert DEDICATED_TOKEN not in rendered
    assert "runner-token" not in rendered


def test_missing_dedicated_token_stops_before_backend_creation() -> None:
    backend_factory_called = False

    def backend_factory(token: str) -> FakeDraftPrBackend:
        nonlocal backend_factory_called
        del token
        backend_factory_called = True
        return FakeDraftPrBackend()

    with pytest.raises(ImplementationDraftPrControlPlaneError, match=DRAFT_PR_CONTROL_PLANE_TOKEN_ENV):
        execute_draft_pr_control_plane(
            _operation(),
            environ={"GITHUB_TOKEN": "runner-token"},
            backend_factory=backend_factory,
        )

    assert backend_factory_called is False


def test_operation_file_is_strict_and_rejects_extra_fields(tmp_path: Path) -> None:
    payload = json.loads(_operation().model_dump_json())
    assert isinstance(payload, dict)
    payload["unexpected"] = True
    path = tmp_path / "draft-pr-control.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ImplementationDraftPrControlPlaneFileError, match="invalid"):
        load_draft_pr_control_plane_operation(path)


def test_operation_file_round_trips_exact_contract(tmp_path: Path) -> None:
    operation = _operation()
    path = tmp_path / "draft-pr-control.json"
    path.write_text(operation.model_dump_json(indent=2), encoding="utf-8")

    loaded = load_draft_pr_control_plane_operation(path)

    assert loaded == operation
