# AGENTS

## 1. Core Principle: Documentation is Runtime

Documentation in this repository is **not optional**.  
Every `AGENTS.md` file defines **binding behavior contracts** for agents and contributors.

If documentation is outdated or incorrect:
- agent behavior will drift
- architecture will degrade
- incorrect changes will propagate

**Rule:** Any code change MUST update the relevant `AGENTS.md` in the same session.

---

## 2. Documentation Hierarchy

This repository follows a strict documentation ownership model:

### Levels

- **Level 0 — `/AGENTS.md` (this file)**
  - Global rules
  - Architecture boundaries
  - Documentation policy

- **Level 1 — Domain Docs (`/clf/AGENTS.md`, `/extensions/AGENTS.md`)**
  - Subsystem architecture
  - Stable interfaces and contracts

- **Level 2 — Module Docs**
  - Concrete implementation rules
  - File ownership
  - Local behavior contracts

### Rules

- The **closer the doc is to the code**, the more specific it must be
- The **higher the doc**, the more stable and abstract it must be
- **Never duplicate contracts across levels**
- **Always update the closest owning document**

---

## 3. Repository Purpose

### Plugin: `a0-clf-cognition-layers`

Provides **cognitive control layers** for Agent Zero:

- verification
- pattern detection
- context control
- self-correction

This is a **plugin implementation of CLF concepts**.

---

## 4. Ownership Model

- **Primary maintainers:** AI agents (execution + iteration)
- **Human role:** validation, correction, boundary enforcement

Agents are expected to:
- follow contracts defined in `AGENTS.md`
- avoid modifying architecture outside their scope
- prioritize stability over novelty

---

## 5. Architecture Overview

### Core System (`/clf/`)

Key components:

- `CognitionAdapter` → Integration with Agent Zero
- `CognitionOrchestrator` → Controls cognitive flow
- `EventBus` → Internal communication layer
- `VerificationGuardian` → Safety + validation layer
- `PatternDetector` → Behavioral pattern recognition
- `PatternPersistenceCore` → Pattern storage
- `ContextManager` → Context lifecycle control
- `SelfCorrectionTrigger` → Error recovery activation

### Extensions (`/extensions/`)

- Python lifecycle hooks
- WebUI integration layer

### API (`/api/`)

- Status
- Profiles
- Events
- Patterns
- Configuration

### Configuration

- `plugin.yaml` → plugin definition
- `default_config.yaml` → runtime behavior

---

## 6. Contract Boundaries

### README vs AGENTS

- `README.md` → public-facing (what this is)
- `AGENTS.md` → internal contract (how this behaves)

**Rule:**  
Do not move implementation rules into README.

---

## 7. Development Rules

### Non-negotiable

- Update docs with every change
- Respect module ownership
- Do not introduce cross-layer coupling
- Prefer minimal, controlled changes

### Architecture Rule

- Prefer frontend or extension-layer solutions
- Backend changes are **exceptional**
- Only modify backend for:
  - security
  - integrity
  - multi-user isolation
  - runtime stability

---

## 8. Autonomous Behavior Expectations

Agents operating on this repo should:

- validate changes before applying them
- maintain consistency with existing patterns
- avoid speculative refactors
- log meaningful actions

### Required Capabilities

- Testing
- Documentation updates
- Monitoring awareness
- Safe self-correction

---

## 9. Workflows

### Development

1. Modify code
2. Update relevant `AGENTS.md`
3. Validate behavior
4. Run tests
5. Commit

### Maintenance

- Monitor logs and system behavior
- Update pattern detection rules
- Validate persistence and state integrity
- Improve correction mechanisms safely

---

## 10. Documentation System Rules

Each `AGENTS.md` should include:

- Purpose
- Ownership
- Contracts
- Boundaries
- Development guidance

### Anti-patterns

- Duplicated rules across files
- Mixing philosophy with contracts
- Outdated documentation
- Vague responsibilities

---

## 11. Ownership Map

- `/README.md` → Product entry point
- `/AGENTS.md` → Global contract
- `/clf/AGENTS.md` → Core cognition system
- `/extensions/AGENTS.md` → Integration layer
