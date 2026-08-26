# Agent System Security Model

## Objective

Keep development automation useful without allowing an Agent, external model, CI result, or GitHub payload to silently acquire broader authority than the human-approved task.

The design follows these priorities:

```text
least privilege > convenience
exact evidence > inference
fail closed > unsafe continuation
human authorization > self-approval
project-owned contract > external schema
```

## Trust boundaries

### 1. Human intent is not implementation authority

A raw request such as “implement feature X” is input, not authorization to mutate arbitrary files.

`FEATURE_INTAKE_V1` separates:

- requested objective;
- mutation ceiling;
- evidence supplied;
- proposed authorized/prohibited components;
- contracts and acceptance criteria;
- human approval of the exact proposal.

Approval is bound to repository, base SHA and proposal SHA-256.

### 2. Generative output is untrusted

External synthesis is proposal-only.

Current `IMPLEMENTATION_SYNTHESIS_V1` / `CODEX_ADAPTER_V1` explicitly forbids the synthesis output from claiming repository mutation, contract approval or Cisco authority.

Project-owned Pydantic validation and workspace validation remain authoritative after synthesis.

### 3. GitHub metadata is external evidence

PR, branch, commit and CI payloads are not trusted merely because they came from GitHub.

Control planes validate the fields needed for the decision and bind critical operations to exact repository/base/head evidence.

Historical event metadata must not replace stronger direct evidence when the contract requires live branch state or exact checkout provenance.

### 4. CI success is necessary evidence, not merge authority

A green workflow does not imply:

- correct scope;
- approved policy;
- fresh review;
- Ready-for-Review permission;
- merge permission.

CI provenance must match the exact head and required workflow evidence.

### 5. Chat context is not trusted state storage

Critical workflow state belongs in Git/GitHub, typed contracts, tests, CI evidence and hash-chained journals.

Handoffs are navigation aids and must be checked against persisted state before work continues.

## Capability versus authority

A backend may technically be able to perform an operation without being authorized to do so.

Keep these distinct:

```text
read capability
!= work-branch mutation authority
!= Draft PR authority
!= Ready-for-Review authority
!= merge authority
!= Cisco execution authority
```

No Agent may self-escalate from one capability to another.

## Cisco isolation

Agents / DevTools are outside the productive Cisco runtime.

They MUST NOT execute Cisco SSH/CLI directly.

Productive device access remains exclusively:

```text
Assessment Plan -> Command Catalog -> Collector
```

Agent contracts repeatedly preserve `cisco_execution_allowed=false` as a structural invariant.

No GitHub or coding-agent credential should ever be interpreted as Cisco authority.

## Repository mutation safety

Repository writes require an approved project-owned mutation path.

Expected properties include, as applicable:

- exact repository binding;
- expected base branch and SHA;
- approved components and paths;
- validated workspace;
- controlled work-branch namespace;
- no force update unless a future explicit contract authorizes it;
- fresh head observation before mutation;
- post-mutation verification.

If a ref has moved unexpectedly, stop rather than rebasing authority implicitly.

## Base/head freshness

Base and head evidence must be treated as time-sensitive.

The system uses exact SHA binding so that an approval for one revision cannot silently apply to a later one.

Expected fail-closed outcomes include:

- `NEEDS_BASE_REFRESH` when the approved base is stale;
- `BLOCKED` when evidence is incomplete or invalid;
- human review when a deterministic gate requires human judgment.

Base refresh creates a new run and requires reproposal instead of reusing prior base-bound artifacts.

## PR transition safety

### Draft PR

Draft PR creation is separate from implementation mutation and uses a dedicated credential boundary.

Creating a Draft PR grants neither Ready nor merge authority.

### Draft PR Amendment

Amendment of an existing Draft PR must remain bound to the exact PR, repository, expected old head and allowed base evidence. Ref advancement is fast-forward only and requires fresh exact-head CI.

Temporary GitHub eventual-consistency states may be retried only where the project contract explicitly permits bounded polling; unexpected states fail closed.

### Ready for Review

`CONTROLLED_READY_FOR_REVIEW_V1` requires explicit Ready authorization and a fresh `PR_REVIEW_AGENT_V1` result.

Only exact `APPROVE` evidence may transition Draft -> Ready. Base drift or stale binding stops the transition.

### Human Merge

`CONTROLLED_HUMAN_MERGE_V1` requires explicit `MERGE_APPROVED` authorization bound to the exact repository, PR, base SHA and head SHA.

It re-runs review, revalidates live refs immediately before the only permitted merge mutation, supplies the expected head SHA to the GitHub merge call and verifies the resulting merge afterward.

## Credential model

Secrets are capabilities and must remain least-privilege, explicit and non-persistent in logs/journals/docs.

Current local Agent-First execution separates at least:

- `CISCO_ASSESSMENT_IMPLEMENTATION_TOKEN`;
- `CISCO_ASSESSMENT_DRAFT_PR_TOKEN`;
- `CISCO_ASSESSMENT_PR_REVIEW_TOKEN`.

The local runtime requires these three values to be distinct.

Ready-for-Review and Human Merge have their own control-plane credential boundaries in their respective modules.

Never document secret values. Document only credential names/capabilities.

Do not silently fall back to ambient `GITHUB_TOKEN` / `GH_TOKEN` where a dedicated control-plane contract requires a distinct credential.

## External worker isolation

The current local Codex backend is intentionally proposal-only.

Its security boundary includes project-owned validation plus the concrete backend/runtime restrictions implemented in code. External worker credentials and environment exposure must stay minimal.

A future alternate worker must satisfy the same project-owned safety properties; provider-specific behavior must not become implicit project authority.

## Persistence integrity

`FEATURE_RUN_JOURNAL_V1` protects workflow history through:

- canonical checkpoint SHA-256;
- entry SHA-256;
- previous-entry hash chaining;
- contiguous ordinals;
- monotonic timestamps;
- atomic local writes;
- full model revalidation on load.

A journal proves consistency of the persisted project artifact; it does not replace fresh GitHub observations for time-sensitive refs.

## Repository governance

Agent control planes are one defense layer. Repository-side branch/ruleset protection should provide an independent defense layer.

Do not assume `main` is protected merely because the workflow intends PR-only delivery. Verify GitHub protection/rulesets explicitly before increasing automation authority.

## Fail-closed conditions

Stop rather than continue when any required condition cannot be demonstrated, including:

- missing approval;
- unknown scope;
- conflicting authorized/prohibited components;
- required evidence missing;
- base drift;
- head drift;
- unexpected PR state;
- invalid or stale review;
- ambiguous CI provenance;
- invalid external synthesis JSON;
- synthesis metadata mismatch;
- workspace path outside authorized scope;
- credential failure;
- unexpected external API schema/state.

No uncertainty should be converted into authorization.

## Security review checklist

For a new Agent/DevTools capability, confirm:

- What exact capability is added?
- Which human authorization gates it?
- What repository/base/head values bind it?
- Which credential can perform it?
- Is that credential narrower than adjacent control planes?
- What external data is trusted, and how is it validated?
- What happens on stale or missing evidence?
- Can the Agent broaden scope or authority itself? It must not.
- Can it execute Cisco? It must not.
- Can it merge without `CONTROLLED_HUMAN_MERGE_V1`? It must not.
- Are tests present for both success and fail-closed cases?