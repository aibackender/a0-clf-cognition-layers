from __future__ import annotations

from pathlib import Path
from typing import Any
from usr.plugins.cognition_layers.helpers.policy import bounded_recovery_enabled


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CORE_REQUIRED_SUITES = (
    "orchestrator_phase_contract",
    "planner_determinism_and_dependency_validation",
    "retry_timeout_cancellation_and_idempotency",
    "event_bus_delivery_ordering_and_back_pressure",
    "adapter_compatibility",
    "verification_cache_and_invalidation",
    "schema_version_compatibility",
)
STANDARD_REQUIRED_SUITES = (
    "pattern_detector_contract",
    "pattern_validation_and_normalized_storage",
    "pattern_filtering_and_lookup",
    "pattern_lifecycle_and_storage_layers",
    "legacy_pattern_migration",
    "prompt_hint_retrieval_from_standard_patterns",
)
FULL_REQUIRED_SUITES = (
    "checkpoint_restore_and_schema_validation",
    "prompt_compaction_and_budgeting",
    "retry_state_persistence_across_checkpoint_restore",
    "self_correction_state_machine",
    "self_correction_modes_and_history_deduplication",
    "verification_pattern_context_integration",
)
SUITE_TEST_PATHS = {
    "orchestrator_phase_contract": "tests/conformance/core/test_orchestrator_contract.py",
    "planner_determinism_and_dependency_validation": "tests/conformance/core/test_orchestrator_contract.py",
    "retry_timeout_cancellation_and_idempotency": "tests/conformance/core/test_orchestrator_contract.py",
    "event_bus_delivery_ordering_and_back_pressure": "tests/conformance/core/test_event_bus.py",
    "adapter_compatibility": "tests/conformance/core/test_adapter_contract.py",
    "verification_cache_and_invalidation": "tests/conformance/core/test_verification_cache.py",
    "schema_version_compatibility": "tests/conformance/core/test_schema_contract.py",
    "pattern_detector_contract": "tests/conformance/standard/test_pattern_detector_contract.py",
    "pattern_validation_and_normalized_storage": "tests/conformance/standard/test_pattern_detector_contract.py",
    "pattern_filtering_and_lookup": "tests/conformance/standard/test_pattern_persistence_contract.py",
    "pattern_lifecycle_and_storage_layers": "tests/conformance/standard/test_pattern_persistence_contract.py",
    "legacy_pattern_migration": "tests/conformance/standard/test_pattern_persistence_contract.py",
    "prompt_hint_retrieval_from_standard_patterns": "tests/conformance/standard/test_prompt_hint_contract.py",
    "checkpoint_restore_and_schema_validation": "tests/conformance/full/test_context_manager_contract.py",
    "prompt_compaction_and_budgeting": "tests/conformance/full/test_context_manager_contract.py",
    "retry_state_persistence_across_checkpoint_restore": "tests/conformance/full/test_context_manager_contract.py",
    "self_correction_state_machine": "tests/conformance/full/test_self_correction_contract.py",
    "self_correction_modes_and_history_deduplication": "tests/conformance/full/test_self_correction_contract.py",
    "verification_pattern_context_integration": "tests/conformance/full/test_full_integration_contract.py",
}
CLAIM_MATRIX = {
    "core": {
        "artifact": PLUGIN_ROOT / "CLAIM_CORE_v1.0.0.md",
        "config": PLUGIN_ROOT / "certification" / "core_claim_config.yaml",
        "required_suites": CORE_REQUIRED_SUITES,
    },
    "standard": {
        "artifact": PLUGIN_ROOT / "CLAIM_STANDARD_v1.0.0.md",
        "config": PLUGIN_ROOT / "certification" / "standard_claim_config.yaml",
        "required_suites": CORE_REQUIRED_SUITES + STANDARD_REQUIRED_SUITES,
    },
    "full": {
        "artifact": PLUGIN_ROOT / "CLAIM_FULL_v1.0.0.md",
        "config": PLUGIN_ROOT / "certification" / "full_claim_config.yaml",
        "required_suites": CORE_REQUIRED_SUITES + STANDARD_REQUIRED_SUITES + FULL_REQUIRED_SUITES,
    },
}


def suite_status_for_profile(profile: str) -> dict[str, bool]:
    root = PLUGIN_ROOT.parents[2]
    profile_entry = CLAIM_MATRIX.get(str(profile or "").lower(), {})
    suites = profile_entry.get("required_suites", ()) if isinstance(profile_entry, dict) else ()
    status: dict[str, bool] = {}
    for suite in suites:
        status[str(suite)] = (root / SUITE_TEST_PATHS[str(suite)]).exists()
    return status


def claim_paths() -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    for profile, entry in CLAIM_MATRIX.items():
        suites = suite_status_for_profile(profile)
        artifact = entry["artifact"]
        config = entry["config"]
        catalog[profile] = {
            "target_profile": profile,
            "artifact_path": str(artifact),
            "artifact_present": artifact.exists(),
            "claim_config_path": str(config),
            "claim_config_present": config.exists(),
            "required_suite_status": suites,
            "suite_count": len(suites),
        }
    return catalog


def claim_readiness(
    config: dict[str, Any],
    profile_status: dict[str, Any],
    adapter_capabilities: dict[str, Any],
    verification_cache: dict[str, Any],
) -> dict[str, Any]:
    selected = str(profile_status.get("selected_profile", "full") or "full")
    effective = str(profile_status.get("effective_profile", "full") or "full")
    target = selected if selected in CLAIM_MATRIX else None
    path_entry = CLAIM_MATRIX.get(target or "")
    suites = suite_status_for_profile(target) if target else {}
    unsupported = list(profile_status.get("unsupported_behaviors", []) or [])
    adapter_ready = not bool(adapter_capabilities.get("errors"))
    spec_version = str(config.get("plugin", {}).get("spec_version", "1.0.0") or "1.0.0")
    artifact = path_entry["artifact"] if isinstance(path_entry, dict) else None
    claim_config = path_entry["config"] if isinstance(path_entry, dict) else None
    bounded_override = bounded_recovery_enabled(config)
    ready = bool(
        target
        and spec_version == "1.0.0"
        and selected == effective
        and bool(config.get("plugin", {}).get("claim_conformance", False))
        and all(suites.values())
        and artifact is not None
        and artifact.exists()
        and claim_config is not None
        and claim_config.exists()
        and adapter_ready
        and verification_cache.get("cache_enabled", False)
        and not bounded_override
    )
    return {
        "target_profile": target,
        "selected_profile": selected,
        "effective_profile": effective,
        "spec_version": spec_version,
        "required_suite_status": suites,
        "adapter_ready": adapter_ready,
        "artifact_path": str(artifact) if artifact is not None else None,
        "artifact_present": bool(artifact and artifact.exists()),
        "claim_config_path": str(claim_config) if claim_config is not None else None,
        "claim_config_present": bool(claim_config and claim_config.exists()),
        "unsupported_behaviors": unsupported,
        "verification_cache_enabled": bool(verification_cache.get("cache_enabled", False)),
        "bounded_recovery_override": bounded_override,
        "available_claim_paths": claim_paths(),
        "ready": ready,
    }
