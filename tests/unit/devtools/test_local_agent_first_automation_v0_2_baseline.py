"""Regression coverage for the Local Agent-First Automation v0.2 A0 baseline."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPOSITORY_ROOT / "docs/agents/LOCAL_AGENT_FIRST_AUTOMATION_V0_2_BASELINE.md"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"

FUNCTIONAL_AGENT_IDS = {
    "IMPLEMENTATION_AGENT_V1",
    "PR_REVIEW_AGENT_V1",
}

STABLE_IDS = {
    "IMPLEMENTATION_AGENT_V1",
    "PR_REVIEW_AGENT_V1",
    "FEATURE_INTAKE_V1",
    "FEATURE_ORCHESTRATOR_V1",
    "FEATURE_RUN_JOURNAL_V1",
    "FEATURE_RUN_RESUME_V1",
    "FEATURE_EXECUTION_CONTROLLER_V1",
    "LOCAL_FEATURE_EXECUTION_RUNTIME_V1",
    "IMPLEMENTATION_SYNTHESIS_V1",
    "CODEX_ADAPTER_V1",
    "CONTROLLED_READY_FOR_REVIEW_V1",
    "CONTROLLED_RETURN_TO_DRAFT_V1",
    "CONTROLLED_HUMAN_MERGE_V1",
}

MANUAL_FALLBACK_COMMANDS = {
    "cisco-implementation",
    "cisco-pr-review",
    "cisco-draft-pr-control",
    "cisco-draft-pr-amendment-control",
    "cisco-ready-for-review-control",
    "cisco-return-to-draft-control",
    "cisco-human-merge-control",
}


def _baseline() -> str:
    return BASELINE_PATH.read_text(encoding="utf-8")


def test_a0_baseline_document_exists() -> None:
    assert BASELINE_PATH.is_file()
    assert _baseline().strip()


def test_baseline_defines_exactly_two_functional_agents() -> None:
    text = _baseline()
    section = text.split("## Functional Agents", 1)[1].split("## Stable contracts", 1)[0]
    listed_ids = set(re.findall(r"^- `([A-Z0-9_]+_AGENT_V1)`:", section, re.MULTILINE))
    assert listed_ids == FUNCTIONAL_AGENT_IDS
    assert "exactly these two IDs" in section
    assert "not additional functional Agents" in section


def test_baseline_preserves_every_stable_id() -> None:
    text = _baseline()
    missing = {
        stable_id
        for stable_id in STABLE_IDS
        if stable_id not in text
    }
    assert not missing, f"baseline is missing stable IDs: {sorted(missing)}"


def test_baseline_freezes_safety_and_authority_invariants() -> None:
    text = _baseline()
    required_statements = (
        "Contract approval is human and explicit.",
        "Approved component scope never expands automatically.",
        "Assessment policy and severity never change autonomously.",
        "Ready-for-Review is not permission to merge.",
        "The Human Merge Gate is mandatory.",
        "Codex proposes content only and cannot mutate the repository directly.",
        "Agent and DevTools execution remains local in WSL",
        "Cisco execution is prohibited for this automation.",
        "GitHub Actions CI supplies external evidence",
        "Chat may provide transient feature intent or discussion only.",
        "Missing, inconsistent, or stale evidence fails closed.",
    )
    for statement in required_statements:
        assert statement in text


def test_baseline_records_exact_authorized_roadmap_without_implementing_later_steps() -> None:
    text = _baseline()

    expected_labels = (
        "A0 — Baseline/Freeze",
        "A1 — Wave/Slice/Run State",
        "A2 — status/next",
        "A3 — run",
        "A4 — resume",
        "A5 — Review/Amendment/CI/Re-review",
        "A6 — Local Waves",
    )

    deprecated_r1_labels = (
        "A1 — Intake ergonomics",
        "A2 — Local run command and recovery UX",
        "A3 — Evidence presentation",
        "A4 — Draft PR amendment loop",
        "A5 — Operational hardening",
        "A6 — Adoption and governance",
    )

    positions = tuple(
        text.index(label)
        for label in expected_labels
    )

    assert positions == tuple(sorted(positions))

    for label in expected_labels:
        assert label in text

    for label in expected_labels[1:]:
        assert f"- **{label}: gap, not implemented.**" in text

    for label in deprecated_r1_labels:
        assert label not in text

    assert "implements none of A1 through A6" in text

def test_documented_manual_fallback_names_match_pyproject_scripts() -> None:
    baseline = _baseline()
    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    declared_scripts = set(
        re.findall(r"^(cisco-[a-z-]+)\s*=", pyproject, re.MULTILINE)
    )
    assert MANUAL_FALLBACK_COMMANDS <= declared_scripts
    for command in MANUAL_FALLBACK_COMMANDS:
        assert f"`{command}`" in baseline
    documented = set(
        re.findall(r"^- `(cisco-[a-z-]+)`$", baseline, re.MULTILINE)
    )
    assert documented == MANUAL_FALLBACK_COMMANDS


def test_baseline_grants_no_automation_merge_or_cisco_authority() -> None:
    text = _baseline().lower()
    forbidden_authority_claims = (
        "agents may merge",
        "agent may merge",
        "automation may merge",
        "automatic merge is allowed",
        "ready-for-review grants merge authority",
        "agents may execute cisco",
        "agent may execute cisco",
        "automation may execute cisco",
        "cisco execution is allowed",
        "codex may mutate the repository directly",
    )
    for claim in forbidden_authority_claims:
        assert claim not in text
    assert "human merge gate remains mandatory" in text
    assert "cisco execution by agents or devtools" in text
    assert "codex remains untrusted proposal-only synthesis" in text


def test_baseline_classifies_pr_100_as_historical_non_authority() -> None:
    text = _baseline()
    assert "PR #100 is historical, non-integrated material" in text
    assert "not a source of truth" in text
