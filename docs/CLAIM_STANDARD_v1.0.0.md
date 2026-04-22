# CLF Standard 1.0.0 Claim

This repository publishes a plugin-only CLF `v1.0.0` **Standard** claim path in addition to the existing Core claim path.

## Target

- Spec version: `1.0.0`
- Target profile: `standard`
- Certification fixture: `usr/plugins/cognition_layers/certification/standard_claim_config.yaml`
- Artifact owner: `usr/plugins/cognition_layers`

## Claimed Surfaces

- `CognitionAdapter`
- `EventBus`
- `CognitionOrchestrator`
- `VerificationGuardian`
- `PatternDetector`
- `PatternPersistenceCore`

## Explicit NOT_SUPPORTED

- Subordinate execution through the host runtime
- `L3_SHARED` shared/global pattern persistence
- Discovery mode and external/global pattern sync
- Full-profile `ContextManager` and `SelfCorrectionTrigger` claim semantics in this milestone

## Sample Normalized Pattern

```json
{
  "id": "pattern-demo-standard",
  "type": "error",
  "pattern": "If code_execution_tool returns a similar failure, pause, re-check assumptions, then retry with a narrower plan.",
  "confidence": 0.83,
  "firstObserved": "2026-04-19T00:00:00+00:00",
  "lastObserved": "2026-04-19T00:00:00+00:00",
  "evidence": [
    {
      "observation": "validation failed because tool_args were invalid",
      "source": "tool_result",
      "observedAt": "2026-04-19T00:00:00+00:00",
      "toolName": "code_execution_tool",
      "scope": { "label": "global", "context_id": null },
      "metadata": { "response_kind": "error" }
    }
  ],
  "mitigation": "Do not repeat the identical failing action without changing the plan or tool inputs.",
  "status": "promoted",
  "metadata": {
    "title": "Tool After",
    "tags": ["code_execution_tool", "invalid", "validation"],
    "scope": { "label": "global", "context_id": null },
    "trigger": "tool_after",
    "source_phase": "tool_after",
    "tool_name": "code_execution_tool",
    "context_id": null
  },
  "storageLayer": "L2_AGENT",
  "schema_version": "3.0",
  "spec_version": "1.0.0"
}
```

## Required Suites

- Core-required suites
- `pattern_detector_contract`
- `pattern_validation_and_normalized_storage`
- `pattern_filtering_and_lookup`
- `pattern_lifecycle_and_storage_layers`
- `legacy_pattern_migration`
- `prompt_hint_retrieval_from_standard_patterns`

## Prompt Injection Result

- Prompt hints are drawn only from normalized patterns in lifecycle states `promoted`, `verified`, or `active`.
- `candidate`, `deprecated`, `archived`, and `rejected` patterns are excluded from prompt hints.

## Host Constraints

- Persistence is plugin-managed JSON in the host cache directory, outside the shipped plugin artifact.
- `L1_SESSION` and `L2_AGENT` are implemented locally in the plugin.
- `L3_SHARED` is surfaced as an explicit structured `NOT_SUPPORTED` result.
- Standard claim readiness still requires the Core claim fixture and suites to remain green.
