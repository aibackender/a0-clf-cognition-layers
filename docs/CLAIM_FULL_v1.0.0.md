# CLF Full 1.0.0 Claim

This repository publishes a plugin-only CLF `v1.0.0` **Full** claim path alongside the existing Core and Standard claim paths.

## Target

- Spec version: `1.0.0`
- Target profile: `full`
- Certification fixture: `usr/plugins/cognition_layers/certification/full_claim_config.yaml`
- Artifact owner: `usr/plugins/cognition_layers`

## Claimed Surfaces

- `CognitionAdapter`
- `EventBus`
- `CognitionOrchestrator`
- `VerificationGuardian`
- `PatternDetector`
- `PatternPersistenceCore`
- `ContextManager`
- `SelfCorrectionTrigger`

## Explicit NOT_SUPPORTED

- Subordinate execution through the host runtime
- Shared/global recovery state or shared/global checkpoint storage
- `L3_SHARED` pattern persistence
- Discovery mode and external recovery coordinators

## Agent Zero `usr` Recovery Contract

- Recovery state is stored only in Agent Zero `usr` JSON checkpoints and agent-local runtime memory.
- `ContextManager` restores by `context_id`, then compatible scope, then latest compatible checkpoint.
- `SelfCorrectionTrigger` certifies both `advisory` and `auto` modes, with the Full certification fixture using `auto`.
- Automatic recovery is limited to local guidance and local `break_loop` continuation; no host-owned retries or subordinate execution are claimed.

## Sample Checkpoint Snapshot

```json
{
  "id": "checkpoint-demo-full",
  "context_id": "ctx-full-demo",
  "scope": { "label": "project:demo", "context_id": "ctx-full-demo" },
  "profile_status": { "effective_profile": "full" },
  "recent_verification_results": [
    { "action": "block", "reason": "matched blocked shell pattern", "tool_name": "code_execution_tool" }
  ],
  "recent_patterns": [
    { "id": "pattern-demo", "type": "error", "pattern": "Retry with a narrower validated request after a failure." }
  ],
  "recent_correction_decisions": [
    { "state": "triggered", "trigger": "validation_failure", "guidance": "Retry with a strictly valid tool request shape and keep arguments minimal and explicit." }
  ],
  "correction_runtime_state": {
    "attempt_counter": { "validation_failure": 1 },
    "recent_failures": { "code_execution_tool:validation_failure": 1 },
    "pending_guidance": [
      { "state": "triggered", "trigger": "validation_failure", "guidance": "Retry with a strictly valid tool request shape and keep arguments minimal and explicit." }
    ],
    "last_history_trigger": null,
    "last_correction_state": "triggered",
    "last_decision": { "state": "triggered", "trigger": "validation_failure" },
    "mode": "auto",
    "schema_version": "1.0.0"
  },
  "prompt_budget": { "max_chars": 900, "verbosity": "standard" },
  "metadata": { "profile": "full" },
  "schema_version": "1.0.0",
  "spec_version": "1.0.0",
  "created_at": "2026-04-19T00:00:00+00:00",
  "updated_at": "2026-04-19T00:00:00+00:00"
}
```

## Required Suites

- All Core-required suites
- All Standard-required suites
- `checkpoint_restore_and_schema_validation`
- `prompt_compaction_and_budgeting`
- `retry_state_persistence_across_checkpoint_restore`
- `self_correction_state_machine`
- `self_correction_modes_and_history_deduplication`
- `verification_pattern_context_integration`

## Host Constraints

- Full readiness still requires Core and Standard fixtures and suites to remain green.
- Checkpointing and recovery are Agent Zero `usr` local only.
- No claim is made for subordinate execution, shared/global recovery state, or host-managed retries.
