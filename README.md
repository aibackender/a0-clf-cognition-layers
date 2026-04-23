# Cognition Layers Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Zero Plugin](https://img.shields.io/badge/Agent%20Zero-Plugin-blue)](https://github.com/frdel/agent-zero)

**Agent Zero plugin** for cognitive behavior and pattern detection using CLF-style runtime.

This package keeps Agent Zero hooks thin and moves cognitive behavior into `clf/` surfaces, including:
- `CognitionAdapter`
- `EventBus`
- `CognitionOrchestrator`
- `VerificationGuardian`
- `PatternDetector`
- `PatternPersistenceCore`
- `ContextManager`
- `SelfCorrectionTrigger`

The plugin is designed around CLF v1.0.0 profile semantics.

---

## Installation

To install the plugin in your Agent Zero environment:

```bash
git clone https://github.com/aibackender/a0-clf-cognition-layers.git
cd a0-clf-cognition-layers
cp -r . /path/to/agent-zero/usr/plugins/cognition_layers
```

---

## Usage

The plugin can be configured via `default_config.yaml` or Agent Zero plugin settings.

### Important Notice

The plugin **may increment calls for the main model**, as it is used for internal CLF plugin discoveries (patterns, self-correction).

---

## Configuration

Configure the plugin using `default_config.yaml` or Agent Zero plugin settings:

```yaml
plugin:
  enabled: true
  profile: full   # core | standard | full | custom
  spec_version: 1.0.0
  claim_conformance: false

surfaces:
  cognition_adapter: true
  event_bus: true
  cognition_orchestrator: true
  verification_guardian: true
  pattern_detector: true
  pattern_persistence_core: true
  context_manager: true
  self_correction_trigger: true
```

---

## Features

- **Core Surfaces**: `CognitionOrchestrator`, `VerificationGuardian`, `EventBus`, `CognitionAdapter`
- **Standard Surfaces**: Core plus `PatternDetector` and `PatternPersistenceCore`
- **Full Surfaces**: Standard plus `ContextManager` and `SelfCorrectionTrigger`
- **Profile Resolution**: Explicit profiles (Core, Standard, Full) and custom user-controlled surface toggles
- **Runtime State**: Persistent state stored in `state/`
- **Verification Guardian**: Separates shell analysis, file destination analysis, content payload analysis, and credential likelihood analysis

---

## Current Claim Scope

- **Public claim paths**: CLF `v1.0.0` Core, Standard, and Full
- **Core certification artifact**: `docs/CLAIM_CORE_v1.0.0.md`
- **Core certification fixture config**: `certification/core_claim_config.yaml`
- **Standard certification artifact**: `docs/CLAIM_STANDARD_v1.0.0.md`
- **Standard certification fixture config**: `certification/standard_claim_config.yaml`
- **Full certification artifact**: `docs/CLAIM_FULL_v1.0.0.md`
- **Full certification fixture config**: `certification/full_claim_config.yaml`

---

## APIs

- `GET/POST api/get_status`
- `GET/POST api/get_profile`
- `GET/POST api/get_defaults`
- `GET/POST api/get_events`
- `GET/POST api/get_patterns`
- `POST api/clear_patterns`

---

## Runtime State

Plugin-owned state is stored inside the plugin folder so learned patterns and telemetry travel with the plugin:

```
state/
├── config.json
├── profile_status.json
├── patterns.json
├── events.jsonl
├── checkpoints.json
├── verification_cache.json
└── telemetry_rollup.json
```

---

## Hook Architecture

Files under `extensions/python/...` are wrappers only. Each wrapper:
1. Creates a runtime
2. Builds an adapter context
3. Calls one runtime entry point
4. Applies returned effects

The hooks do not directly verify tools, mutate pattern memory, or run correction logic anymore.

---

## Ecosystem

- [Agent Zero](https://github.com/agent0ai/agent-zero) — Core framework for Agent Zero plugins.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on contributing to this project.

---

## License

MIT — see [LICENSE](LICENSE)

---

## AI-Driven Development

a0-clf-cognition-layers is primarily developed by AI agents, with human oversight and validation.

Agent behavior and changes are guided by the AGENTS.md contract hierarchy, which defines architecture, ownership, and implementation rules across the repository.
