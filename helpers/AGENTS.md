# Helpers Contracts

## Purpose

The `helpers/` directory owns shared runtime infrastructure for configuration, persistence, telemetry, compatibility, and schema-backed normalization.

### Ownership

- Primary owner: AI agents
- Scope: helper-layer contracts that multiple runtime surfaces depend on

---

## Config Resolution Contracts

- `helpers/policy.py` owns config resolution and normalization.
- Canonical resolution order is:
  1. defaults from `default_config.yaml`
  2. persisted runtime overrides from the host
  3. legacy migration
  4. normalization and fallback filling
- Supported persisted shapes include:
  - direct section objects
  - dotted keys
  - serialized scalar values
  - nested `config` shells from saved UI payloads
- `plugin.profile` is canonical.
- `plugin.mode` is legacy input only and must be migrated away during normalization.
- Bounded-recovery defaults and observability defaults are normalized centrally here.

---

## Persistence Contracts

- `helpers/state.py` owns plugin-local persistence behavior.
- State is intentionally split:
  - `patterns.json` stores patterns
  - `telemetry_rollup.json` stores rollup counters and recent decisions/corrections
  - `state.json` is maintained as a compatibility rollup mirror
  - checkpoints, events, verification cache, profile status, and config each keep their own files
- Composite reads go through `load_state()`.
- Pattern reads and writes must go through `load_patterns()` and `save_patterns()` or higher-level helper APIs built on top of them.
- Decision and correction rollup updates must go through `load_rollup()`, `save_rollup()`, or the dedicated helper mutators such as `add_decision()`, `add_correction()`, and `save_checkpoint()`.
- Helper code must preserve compatibility for existing persisted state when adding new normalization behavior.

---

## Telemetry And Status Contracts

- Telemetry helpers must redact secrets before persistence or presentation.
- Telemetry output must respect:
  - `observability.log_level`
  - `observability.log_decisions`
  - `observability.log_rejections`
- Status summaries must reflect the rollup/pattern split instead of assuming a single monolithic state payload.

---

## Boundaries

- `helpers/` owns shared normalization and persistence behavior, not CLF orchestration decisions.
- Core runtime code should call helper APIs rather than reimplement config parsing, payload migration, or file ownership rules.
- Top-level UI code may mirror helper semantics for user experience, but backend normalization authority stays in `helpers/`.

---

## Development Guidance

- Prefer extending existing helper seams before introducing new state or config entrypoints.
- Preserve lock-protected writes and compatibility mirroring when changing persistence behavior.
- When helper behavior changes user-visible semantics, update the owning `webui/` or `clf/` docs in the same session.
