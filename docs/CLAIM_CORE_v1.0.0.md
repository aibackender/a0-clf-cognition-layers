# CLF Core 1.0.0 Conformance Claim Artifact

## Target

- Target profile: `core`
- Spec version: `1.0.0`
- Claim scope: `CognitionOrchestrator`, `VerificationGuardian`, `EventBus`, `CognitionAdapter`
- Certification fixture: `usr/plugins/cognition_layers/certification/core_claim_config.yaml`

## Implemented Surfaces

- `CognitionOrchestrator`
- `VerificationGuardian`
- `EventBus`
- `CognitionAdapter`

## Unsupported Behaviors

- `subordinates: NOT_SUPPORTED`
- `global/shared pattern persistence: NOT_SUPPORTED`
- `external invalidation sources: NOT_SUPPORTED`

## Sample AgentContext Snapshot

```json
{
  "schema_version": "1.0.0",
  "agent_id": "core-agent",
  "context_id": "ctx-claim-sample",
  "scope": {
    "label": "global",
    "project": null,
    "agent_profile": null,
    "context_id": null
  },
  "trigger": "tool_before",
  "tool": {
    "tool_name": "code_execution_tool",
    "tool_args": {
      "command": "echo safe"
    },
    "call_id": null,
    "raw": {}
  },
  "profile_status": {
    "selected_profile": "core",
    "effective_profile": "core",
    "spec_version": "1.0.0",
    "claim_conformance": true,
    "conformant": true,
    "status": "conformant",
    "active_surfaces": {
      "cognition_adapter": true,
      "event_bus": true,
      "cognition_orchestrator": true,
      "verification_guardian": true,
      "pattern_detector": false,
      "pattern_persistence_core": false,
      "context_manager": false,
      "self_correction_trigger": false
    },
    "expected_surfaces": {
      "cognition_adapter": true,
      "event_bus": true,
      "cognition_orchestrator": true,
      "verification_guardian": true,
      "pattern_detector": false,
      "pattern_persistence_core": false,
      "context_manager": false,
      "self_correction_trigger": false
    },
    "warnings": [],
    "unsupported_behaviors": [
      "subordinates: NOT_SUPPORTED by this plugin runtime facade",
      "global/shared pattern persistence: NOT_SUPPORTED; Agent Zero usr-local JSON only",
      "external invalidation sources: NOT_SUPPORTED",
      "pattern_detector: NOT_SUPPORTED in active profile",
      "pattern_persistence_core: NOT_SUPPORTED in active profile",
      "context_manager: NOT_SUPPORTED in active profile",
      "self_correction_trigger: NOT_SUPPORTED in active profile"
    ]
  },
  "host_capabilities": {
    "supported": {
      "warning_channel": false,
      "agent_data": false,
      "prompt_injection": true,
      "context_snapshot": true,
      "repairable_exception": true
    },
    "unsupported": [
      {
        "capability": "subordinates",
        "reason": "Agent Zero subordinate execution is not implemented in this plugin-only adapter.",
        "status": "NOT_SUPPORTED",
        "supported": false,
        "host_behavior": "subordinate_execution"
      }
    ],
    "errors": []
  },
  "prompt_state": {
    "user_message": "check",
    "history_output": [
      "hello"
    ],
    "system_count": 0
  },
  "snapshot": {
    "last_verification": null,
    "last_correction_state": null,
    "pending_guidance_count": 0
  },
  "last_result_present": false,
  "response_summary": null
}
```

## Required Suite Results

| Suite | Result | Evidence |
|------|--------|----------|
| Orchestrator phase contract | Passing | `tests/conformance/core/test_orchestrator_contract.py` |
| Planner determinism and dependency validation | Passing | `tests/conformance/core/test_orchestrator_contract.py` |
| Retry, timeout, cancellation, and idempotency | Passing | `tests/conformance/core/test_orchestrator_contract.py` |
| Event bus delivery, ordering, and back-pressure | Passing | `tests/conformance/core/test_event_bus.py` |
| Adapter compatibility | Passing | `tests/conformance/core/test_adapter_contract.py` |
| Verification cache and invalidation | Passing | `tests/conformance/core/test_verification_cache.py` |
| Schema/version compatibility | Passing | `tests/conformance/core/test_schema_contract.py` |

## Prompt Injection and Subordinate Contract Results

- Prompt injection is supported through `loop.system.append(...)` and the adapter fallback queue.
- Subordinate execution returns explicit `NOT_SUPPORTED` from the adapter contract rather than silently succeeding.

## Known Host Constraints

- This certification path is plugin-only and does not claim host-managed subordinate execution.
- Standard and Full surfaces remain implemented in the repo but are outside this `core` public claim.
- Experimental CLF features remain excluded from the `1.0.0` claim.

## Regeneration Command

```bash
bash scripts/run_full_conformance.sh
```
