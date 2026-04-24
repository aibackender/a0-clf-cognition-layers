# WebUI Contracts

## Purpose

The `webui/` directory contains top-level plugin UI pages and page-local logic for configuration and status presentation.

### Ownership

- Primary owner: AI agents
- Scope: top-level UI behavior under `webui/`

---

## Configuration Page Contracts

- `config.html` treats the host-provided global `config` object as the source of truth.
- The page normalizes that object in place instead of maintaining a separate shadow configuration model.
- The page must fetch defaults from `api/get_defaults`, merge them with persisted config, unwrap nested `config` payloads, and migrate legacy `plugin.mode` behavior to `plugin.profile`.
- Supported profile behavior:
  - `core`, `standard`, and `full` auto-fill their expected surfaces
  - manual surface overrides force `custom`
  - `full` defaults `layers.self_correction.mode` to `auto` unless the user already set an explicit value

---

## UI Messaging Contracts

- Help text must stay aligned with backend semantics for:
  - verification mode
  - bounded recovery
  - observability
  - claim-conformance messaging
- UI defaults and labels may simplify presentation, but they must not contradict helper-owned normalization or runtime semantics.

---

## Boundaries

- `/webui/` owns top-level page behavior.
- `/extensions/webui` owns extension bridge and handler behavior, not page-level config hydration.
- Backend config normalization authority remains in `helpers/`; UI-side normalization exists to keep persisted payloads and user interactions stable.

---

## Development Guidance

- Preserve the current page contract with the host-provided `config` object.
- Avoid introducing an alternate persistence shape from the UI unless `helpers/policy.py` is updated in the same session.
- When changing page text or controls for runtime behavior, verify that the underlying backend contract still matches the explanation shown to the user.
