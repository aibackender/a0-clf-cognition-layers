# Cognition Layers Core Contracts

## Purpose

The `clf/` directory contains the core runtime surfaces for the Cognition Layers plugin.
These components orchestrate verification, pattern memory, context recovery, and self-correction inside Agent Zero.

### Ownership

- Primary owner: AI agents
- Scope: core runtime behavior and cross-surface coordination inside `clf/`

---

## Core Components

### CognitionAdapter

- Builds runtime context from host hook inputs.
- Applies runtime effects back to Agent Zero.
- Treats helper-owned config, telemetry, and state APIs as the source of truth.

### EventBus

- Publishes and subscribes to internal runtime events.
- Owns in-memory event coordination, not long-term persistence formats.

### CognitionOrchestrator

- Routes hook triggers through the CLF runtime plan.
- Preserves observability and persistence side effects exposed by helper APIs.
- Must not bypass helper-owned config or state normalization.

### VerificationGuardian

- Verifies tool calls and arguments.
- Analyzes shell commands, file destinations, content payloads, and credential likelihood.
- Relies on normalized config and verification-cache contracts owned by `helpers/`.

### PatternDetector

- Detects and classifies patterns from observations.
- Produces normalized pattern records for helper-managed persistence.

### PatternPersistenceCore

- Retrieves patterns through centralized helper persistence APIs.
- Tracks cooldown context ids when patterns are selected for prompt injection.
- Marks prompt-selected patterns active through helper-managed saves instead of mutating raw files directly.

### ContextManager

- Creates, restores, and summarizes checkpoints.
- Builds checkpoints from rollup decisions and corrections plus separately loaded patterns.
- Must respect effective bounded-recovery settings when choosing restore behavior.

### SelfCorrectionTrigger

- Evaluates failures and builds correction decisions.
- Preserves claim-conformance and bounded-recovery semantics exposed by the config layer.

---

## Integration Boundaries

- Core CLF surfaces must consume helper-owned config and state APIs instead of reading raw files directly.
- `clf/` owns runtime behavior, not persisted config-shape migration or UI payload unwrapping.
- Conformance, claim signaling, and bounded-recovery overrides are runtime contracts and must remain consistent across orchestrator, registry, context, and self-correction flows.

---

## Current Runtime Contracts

- `plugin.profile` is the canonical profile selector.
- `claim_conformance` and bounded-recovery overrides affect effective runtime and conformance reporting and must be preserved.
- Pattern retrieval and checkpoint summaries depend on the split between pattern storage and rollup storage.
- Observability emitted by core surfaces must respect helper-owned telemetry controls rather than inventing local logging policy.

---

## Development Guidance

- Prefer extending helper-owned abstractions when core behavior needs normalized config or persistence access.
- Keep hook-facing behavior stable by changing adapter and orchestrator seams deliberately.
- When changing persistence-sensitive core behavior, update `helpers/AGENTS.md` and `clf/AGENTS.md` together if ownership crosses that boundary.
