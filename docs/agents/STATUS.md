# Agent System Status

Last verified: 2026-08-26
Repository: `luciusblack2411-create/SCRIPTS`
Verified `main`: `7f9eb046c620a45110025e73e3bb309c6f8fff6e`

This file is an operational checkpoint, not a substitute for Git/GitHub verification.

## Current capability baseline

### Integrated / available

- `PR_REVIEW_AGENT_V1` — operational read-only PR review.
- `IMPLEMENTATION_AGENT_V1` — typed implementation scope/readiness/context/planning/workspace/mutation/CI contracts.
- `FEATURE_INTAKE_V1` — typed feature request/proposal plus exact human approval boundary.
- `FEATURE_ORCHESTRATOR_V1` — typed orchestration state machine through `HUMAN_MERGE_GATE`.
- `FEATURE_RUN_JOURNAL_V1` — append-only hash-chained persistence.
- `FEATURE_RUN_RESUME_V1` — live-base resume and explicit base-refresh restart.
- `FEATURE_EXECUTION_CONTROLLER_V1` — executable composition through work branch, CI, Draft PR, PR review, Ready and Human Merge Gate.
- `IMPLEMENTATION_SYNTHESIS_V1` / `CODEX_ADAPTER_V1` — proposal-only external synthesis boundary.
- `LOCAL_FEATURE_EXECUTION_RUNTIME_V1` — current concrete local Agent-First runtime.
- controlled work-branch mutation.
- exact-head implementation CI validation.
- dedicated Draft PR control plane.
- Draft PR Amendment / work-branch resume control plane.
- `CONTROLLED_READY_FOR_REVIEW_V1`.
- `CONTROLLED_HUMAN_MERGE_V1`.
- root-level `/AGENTS.md` integrated by PR #98.

## Current real-validated local synthesis runtime

The current local runtime contract pins:

- Codex CLI `0.149.1`;
- model `gpt-5.6-sol`.

This is the currently validated concrete backend, not a requirement that the long-term reusable Agent architecture depend on Codex.

A portability milestone should eventually generalize the authoring boundary so another project-owned backend can replace Codex without changing delivery contracts.

## Current repository work in parallel

At this checkpoint, GitHub shows active work outside this documentation slice, including:

- PR #99 — Draft DevTools fix for post-amendment PR-head convergence after a successful work-branch ref update.
- PR #93 — Draft M14 Switchport Observation normalized-model slice.

Those PRs are separate work streams and must not be folded into this documentation change.

Several older Agent-First pilot/historical Draft PRs also remain open. They must not be merged merely because they are open; treat them according to their original pilot/historical purpose and revalidate explicitly before any mutation.

## Agent-First productive proof

The Agent Development Pipeline has already been exercised against real repository delivery flows and has been used for productive M14 work.

M14 Command Catalog slice was integrated via PR #92 using the Agent-First path.

This is useful validation evidence, but each future productive layer still requires its own approved scope, evidence, tests and review.

## Known architecture / product gaps

### 1. Feature Design Brief

Backlog initiative: `Feature Design Brief v0.1`.

Desired role:

```text
feature idea
-> executive design brief
-> GO / MODIFY / REJECT
-> FeatureContractProposal
-> implementation
```

It should describe desired information, acquisition method, candidate read-only Command Catalog commands, normalized data, possible rules/decisions, non-inferences, evidence requirements, affected layers, risks and non-scope.

It is not yet a mandatory productive gate until its contract is designed/approved/implemented.

### 2. Offline Evidence Collection / Command Pack

Backlog initiative: `Offline Evidence Collection / Command Pack v0.1`.

Target concept:

```text
closed Command Pack
-> customer/technician collection
-> evidence bundle + manifest/SHA
-> offline importer
-> RawCommandOutput / equivalent evidence boundary
-> existing Parser / Models / Engine / Rules / Reporting
```

It is not yet implemented and must not be simulated through arbitrary Cisco commands or by overloading the SSH Collector.

### 3. Reusable Agent Delivery Framework

The current Agent system is reusable in architecture but still contains project-specific coupling, including `ComponentId`/path classification and current `Codex*` naming/runtime wiring.

Future portability work should separate a generic delivery core from project profiles/policies and pluggable authoring/CI/source backends.

Do not extract prematurely if doing so blocks productive Assessment development; avoid increasing coupling in new Agent code.

### 4. Repository governance

At this checkpoint, the GitHub classic branch endpoint reports `main` as `protected=false` with required status-check enforcement off.

This is a security/governance gap before increasing Agent write autonomy.

Repository rulesets were not independently verified by this checkpoint, so do not infer that no other protection exists. Verify actual branch/ruleset configuration explicitly before changing governance.

Desired defense-in-depth direction:

- require PR-based integration;
- require appropriate CI/status checks;
- restrict force pushes/bypass;
- keep Human Merge Gate as an independent application-layer control.

The Human Merge Gate does not replace repository-side protection.

## Documentation migration status

- Project Instructions updated for Agents/DevTools and persistent state rules: completed.
- Source Library Index updated: completed.
- `agent_automation_sources.md` prepared for Project Sources: completed.
- root `AGENTS.md`: integrated in `main` through PR #98.
- `docs/agents/` reference set: this documentation slice.
- formal continuity/handoff operating procedure: next documentation step after this slice is integrated.

## Invariants that remain non-negotiable

- Agents do not execute Cisco SSH/CLI directly.
- Productive Cisco execution remains Assessment Plan -> Command Catalog -> Collector.
- External synthesis is untrusted/proposal-only.
- No Agent self-approves scope, public contract changes, policy/severity, Cisco execution or merge.
- Ready-for-Review is not merge authority.
- Human Merge remains explicit and exact-SHA bound.
- Real RAW/evidence contracts remain outside Agent automation shortcuts.
- Critical project state must be persisted outside chat.

## Recommended next actions

1. Integrate this `docs/agents/` reference slice after normal documentation PR review/CI.
2. Complete the continuity/handoff procedure so new chats can reconstruct state from `AGENTS.md`, `docs/agents/STATUS.md`, GitHub and the latest domain handoff.
3. Resolve active DevTools/productive PRs in their own chats/scopes; do not mix them into documentation work.
4. Before materially increasing Agent autonomy, review repository branch/ruleset protection.
5. Continue productive Assessment milestones; treat reusable Agent extraction as a controlled future milestone rather than a prerequisite for new Assessment features.

## How to resume from this checkpoint

A new Agent/Automation chat should:

1. read `/AGENTS.md`;
2. read `docs/agents/README.md` and this file;
3. query current `main` and open PRs from GitHub;
4. compare current state to the SHA/status above;
5. report drift before taking action;
6. continue from the current verified repository state, not from stale chat memory.