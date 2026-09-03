# Agent System Architecture

## Scope

This document describes the development Agent / DevTools control plane. It does not describe or replace the productive Cisco Assessment runtime.

The two planes are deliberately separated:

```text
PRODUCTIVE ASSESSMENT
Assessment Plan -> Command Catalog -> Collector -> RAW -> Parser -> Models -> Engine -> Rules -> Reporting

DEVELOPMENT CONTROL PLANE
Feature intent -> Intake -> Approval -> Context -> Synthesis -> Workspace -> Work Branch -> CI -> Draft PR -> Review -> Ready -> Human Merge Gate
```

Agents cannot use the development plane to bypass the productive Assessment execution path.

## Main building blocks

### PR Review Agent

Code: `src/cisco_assessment/devtools/pr_review/`

Purpose:

- read Pull Request / repository / CI evidence;
- classify changed components;
- evaluate scope, architecture, contract, metadata and CI-provenance checks;
- derive a canonical review decision.

The PR Review Agent is read-only. It does not create commits, transition PR state or merge.

Stable identity currently exported by the project: `PR_REVIEW_AGENT_V1`.

### Implementation Agent

Code: `src/cisco_assessment/devtools/implementation/`

Purpose:

- consume an approved implementation request;
- load exact repository context;
- build an implementation plan;
- inspect explicitly selected source evidence;
- validate a proposed workspace;
- create a controlled work-branch mutation;
- validate exact-head CI;
- prepare later delivery gates.

Stable identity: `IMPLEMENTATION_AGENT_V1`.

Implementation authorization is intentionally layered rather than universal. Current authorization levels include plan-only, work-branch and Draft-PR bounds.

### Feature Intake

Code: `implementation/feature_intake.py`.

`FEATURE_INTAKE_V1` converts raw human intent into a typed proposal with:

- objective;
- authorized/prohibited components;
- contracts to preserve/change;
- invariants;
- acceptance criteria;
- required evidence;
- ambiguities;
- maximum implementation authorization.

The proposal has no approval authority. Human approval is bound to the exact proposal SHA-256, repository and base SHA before it can become an `ImplementationRequest`.

### Feature Orchestrator

Code: `implementation/orchestrator.py`.

`FEATURE_ORCHESTRATOR_V1` is a typed state machine that records evidence from existing protected gates. It does not itself perform repository mutation, PR transitions, merge or Cisco execution.

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

The orchestration run stores deterministic SHA-256 references to the artifacts used as it advances.

### Run Journal / Resume

Code: `implementation/run_journal.py`.

`FEATURE_RUN_JOURNAL_V1` persists orchestration checkpoints as an append-only, hash-chained sequence.

The journal validates:

- contiguous ordinals;
- checkpoint hashes;
- previous-entry hashes;
- monotonic timestamps;
- stable repository/base identity;
- monotonic checkpoint evidence.

`FEATURE_RUN_RESUME_V1` re-observes the live base branch before deciding whether a persisted run may resume.

Base drift does not silently rebind prior artifacts. The restart contract creates a new run and requires contract reproposal; previous base-bound artifacts are not reused.

### Feature Execution Controller

Code: `implementation/feature_controller.py`.

`FEATURE_EXECUTION_CONTROLLER_V1` composes the existing gates into an executable delivery flow.

Its terminal decisions before the separate merge plane are:

- `HUMAN_MERGE_GATE`;
- `NEEDS_BASE_REFRESH`;
- `BLOCKED`.

It explicitly cannot merge and structurally records `cisco_execution_allowed=false`.

### Synthesis / Authoring boundary

Code: `implementation/synthesis.py` and current concrete backend in `implementation/codex_cli_backend.py`.

The project-owned synthesis contract is `IMPLEMENTATION_SYNTHESIS_V1`. The current external adapter identity is `CODEX_ADAPTER_V1`.

External synthesis receives only approved scope plus selected, byte-pinned source evidence. Its output is an untrusted JSON proposal and cannot claim:

- repository mutation;
- contract approval;
- Cisco execution;
- merge authority.

The output must pass strict project-owned validation and workspace checks before any repository mutation can occur.

Current code names the protocol `CodexSynthesisBackend`; this is an implementation seam, not a declaration that the long-term Agent architecture must require Codex. Future portability may generalize this boundary while keeping the project-owned synthesis contract.

### Work Branch / CI

Implementation mutation is restricted to the approved workspace and controlled work branch. Current full-controller operations require the `agent/implementation/` work-branch namespace.

CI validation is bound to exact repository/branch/head evidence and must distinguish successful CI from stale or unrelated CI.

### Draft PR control plane

Draft PR creation is a separate least-privilege control plane. It uses a dedicated credential and does not grant Ready-for-Review or merge authority.

The implementation subsystem also contains a separate Draft PR Amendment / work-branch resume path for advancing an existing exact Draft PR head under fail-closed checks and fresh CI.

### Ready-for-Review control plane

Code: `ready_for_review.py` and `ready_for_review_control_plane.py`.

Stable control-plane identity: `CONTROLLED_READY_FOR_REVIEW_V1`.

It performs only Draft -> Ready-for-Review after a fresh `PR_REVIEW_AGENT_V1` report returns exact `APPROVE` evidence and base/head bindings remain valid.

Ready-for-Review never implies merge authority.

### Human Merge control plane

Code: `human_merge_gate.py` and `human_merge_control_plane.py`.

Stable control-plane identity: `CONTROLLED_HUMAN_MERGE_V1`.

This is the only current Agent/DevTools path intended to perform merge, and only after:

- explicit human `MERGE_APPROVED` authorization;
- fresh PR review;
- exact repository/PR/base/head binding;
- current Ready state;
- base/head freshness revalidation immediately before mutation;
- post-merge verification of PR state, base head and merge-commit parents.

## Evidence ownership

The architecture distinguishes three kinds of state:

```text
Contracts / policy
  -> Python/Pydantic models + stable IDs

Workflow state
  -> FeatureRunJournal / typed results

External truth
  -> Git/GitHub refs, PRs, commits, workflow runs, job logs
```

No chat is authoritative for any of these.

## Portability boundary

The reusable portion of the Agent system is the delivery/control-plane pattern:

```text
Intent -> Contract -> Approval -> Evidence -> Proposal -> Validation -> CI -> Review -> Human Gate
```

Cisco-specific productive semantics must remain outside the reusable Agent core. Likewise, a future external authoring worker should remain replaceable behind a project-owned interface rather than becoming a public project contract.