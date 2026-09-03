# Agent System Contracts

## Purpose

This document inventories the stable or externally meaningful Agent/DevTools identities currently present in the repository and summarizes what authority each contract does and does not carry.

The Python models and tests remain authoritative. This document is a navigation/reference layer.

## Contract rules

For persisted or externally consumed Agent/DevTools artifacts:

- IDs and schema versions are stable contracts;
- breaking changes must be explicit;
- external GitHub/Codex payloads must remain behind project-owned adapters/contracts;
- `extra="forbid"` / strict immutable Pydantic models are preferred where implemented;
- a successful validation does not grant authority beyond the contract that was validated.

## Current identities

| Identity | Schema | Role | Mutation authority |
|---|---:|---|---|
| `PR_REVIEW_AGENT_V1` | 1.0 | deterministic/read-only PR review | none |
| `IMPLEMENTATION_AGENT_V1` | 1.0 | implementation scope/readiness/workspace/delivery contracts | only as separately authorized |
| `FEATURE_INTAKE_V1` | 1.0 | feature request, proposal and exact human contract approval | none by proposal alone |
| `FEATURE_ORCHESTRATOR_V1` | 1.0 | typed evidence/state checkpointing | none by itself |
| `FEATURE_RUN_JOURNAL_V1` | 1.0 | append-only hash-chained run history | none |
| `FEATURE_RUN_RESUME_V1` | 1.0 | live-base resume / base-refresh decision | none |
| `FEATURE_EXECUTION_CONTROLLER_V1` | 1.0 | compose protected delivery gates through Human Merge Gate | work-branch/Draft/Ready only through dedicated seams; no merge |
| `IMPLEMENTATION_SYNTHESIS_V1` | 1.0 | project-owned bounded synthesis contract | none |
| `CODEX_ADAPTER_V1` | 1.0 | current external synthesis adapter identity | none |
| `LOCAL_FEATURE_EXECUTION_RUNTIME_V1` | 1.0 | concrete local dependency wiring for the feature controller | no merge / no Cisco |
| `CONTROLLED_READY_FOR_REVIEW_V1` | 1.0 | Draft -> Ready transition after fresh approved review | Ready transition only |
| `CONTROLLED_HUMAN_MERGE_V1` | 1.0 | fresh-review + human-authorized merge control plane | merge only after exact gate |

The Draft PR creation and Draft PR Amendment control planes currently use the `IMPLEMENTATION_AGENT_V1` contract family rather than introducing an independent public `ControlPlaneId` in the operation envelope. Do not invent a new ID in documentation without changing code/tests explicitly.

## `FEATURE_INTAKE_V1`

Primary types:

- `FeatureRequest`;
- `FeatureContractProposalDraft`;
- `FeatureContractProposal`;
- `FeatureContractApproval`.

Important invariants:

- raw request intent is not approval;
- proposal authorized/prohibited components cannot overlap;
- contracts-to-preserve/change cannot overlap;
- proposal authorization cannot exceed the request mutation ceiling;
- proposals require human approval;
- approval binds exact repository + base SHA + proposal SHA-256;
- approval authorization cannot exceed proposal maximum authorization;
- `human_merge_gate_required=true`;
- `cisco_execution_allowed=false`.

The approved output becomes an `ImplementationRequest`.

## `IMPLEMENTATION_AGENT_V1`

Primary request contract: `ImplementationRequest`.

It records:

- repository/base branch;
- objective;
- authorized/prohibited components;
- contracts to preserve/change;
- invariants;
- acceptance criteria;
- required/available evidence;
- explicit authorization level;
- related issue IDs/handoff text where supplied.

Current authorization enum is ordered conceptually as:

```text
PLAN_ONLY < WORK_BRANCH < DRAFT_PR
```

Separate downstream control planes still require their own explicit authority; `DRAFT_PR` is not merge authority.

## `FEATURE_ORCHESTRATOR_V1`

Canonical checkpoint: `FeatureOrchestrationRun`.

It is base-bound and stores hashes/references to the artifacts accumulated across the run.

Current states:

```text
FEATURE_RECEIVED
NEEDS_CONTRACT_APPROVAL
IMPLEMENTATION_READY
WORKSPACE_VALIDATED
CI_PASSED
DRAFT_PR_CREATED
HUMAN_MERGE_GATE
NEEDS_BASE_REFRESH
BLOCKED
```

The orchestration model structurally fixes:

- `merge_performed=false`;
- `human_merge_gate_required=true`;
- `cisco_execution_allowed=false`.

## `FEATURE_RUN_JOURNAL_V1` / `FEATURE_RUN_RESUME_V1`

Journal contracts:

- `FeatureRunJournal`;
- `FeatureRunJournalEntry`.

Resume/base-refresh contracts include:

- `FeatureRunResumeResult`;
- `FeatureBaseRefreshRestart`.

The journal is append-only and hash-chained. Resume is based on a fresh read of live base evidence.

A base refresh creates a distinct run and explicitly sets:

- prior base-bound artifacts reused: false;
- contract reproposal required: true.

## `FEATURE_EXECUTION_CONTROLLER_V1`

Primary contracts:

- `FeatureExecutionDependencies`;
- `FeatureDraftPrAuthorization`;
- `FeatureExecutionOperation`;
- `FeatureExecutionResult`.

A full operation requires:

- exact approved proposal;
- exact contract approval using `WORK_BRANCH` authority;
- separate `DRAFT_PR_APPROVED` authorization bound to proposal/base;
- explicit Ready-for-Review authorization;
- selected source paths;
- controlled work branch under `agent/implementation/`;
- commit/PR metadata;
- bounded timeout/poll configuration.

Terminal decisions before merge:

- `HUMAN_MERGE_GATE`;
- `NEEDS_BASE_REFRESH`;
- `BLOCKED`.

`merge_performed=false` is structural in this controller.

## `IMPLEMENTATION_SYNTHESIS_V1` / `CODEX_ADAPTER_V1`

Primary types:

- `CodexSynthesisPrompt`;
- `CodexSynthesisChange`;
- `CodexSynthesisOutput`;
- `CodexSynthesisBackend` protocol.

Despite the current `Codex*` naming, project authority comes from the project-owned synthesis/workspace contracts, not from the provider.

Prompt/output contracts bind:

- repository;
- base SHA;
- objective;
- authorized/prohibited components;
- contracts;
- invariants;
- acceptance criteria;
- selected source evidence.

External output is rejected if it is invalid JSON, violates the strict schema, changes the bound repository/base/objective, duplicates paths, or fails workspace validation.

The synthesis contract explicitly records no repository mutation, no contract approval and no Cisco execution authority.

## `LOCAL_FEATURE_EXECUTION_RUNTIME_V1`

This is the current concrete local wiring for real Agent-First execution.

At the current repository contract it validates:

- Codex CLI version `0.149.1`;
- Codex model `gpt-5.6-sol`;
- explicit implementation, Draft PR and PR Review credentials;
- those three credentials are distinct;
- Human Merge remains outside the runtime;
- Cisco execution remains disabled.

These version pins describe the current real-validated runtime, not a requirement that future reusable Agent frameworks must permanently use Codex.

## `PR_REVIEW_AGENT_V1`

Primary public types include:

- `ReviewRequest`;
- `ReviewReport`;
- `ReviewCheck`;
- `ReviewFinding`;
- `ReviewEvidence`;
- `PullRequestContext`.

The agent derives decisions from typed checks covering scope, architecture/safety, contract/quality, metadata and CI provenance.

Review output is evidence for later gates. It is not repository mutation authority.

## `CONTROLLED_READY_FOR_REVIEW_V1`

Primary contracts:

- `ReadyForReviewOperation`;
- `ReadyForReviewResult`.

Explicit authorization enum/value: `READY_FOR_REVIEW`.

Canonical decisions:

- `READY_FOR_REVIEW`;
- `REVIEW_NOT_APPROVED`;
- `NEEDS_BASE_REFRESH`.

The gate runs a fresh independent review and permits only Draft -> Ready when `ReviewDecision.APPROVE` and exact base/head evidence remain valid.

It structurally records `merge_performed=false` and `cisco_execution_allowed=false`.

## `CONTROLLED_HUMAN_MERGE_V1`

Primary contracts:

- `HumanMergeAuthorization`;
- `HumanMergeOperation`;
- `HumanMergeResult`.

Explicit human decision: `MERGE_APPROVED`.

Canonical decisions:

- `MERGED`;
- `REVIEW_NOT_APPROVED`;
- `NEEDS_BASE_REFRESH`.

Authorization binds exact:

- repository;
- PR number;
- base SHA;
- head SHA;
- human identity and rationale.

The gate performs a fresh review, checks Ready state, rereads refs immediately before merge, uses an expected head SHA and verifies the merged PR/base/parents after mutation.

## Public contract change checklist

Before changing one of these identities or schemas:

1. identify all persisted/external consumers;
2. classify whether the change is additive or breaking;
3. update typed models and tests first;
4. update adapters/control planes;
5. update this document and `STATUS.md` if operational behavior changes;
6. preserve migration/backward compatibility where the project contract requires it;
7. require explicit human approval for any scope/authority expansion.