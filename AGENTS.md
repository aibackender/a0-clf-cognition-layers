# AGENTS

## 1. Core Principle: Documentation is Runtime

Documentation in this repository is not optional.
Every `AGENTS.md` file defines binding behavior contracts for agents and contributors.

If documentation is outdated or incorrect:
- agent behavior will drift
- architecture will degrade
- incorrect changes will propagate

Rule: any code change must update the relevant `AGENTS.md` in the same session.

---

## 2. Documentation Hierarchy

This repository follows a strict documentation ownership model.

### Levels

- Level 0: `/AGENTS.md`
  - Global rules
  - Architecture boundaries
  - Documentation policy
- Level 1: domain docs
  - `/clf/AGENTS.md`
  - `/extensions/AGENTS.md`
  - `/helpers/AGENTS.md`
  - `/webui/AGENTS.md`
- Level 2: module docs
  - Concrete implementation rules
  - File ownership
  - Local behavior contracts

### Rules

- The closer the doc is to the code, the more specific it must be.
- The higher the doc, the more stable and abstract it must be.
- Never duplicate contracts across levels.
- Always update the closest owning document.

---

## 3. Repository Purpose

### Plugin: `a0-clf-cognition-layers`

Provides cognitive control layers for Agent Zero:

- verification
- pattern detection
- context control
- self-correction
- observability
- safe persistence

This is a plugin implementation of CLF concepts.

---

## 4. Ownership Model

- Primary maintainers: AI agents
- Human role: validation, correction, boundary enforcement

Agents are expected to:
- follow contracts defined in `AGENTS.md`
- avoid modifying architecture outside their scope
- prioritize stability over novelty

---

## 5. Architecture Overview

### Core System (`/clf/`)

Key components:

- `CognitionAdapter` -> integration with Agent Zero
- `CognitionOrchestrator` -> controls cognitive flow
- `EventBus` -> internal communication layer
- `VerificationGuardian` -> safety and validation layer
- `PatternDetector` -> behavioral pattern recognition
- `PatternPersistenceCore` -> pattern selection and persistence orchestration
- `ContextManager` -> context lifecycle control
- `SelfCorrectionTrigger` -> error recovery activation

### Helpers (`/helpers/`)

Shared runtime infrastructure:

- config resolution and normalization
- persistence and state integrity
- telemetry formatting and redaction
- compatibility helpers and schemas

### Extensions (`/extensions/`)

- Python lifecycle hooks
- extension bridge code for Agent Zero integration

### WebUI (`/webui/`)

- top-level configuration and status pages
- UI-side normalization and presentation logic for plugin settings

### API (`/api/`)

- status
- profiles
- events
- patterns
- defaults and configuration reads

### Configuration And State Ownership

- `plugin.yaml` -> plugin definition and plugin release metadata
- `default_config.yaml` -> default runtime behavior
  - verification default lists may intentionally be empty and must not be repopulated unless the default policy changes
- `helpers/policy.py` -> config resolution and normalization
- `helpers/state.py` -> plugin-local persistence ownership

---

## 6. Contract Boundaries

### README vs AGENTS

- `README.md` -> public-facing product description
- `AGENTS.md` -> internal implementation contracts

Rule:
do not move implementation rules into README.

### Versioning And Compatibility

- `plugin.yaml` owns the plugin/package version.
- CLF `spec_version` is a compatibility contract and is not the same as the plugin release number.
- Version-only changes do not justify broad doc churn beyond the ownership note above.

### Domain Ownership

- `/clf/AGENTS.md` owns core runtime contracts.
- `/helpers/AGENTS.md` owns config, persistence, telemetry, and compatibility helper contracts.
- `/extensions/AGENTS.md` owns hook and extension bridge contracts.
- `/webui/AGENTS.md` owns top-level page behavior and UI-side config hydration contracts.

---

## 7. Development Rules

### Non-negotiable

- update docs with every change
- respect module ownership
- do not introduce cross-layer coupling
- prefer minimal, controlled changes

### Architecture Rule

- prefer frontend or extension-layer solutions when they preserve behavior safely
- backend changes are exceptional
- only modify backend for:
  - security
  - integrity
  - multi-user isolation
  - runtime stability
  - state integrity
  - observability correctness

---

## 8. Autonomous Behavior Expectations

Agents operating on this repo should:

- validate changes before applying them
- maintain consistency with existing patterns
- avoid speculative refactors
- log meaningful actions
- preserve compatibility for persisted config and state shapes

### Required Capabilities

- testing
- documentation updates
- monitoring awareness
- safe self-correction

---

## 9. Workflows

### Development

1. Modify code.
2. Update the closest owning `AGENTS.md`.
3. Validate behavior.
4. Run tests or checks appropriate to the change.
5. Commit.

### Maintenance

- monitor logs and system behavior
- update pattern detection rules safely
- validate persistence and state integrity
- keep observability behavior aligned with runtime semantics
- improve correction mechanisms safely

---

## 10. Documentation System Rules

Each `AGENTS.md` should include:

- purpose
- ownership
- contracts
- boundaries
- development guidance

### Anti-patterns

- duplicated rules across files
- mixing philosophy with contracts
- outdated documentation
- vague responsibilities

---

## 11. Ownership Map

- `/README.md` -> product entry point
- `/AGENTS.md` -> global contract
- `/clf/AGENTS.md` -> core cognition system
- `/extensions/AGENTS.md` -> integration layer
- `/helpers/AGENTS.md` -> config, persistence, telemetry, and compatibility helpers
- `/webui/AGENTS.md` -> top-level plugin UI pages
