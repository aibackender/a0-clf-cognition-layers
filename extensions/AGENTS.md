# Extensions Contracts

## Purpose

The `extensions/` directory contains Agent Zero integration hooks and extension bridge code for the plugin runtime.

### Ownership

- Primary owner: AI agents
- Scope: hook entrypoints and extension-specific bridge behavior under `extensions/`

---

## Extensions Overview

### Python Hooks

- `extensions/python` hooks remain thin wrappers.
- Each hook should:
  - bootstrap or access runtime state
  - build adapter context
  - invoke one runtime entry point
  - apply returned effects
- Hooks do not own verification policy, pattern persistence rules, recovery policy, or raw state-file handling.

### WebUI Extension Bridge

- `extensions/webui` owns only extension bridge and handler behavior under `extensions/`.
- It does not own top-level page behavior in `/webui/`.

---

## Boundaries

- `extensions/` does not own top-level `webui/` configuration page behavior.
- `extensions/` does not own persisted config-shape normalization.
- If a change primarily affects UI hydration, defaults merging, or page-level help text, update `/webui/AGENTS.md` instead.
- If a change primarily affects runtime semantics, update the owning `clf/` or `helpers/` contracts instead of expanding hook logic.

---

## Development Guidance

- Keep hooks intentionally small and predictable.
- Prefer passing normalized data into the runtime rather than duplicating normalization inside hooks.
- Preserve hook stage boundaries so Agent Zero lifecycle behavior remains easy to reason about and test.
