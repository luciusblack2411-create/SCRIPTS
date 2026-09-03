# Local Agent-First Automation v0.2 — A0 Baseline

Status: A0 documentation baseline only  
Repository: `luciusblack2411-create/SCRIPTS`  
Base branch: `main`  
Baseline base SHA: `f7c4ef16eb16471425ee480756637e754411dc49`

## Purpose and scope

This document freezes the current Local Agent-First Automation v0.2 baseline. A0 records existing identities, contracts, delivery behavior, authority boundaries, evidence precedence, the manual fallback, and the A0–A6 gap analysis. It changes no productive runtime behavior and implements none of A1 through A6.

The automation and all DevTools stay outside the productive Cisco assessment runtime. The baseline neither adds a runtime integration nor grants any Cisco, contract-approval, policy, scope, or merge authority.

## Functional Agents

The complete functional Agent inventory contains exactly these two IDs:

- `IMPLEMENTATION_AGENT_V1`: consumes an explicitly approved, base-bound implementation contract; inspects authorized evidence; obtains proposal-only synthesis; validates a workspace; and, when separately authorized, drives protected work-branch, CI, Draft PR, and Ready-for-Review gates.
- `PR_REVIEW_AGENT_V1`: independently reviews one exact pull request and its base/head evidence against approved scope, stable contracts, invariants, and CI evidence; it returns a typed review decision but cannot merge.

Controllers, runtimes, adapters, control planes, GitHub Actions workflows, and Codex are not additional functional Agents.

## Stable contracts and control-plane identities

A0 preserves these existing IDs unchanged:

- `IMPLEMENTATION_AGENT_V1`
- `PR_REVIEW_AGENT_V1`
- `FEATURE_INTAKE_V1`
- `FEATURE_ORCHESTRATOR_V1`
- `FEATURE_RUN_JOURNAL_V1`
- `FEATURE_RUN_RESUME_V1`
- `FEATURE_EXECUTION_CONTROLLER_V1`
- `LOCAL_FEATURE_EXECUTION_RUNTIME_V1`
- `IMPLEMENTATION_SYNTHESIS_V1`
- `CODEX_ADAPTER_V1`
- `CONTROLLED_READY_FOR_REVIEW_V1`
- `CONTROLLED_RETURN_TO_DRAFT_V1`
- `CONTROLLED_HUMAN_MERGE_V1`

These names are stable contract or control-plane identifiers; listing them does not create new components or change their authority.

## Current delivery flow

The current delivery path is:

1. **Feature Intake** (`FEATURE_INTAKE_V1`) captures human intent and explicit evidence, observes the `main` base SHA, and produces a proposal with bounded authorized and prohibited components.
2. **Human Contract Approval** binds an explicit decision to the repository, exact base SHA, proposal hash, and maximum authorization. Automation cannot supply this approval.
3. **Orchestration and journal start** (`FEATURE_ORCHESTRATOR_V1`, `FEATURE_RUN_JOURNAL_V1`) create typed, hash-chained checkpoints for the exact run.
4. **Resume/freshness evaluation** (`FEATURE_RUN_RESUME_V1`) compares the journal's base binding with the live Git/GitHub base ref. Drift stops progress with a refresh decision.
5. **Implementation preparation** uses approved context, planning, source inspection, `IMPLEMENTATION_SYNTHESIS_V1`, and the proposal-only `CODEX_ADAPTER_V1`. Project-owned validation accepts or rejects the untrusted proposal.
6. **Protected implementation execution** (`FEATURE_EXECUTION_CONTROLLER_V1` through `LOCAL_FEATURE_EXECUTION_RUNTIME_V1`) may create an authorized work-branch commit, collect exact-head CI evidence, and create a Draft PR using separated credentials and gates.
7. **Independent PR review** checks the exact repository, PR, base branch/SHA, head branch/SHA, approved component scope, preserved contracts, invariants, and required CI provenance.
8. **Ready-for-Review gate** (`CONTROLLED_READY_FOR_REVIEW_V1`) may perform only the Draft-to-Ready transition after a fresh approving review and repeated live-ref checks. Ready-for-Review grants no merge authority.
9. **Return-to-Draft gate**, when explicitly invoked, is bounded by `CONTROLLED_RETURN_TO_DRAFT_V1` and exact live refs. It performs no merge.
10. **Human Merge Gate** remains mandatory. `CONTROLLED_HUMAN_MERGE_V1` can act only after explicit human authorization bound to the exact repository, PR, base SHA, and head SHA, plus a fresh approving review and immediate live-ref verification.

## Local execution boundary

All Agent, controller, Codex adapter, and journal execution occurs locally in WSL. DevTools do not run inside the productive Cisco runtime. GitHub is contacted only through the existing bounded read or control-plane surfaces.

GitHub Actions CI supplies external evidence about an exact commit or merge provenance. A workflow or CI job is not a remote Agent, does not interpret or approve a feature contract, and does not acquire scope, policy, severity, Cisco, or merge authority.

## Source-of-truth hierarchy

When evidence conflicts, the following authority and evidence hierarchy applies:

1. **Live Git/GitHub state** is authoritative for current branches, pull-request state, base/head refs, commit identity, and CI observations.
2. **Typed contracts and explicit human authorizations** are authoritative for approved objective, component scope, preserved or changed contracts, invariants, and permitted operations. Live state cannot enlarge that authority.
3. **Hash-chained run journals** are the persisted execution history and resume evidence for a base-bound run. They cannot override newer live-ref evidence.
4. **Version-controlled documentation**, including this baseline, explains the intended system and stable boundaries but does not itself authorize an operation.
5. **Chat** may provide transient feature intent or discussion only. It is not persisted operational authority and cannot override live state, typed contracts, authorizations, or journals.

A safe action requires agreement among the applicable layers. Missing, inconsistent, or stale evidence fails closed.

## SHA binding and freshness

Every proposal and execution run is bound to an observed base SHA. Workspaces, commits, Draft PR evidence, review reports, CI evidence, and human authorizations remain bound to their exact base/head SHAs. Before a protected transition, the control plane re-reads the applicable live refs; sensitive transitions use an immediate second freshness check.

If the base or head cannot be observed, differs from the bound evidence, changes during a gate, or has ambiguous current-head CI provenance, automation stops. The result is a blocked, ref-refresh, or base-refresh outcome rather than inferred freshness. A base refresh starts a distinct run and requires contract reproposal; stale base-bound artifacts are not reused.

## Manual CLI fallback

The existing manual control-plane fallback remains supported through the script names already declared in `pyproject.toml`:

- `cisco-implementation`
- `cisco-pr-review`
- `cisco-draft-pr-control`
- `cisco-draft-pr-amendment-control`
- `cisco-ready-for-review-control`
- `cisco-return-to-draft-control`
- `cisco-human-merge-control`

`cisco-assessment` is the productive assessment CLI, not an Agent fallback and not an automation authority. Operators remain responsible for supplying valid typed operation files, distinct least-privilege credentials, explicit approvals, and current SHA bindings.

## A0–A6 roadmap and current gaps

- **A0 — Baseline/Freeze: documented in this change.** Freeze the current Agent-First identities, reused stable contracts/control planes, authority boundaries, source-of-truth hierarchy, manual fallback, and the approved A0–A6 roadmap. No runtime behavior changes.
- **A1 — Wave/Slice/Run State: gap, not implemented.** Reuse `FEATURE_ORCHESTRATOR_V1`, `FEATURE_RUN_JOURNAL_V1`, and `FEATURE_RUN_RESUME_V1`; add only the missing Wave/Slice composition and aggregation needed around the existing per-run state and evidence.
- **A2 — status/next: gap, not implemented.** Reuse journal, orchestration, and resume evidence to expose deterministic operator-facing status and next-action projections without adding authority.
- **A3 — run: gap, not implemented.** Reuse `FEATURE_EXECUTION_CONTROLLER_V1` and `LOCAL_FEATURE_EXECUTION_RUNTIME_V1` to provide a local incremental run surface; do not create a second execution engine.
- **A4 — resume: gap, not implemented.** Reuse `FEATURE_RUN_RESUME_V1` and persisted journal checkpoints to continue from the correct safe checkpoint without repeating already-completed repository mutations.
- **A5 — Review/Amendment/CI/Re-review: gap, not implemented.** Compose the existing `PR_REVIEW_AGENT_V1`, Return-to-Draft, Draft PR Amendment, fresh CI, re-review, and Ready-for-Review control planes into a persisted correction loop without merge authority.
- **A6 — Local Waves: gap, not implemented.** Compose A1–A5 locally in WSL so multiple authorized slices can progress in deterministic order while preserving per-slice contracts, evidence, freshness, and the mandatory Human Merge Gate.

No A1–A6 item is authorized by A0. Each requires its own approved feature contract and evidence.

## Historical material

PR #100 is historical, non-integrated material. It is not part of this A0 baseline, not evidence of current repository behavior, and not a source of truth. Any useful idea from it must be independently proposed, approved, implemented, and verified against current live state and stable contracts.

## MUST_NOT_IMPLEMENT

A0 explicitly forbids implementation of:

- new functional Agents or any change to the exactly-two-Agent inventory;
- remote Agents, including treating GitHub Actions CI as an Agent;
- automatic feature-contract approval or inferred human authorization;
- automatic expansion of approved component, file, contract, or evidence scope;
- autonomous assessment-policy or finding-severity changes;
- automatic merge, self-granted merge rights, or any interpretation of Ready-for-Review as merge authority;
- Cisco SSH, Cisco CLI, device mutation, or any other Cisco execution by Agents or DevTools;
- direct repository mutation by Codex; Codex remains untrusted proposal-only synthesis behind `CODEX_ADAPTER_V1`;
- a new or incompatible state store that bypasses or rewrites the typed hash-chained journal contract;
- chat transcripts, chat memory, or conversational claims as persisted operational authority;
- changes to `pyproject.toml`, CI tooling, DevTools runtime code, or the productive Cisco runtime as part of A0.

## Frozen safety and authority invariants

- Contract approval is human and explicit.
- Approved component scope never expands automatically.
- Assessment policy and severity never change autonomously.
- Repository transitions require their exact typed authorization and fresh evidence.
- Ready-for-Review is not permission to merge.
- The Human Merge Gate is mandatory.
- Codex proposes content only and cannot mutate the repository directly.
- Agent and DevTools execution remains local in WSL and outside productive Cisco execution.
- Cisco execution is prohibited for this automation.
- A0 is documentation plus regression coverage only.


## A0 authority wording frozen by regression

- Chat may provide transient feature intent or discussion only.
- Human Merge Gate remains mandatory.
