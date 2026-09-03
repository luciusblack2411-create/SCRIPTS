# Agent Delivery Workflow

## Objective

Define the operational path used to convert approved feature intent into a reviewed Pull Request while preserving explicit human authority at the contract and merge boundaries.

This workflow is for development automation only. It never authorizes Cisco SSH/CLI execution.

## End-to-end path

```text
Human feature intent
  -> FeatureRequest
  -> FeatureContractProposal
  -> Human contract approval
  -> ImplementationRequest
  -> exact repository context
  -> implementation plan
  -> explicit source inspection
  -> synthesis proposal
  -> validated workspace
  -> controlled work-branch mutation
  -> exact-head CI
  -> controlled Draft PR
  -> fresh PR Review Agent
  -> controlled Ready-for-Review
  -> HUMAN_MERGE_GATE
  -> separate explicit Human Merge control plane
```

## Phase 0 — Feature intent

Input: a human request describing the feature or change.

The request is not treated as broad mutation authority.

Record, at minimum:

- repository;
- expected base branch;
- request text;
- maximum requested authorization;
- explicitly supplied evidence;
- related issue IDs if applicable.

If the desired behavior is ambiguous or requires Cisco facts not demonstrated by sources/RAW, resolve that before implementation.

## Phase 1 — Feature contract proposal

`FEATURE_INTAKE_V1` converts the request into a bounded proposal.

A good proposal states:

- objective;
- authorized components;
- prohibited components;
- contracts to preserve;
- contracts intentionally changed;
- invariants;
- acceptance criteria;
- required evidence;
- unresolved ambiguities;
- maximum authorization.

The proposal is bound to the observed base SHA and produces a deterministic SHA-256.

### Stop condition

State: `NEEDS_CONTRACT_APPROVAL`.

Do not implement until a human approval exactly matches repository, base SHA and proposal SHA-256.

## Phase 2 — Implementation readiness

Approved intake becomes an `ImplementationRequest`.

The Implementation Agent validates readiness and loads repository context from the exact approved base.

Read context may include explicitly named prohibited components as read-only evidence, but mutation authority remains limited to authorized components.

### Stop conditions

- required evidence missing;
- contract not approved;
- scope invalid;
- authorization insufficient;
- base moved.

Expected outcome: `READY`, human input required, or blocked according to the implementation readiness contract.

## Phase 3 — Planning and source inspection

Build the deterministic implementation plan from the approved request and exact context.

Inspect only explicitly selected source paths. Each inspected source is bound to repository/base/blob evidence.

Do not infer additional mutation scope merely because a file was read.

## Phase 4 — Synthesis / code authoring proposal

Current concrete path uses `IMPLEMENTATION_SYNTHESIS_V1` through `CODEX_ADAPTER_V1`.

The external worker receives:

- approved scope;
- exact base identity;
- plan step IDs;
- selected source evidence;
- contracts/invariants/acceptance criteria.

It returns JSON file-change proposals only.

### Mandatory validation

Before repository mutation, reject output that:

- is not valid strict JSON;
- changes repository/base/objective binding;
- duplicates paths;
- cites unapproved acceptance criteria;
- proposes changes outside authorized workspace scope;
- attempts to claim approval, mutation, Cisco or merge authority.

The project-owned `ImplementationWorkspace` is the trusted boundary, not the external worker output.

## Phase 5 — Work-branch mutation

Mutation requires explicit `WORK_BRANCH` authority.

Current full-controller work branches must use:

```text
agent/implementation/
```

The mutation is based on the approved exact base and validated workspace.

After mutation, record exact work branch and commit SHA.

### Stop condition

Any concurrent ref/base drift or invalid mutation evidence fails closed.

## Phase 6 — CI gate

Run/observe CI for the exact implementation head.

Required evidence must prove the CI belongs to the expected repository/head/workflow context. Successful but stale/unrelated CI is not accepted.

Typical project quality gates include:

- dependency verification;
- Ruff;
- strict mypy;
- pytest;
- package build;
- CLI/control-plane smoke tests.

### Outcomes

- exact CI passed -> `CI_PASSED` / ready for Draft PR;
- base drift -> `NEEDS_BASE_REFRESH`;
- failed/incomplete evidence -> blocked.

## Phase 7 — Draft PR

Draft PR authority is separate from work-branch mutation authority.

Creation requires a proposal/base-bound `DRAFT_PR_APPROVED` authorization and the dedicated Draft PR control plane.

The resulting PR must remain Draft at this stage.

Creating it does not authorize Ready or merge.

## Phase 8 — Draft PR amendment / resume when needed

If an existing Draft PR needs a new implementation head, use the separate Draft PR Amendment path rather than bypassing the original create-only mutation contract.

The amendment path must preserve:

- exact same-repository Draft PR binding;
- expected old head;
- allowed base evidence;
- fast-forward-only ref update;
- fresh CI for the new exact head;
- fail-closed handling of unexpected refs/states.

Bounded polling may be used only for explicitly modeled GitHub eventual-consistency windows.

## Phase 9 — PR Review

Run `PR_REVIEW_AGENT_V1` against current PR/repository/CI evidence.

The review evaluates scope and architecture independently of synthesis and implementation readiness.

Possible review outcomes include approval, human review, change request or blocked states according to the current review contract.

CI success alone is not review approval.

## Phase 10 — Ready for Review

`CONTROLLED_READY_FOR_REVIEW_V1` requires explicit `READY_FOR_REVIEW` authorization.

It runs a fresh review and performs only Draft -> Ready when:

- review decision is exact `APPROVE`;
- PR/base/head bindings match;
- base freshness remains valid before/after the transition.

Otherwise it returns `REVIEW_NOT_APPROVED` or `NEEDS_BASE_REFRESH`.

## Phase 11 — Human Merge Gate

The feature controller stops here.

State:

```text
HUMAN_MERGE_GATE
```

This state means the feature delivery path reached fresh reviewed Ready evidence. It does not mean merge is authorized or performed.

## Phase 12 — Separate controlled Human Merge

Merge requires a new explicit `HumanMergeAuthorization` with decision `MERGE_APPROVED`, bound to the exact:

- repository;
- PR number;
- base SHA;
- head SHA;
- authorizing human;
- rationale.

`CONTROLLED_HUMAN_MERGE_V1` then:

1. runs a fresh PR review;
2. validates approval and authorization binding;
3. checks current PR is open, Ready and unmerged;
4. checks live PR/base/head refs;
5. rereads refs immediately before mutation;
6. merges using expected head SHA;
7. verifies merged PR, new base head and merge-commit parents.

Only this phase may report `MERGED`.

## Journal checkpoints

Every significant controller transition is persisted in `FEATURE_RUN_JOURNAL_V1`.

Expected progression for a successful run:

```text
FEATURE_RECEIVED
-> NEEDS_CONTRACT_APPROVAL
-> IMPLEMENTATION_READY
-> WORKSPACE_VALIDATED
-> CI_PASSED
-> DRAFT_PR_CREATED
-> HUMAN_MERGE_GATE
```

The journal is append-only/hash-chained and does not authorize skipping phases.

## Resume and base drift

Before resuming a persisted run, reobserve the live base branch.

If live base != approved base:

```text
NEEDS_BASE_REFRESH
```

Do not silently rebase old approvals/workspaces/review evidence.

Start a distinct refreshed run and repropose the contract against the new base.

## Human decision points

A human decision remains mandatory for at least:

- approval of the feature contract;
- scope expansion;
- public/breaking contract changes;
- policy/severity changes;
- ambiguous Cisco semantics requiring product decision;
- merge authorization.

No Agent may infer these approvals from a chat phrase, CI success, reviewer output or GitHub mergeability alone unless the applicable typed authorization contract is explicitly created.

## Workflow completion definition

A development feature is not complete merely because code exists.

For an integrated change, preserve evidence for:

```text
approved scope
+ exact base/head
+ implementation/test evidence
+ PR review
+ CI
+ explicit merge authorization
+ verified merge/main state
```

Then update the relevant project status/handoff documentation.