# Agent System Documentation

Status: repository reference documentation for Agents / DevTools.

## Purpose

This directory is the persistent, repository-owned reference for the software-development agent system used to evolve the Cisco Switch Assessment Framework.

It documents the development/control plane only. It does not grant Cisco execution authority and does not change the productive Assessment architecture.

Productive Assessment remains:

```text
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
```

Agents / DevTools remain outside that runtime.

## Documents

- `ARCHITECTURE.md` — components, boundaries, data flow, orchestration states and ownership.
- `SECURITY_MODEL.md` — trust boundaries, credentials, authorization, SHA/freshness checks and fail-closed behavior.
- `CONTRACTS.md` — stable Agent/ControlPlane/Orchestrator IDs and schema/version expectations currently present in code.
- `DELIVERY_WORKFLOW.md` — feature-delivery lifecycle from human intent to Human Merge Gate.
- `STATUS.md` — current operational checkpoint. This file is expected to change as the system evolves.

## Source of truth

Use this priority when reconstructing current state:

1. `main` code and persisted contracts;
2. tests and CI evidence;
3. GitHub PR/commit history;
4. this directory for architecture and operational checkpoints;
5. chat handoffs as convenience checkpoints only.

If a document conflicts with current code or an exact persisted contract, code/contracts win and the documentation should be corrected.

## Current implementation locations

Primary code lives under:

- `src/cisco_assessment/devtools/pr_review/`
- `src/cisco_assessment/devtools/implementation/`
- `src/cisco_assessment/devtools/ready_for_review.py`
- `src/cisco_assessment/devtools/ready_for_review_control_plane.py`
- `src/cisco_assessment/devtools/human_merge_gate.py`
- `src/cisco_assessment/devtools/human_merge_control_plane.py`

Repository-level operating instructions live in `/AGENTS.md`.

## Update discipline

Update architecture/security/contracts documentation when a public or persisted Agent/DevTools contract changes.

Update `STATUS.md` when a meaningful capability is integrated, a security/governance gap changes, or the recommended next step changes.

Do not copy every CI log, pilot transcript, temporary SHA, or terminal output into these documents. Operational evidence belongs in GitHub, CI, tests, fixtures, journals, or issues.

## Authority boundary

Documentation is descriptive, not authorizing.

It does not by itself authorize:

- repository mutation;
- GitHub mutation;
- scope expansion;
- policy/severity changes;
- Cisco SSH/CLI execution;
- Ready-for-Review;
- merge.

Human approval and the applicable project-owned control-plane contract remain required.