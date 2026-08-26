# AGENTS.md — Cisco Switch Assessment Framework

## Purpose

This file defines repository-level operating instructions for coding agents, generative workers, and development automation working on this repository.

It does not replace project contracts, tests, Git/GitHub controls, or human approval gates. It does not grant authority to execute Cisco commands, expand scope, change policy, or merge code.

When a task conflicts with a persisted project contract or an explicit human authorization, stop and report the conflict.

---

## Project mission

Develop and evolve a modular, typed, testable Python framework for automated, reproducible, traceable assessments of Cisco switches.

The productive assessment runtime is read-only:

Assessment Plan
    -> Command Catalog
    -> Collector / SSH
    -> RawCommandOutput
    -> Parser
    -> Normalized Models
    -> Assessment Engine
    -> Rules
    -> Findings
    -> Reporting

Observe, evaluate, and recommend. Never auto-remediate.

Current productive platform scope:
- Cisco IOS;
- Cisco IOS-XE.

NX-OS is preparatory only until real commands, RAW fixtures, parsers, tests, and plans exist.

---

## Highest-priority invariants

1. Evidence over inference.
2. Own contracts over external schemas.
3. Determinism over heuristics.
4. Traceability over convenience.
5. Real fixtures over fabricated examples.
6. Small scoped changes over broad rewrites.
7. Read-only Cisco behavior over aggressive automation.
8. Fail closed when authorization, provenance, or evidence cannot be demonstrated.

---

## Cisco execution boundary

Agents and development tools MUST NOT execute Cisco SSH/CLI directly.

Productive Cisco execution is permitted only through:

Assessment Plan
    -> Command Catalog
    -> Collector

Only commands explicitly registered in the Command Catalog may be productively executed.

Do not introduce arbitrary CLI execution paths.

Forbidden productive actions include configuration or state-changing operations such as:
- `configure`;
- `clear`;
- `reload`;
- `reset`;
- `delete`;
- `erase`;
- `install`;
- interface/VLAN/STP/EtherChannel/AAA changes;
- configuration save/write;
- automated remediation.

Cisco documentation may explain semantics or recommendations. It never grants write authority.

---

## Layer responsibilities

Do not move logic between layers for convenience.

### Command Catalog / Plans

Own:
- stable `CommandId`;
- exact CLI;
- platform variant;
- purpose;
- expected parser/model;
- required/optional status;
- closed typed execution plans.

Platform differences must be explicit.

### Collector

Owns only:
- SSH transport;
- authentication;
- prompt handling;
- timeouts/deadlines;
- pagination;
- authorized command execution;
- RAW receipt;
- transport errors;
- connection close.

Collector must not:
- interpret Cisco semantics;
- normalize data;
- evaluate health;
- generate Findings.

External SSH libraries remain behind project-owned abstractions.

### RAW / Evidence

Preserve `RawCommandOutput` byte-exact whenever possible.

Maintain the metadata required by contracts, including as applicable:
- command/variant;
- platform;
- timestamps;
- device/run identity;
- SHA-256;
- source/provenance metadata.

Traceability target:

Finding
    -> EvidenceRequest / RuleResult
    -> normalized field path
    -> FieldEvidence
    -> SourceTrace
    -> RAW

Do not invent unavailable data. Use `None`, `unknown`, `NOT_APPLICABLE`, or the contractually defined equivalent.

Never modify a real RAW fixture merely to make a parser or test pass.

### Parsers

Parsers transform:

RawCommandOutput
    -> Normalized Model

Parsers do not determine health, severity, policy compliance, or remediation.

Each productive parser must have the applicable stable identities and version/schema contracts, including:
- `ParserId`;
- `CommandId`;
- `NormalizedModelId`;
- supported platform(s);
- tests using RAW fixtures.

Genie/TextFSM/custom parsing are implementation choices, not public contracts.

### Genie / pyATS

Genie is offline extraction only.

Allowed architecture:

own Collector
    -> own RAW
    -> Genie with previously collected output
    -> own adapter
    -> own Pydantic model

Do not use Genie/Testbed/Unicon/device execution as the productive collector.

Rules and Reporting must not depend on Genie dictionaries, schemas, classes, or exceptions.

Use the versions declared by the repository. Do not silently upgrade Genie/pyATS; validate dependency changes against real fixtures.

### Normalized Models

Prefer:
- Pydantic;
- explicit typing;
- immutable models where appropriate;
- `extra="forbid"`;
- strict validation where coercion could hide incorrect evidence.

Do not place RAW bytes, Paramiko objects, Genie objects, or accidental parser metadata inside normalized domain models.

Evidence belongs outside normalized models through project evidence contracts.

### Assessment Engine / Rules

Engine consumes normalized models and evidence.

It must not depend on Collector, Parser, Genie, or Reporting.

Rules must be deterministic and based only on normalized/evidenced data.

Keep separate:
- factual observation;
- evaluation;
- recommendation;
- informational remediation guidance.

Do not turn a best practice into `FAIL` without explicit policy.

Minimum supported result states include:
- `PASS`;
- `FAIL`;
- `WARNING`;
- `INFO`;
- `NOT_APPLICABLE`;
- `ERROR`.

### Reporting

Reporting consumes evaluated results.

It must not:
- parse CLI;
- execute rules;
- query devices;
- recalculate severity.

Preserve finding identity, status, recommendation, evidence, and traceability.

---

## Source-of-truth rules

For Cisco output format and semantics, prioritize:

1. sanitized real RAW;
2. regression fixture;
3. matching Cisco Command Reference;
4. matching Configuration Guide;
5. other official Cisco documentation.

RAW governs observed format.
Cisco documentation governs meaning.

For Python implementation, prefer official Python/library documentation.

For Genie/pyATS behavior, prefer official Cisco DevNet/CiscoTestAutomation sources and the code/version actually installed.

For GitHub/Agent control-plane behavior, prefer project-owned contracts plus official GitHub/Git/provider documentation.

Do not use chat memory as the sole source of truth for critical project state.

---

## Repository and Git workflow

`main` represents stable integrated state.

Prefer one logical change per branch/PR.

Before implementing:
1. inspect the current repository state;
2. identify the exact base branch/SHA when required by the task;
3. identify authorized and prohibited components;
4. preserve existing public contracts unless change is explicitly authorized.

Before integration, validate:
- scope;
- diff;
- architecture boundaries;
- Cisco read-only invariants;
- typing;
- tests;
- RAW/SHA preservation;
- evidence paths;
- compatibility;
- CI provenance.

Green CI alone is not approval to merge.

Never self-authorize:
- public contract changes;
- scope expansion;
- policy/severity changes;
- Cisco execution;
- merge.

Human Merge Gate remains explicit.

---

## Agents / DevTools boundary

Agents/DevTools automate software development and Git/GitHub workflow. They are not part of the productive Cisco Assessment runtime.

External generative workers, including Codex or any future replacement, must remain behind project-owned contracts/adapters.

Treat generative output as an untrusted proposal until project validation succeeds.

Repository/GitHub mutations require:
- explicit authorization;
- minimum privilege;
- exact repository binding;
- base/head SHA binding when applicable;
- freshness revalidation when required by the control-plane contract.

PR Review, Implementation, CI, Draft PR, and Ready-for-Review do not grant merge authority.

Persist critical workflow state in Git/GitHub, contracts, journals, tests, or repository documentation rather than only in conversation context.

---

## Testing and quality

The repository currently targets Python 3.11+ and keeps its dependency/tool configuration in `pyproject.toml`.

Use the repository configuration as the source of truth.

Expected quality checks for relevant changes:

```bash
ruff check .
mypy src/cisco_assessment
pytest
python -m build
```

Run the smallest relevant test set during iteration, then the required broader checks before proposing integration.

For reproducible bugs, prefer:

real/sanitized RAW fixture
    + regression test
    + minimal fix

Do not globally relax strict typing or linting to accommodate one dependency or feature.

Avoid unrelated refactors while fixing a bug or implementing a scoped feature.

---

## Stable contracts

Treat these as stable public contracts where applicable:
- `CommandId`;
- `ParserId`;
- `NormalizedModelId`;
- `RuleId`;
- `AssessmentPlanId`;
- public normalized field paths.

For persisted or externally consumed Agents/DevTools artifacts, also treat as stable where applicable:
- `AgentId`;
- `ControlPlaneId`;
- `OrchestratorId`;
- schema versions;
- authorization/evidence contracts;
- journal/checkpoint schemas.

Breaking changes must be explicit.

---

## Working with files and fixtures

Use `pathlib` for filesystem paths in Python unless an existing contract requires otherwise.

Preserve:
- real fixture bytes;
- SHA-256;
- line ordering;
- ordinals;
- public field paths;
- evidence ranges.

If a fixture must change because the upstream observed evidence truly changed, treat that as an explicit evidence/contract change and explain it. Never normalize or rewrite a real fixture silently.

---

## Scope discipline

For every task distinguish:

- authorized components;
- prohibited components;
- contracts preserved;
- contracts intentionally changed;
- required evidence;
- acceptance criteria.

If implementation requires touching a prohibited layer or expanding scope, stop and request authorization rather than making the change opportunistically.

Send unrelated ideas to Backlog instead of implementing them inside the current task.

---

## Handoffs and continuity

At the end of a significant task, produce a checkpoint containing:

- STATUS;
- Implemented;
- Contracts changed;
- Tests;
- Components affected;
- Invariants;
- Pending;
- Next recommended chat/action.

A handoff is a checkpoint, not the ultimate source of truth.

When resuming work:
1. read the handoff;
2. inspect current Git/GitHub state;
3. verify persisted contracts and relevant tests;
4. report meaningful drift before continuing.

---

## Repository navigation

Important top-level areas currently include:

- `src/cisco_assessment/assessment/`
- `src/cisco_assessment/catalog/`
- `src/cisco_assessment/collector/`
- `src/cisco_assessment/devtools/`
- `src/cisco_assessment/inventory/`
- `src/cisco_assessment/models/`
- `src/cisco_assessment/parsers/`
- `src/cisco_assessment/raw/`
- `src/cisco_assessment/reporting/`
- `src/cisco_assessment/runner/`
- `tests/`
- `.github/`
- `pyproject.toml`

Do not infer component ownership only from a filename when an existing project contract/classifier defines it more precisely.

---

## Final rule

If there is a conflict between speed and project invariants, preserve the invariants.

If evidence is insufficient, do not invent it.

If authorization is insufficient, do not broaden it.

If a safe deterministic implementation cannot be demonstrated, stop with a precise blocker and the evidence needed to continue.
