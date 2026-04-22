from __future__ import annotations

from typing import Any

from usr.plugins.cognition_layers.clf.self_correction_trigger import SelfCorrectionTrigger, describe_guidance
from usr.plugins.cognition_layers.clf.types import AgentContext, CheckpointRecord, CompactionResult, RestoreResult, new_id
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.helpers.policy import bounded_recovery_settings, bounded_text, effective_bounded_recovery_settings, get_in


class ContextManager:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if isinstance(config, dict) else {}

    def _max_restore_resolution(self, context: AgentContext) -> str:
        return str(effective_bounded_recovery_settings(context.config or self.config).get("max_restore_resolution") or "latest_compatible")

    def checkpoint(self, context: AgentContext) -> dict[str, Any]:
        runtime = SelfCorrectionTrigger(context.config or self.config).runtime_state(context.agent)
        snapshot = state.snapshot()
        record = CheckpointRecord(
            id=new_id("checkpoint"),
            context_id=context.context_id,
            scope=context.scope,
            profile_status=context.profile_status.to_dict() if context.profile_status else {},
            recent_verification_results=snapshot.get("recent_decisions", [])[-10:],
            recent_patterns=snapshot.get("patterns", [])[:10],
            recent_correction_decisions=snapshot.get("recent_corrections", [])[-10:],
            correction_runtime_state=runtime,
            prompt_budget={
                "max_chars": int(get_in(context.config, "prompt_policy.max_injected_chars", 900) or 900),
                "verbosity": get_in(context.config, "prompt_policy.verbosity", "standard"),
            },
            metadata={
                "profile": context.profile_status.effective_profile if context.profile_status else None,
                "latest_restore": context.snapshot.get("last_restore"),
                "latest_compaction": context.snapshot.get("last_compaction"),
            },
        )
        checkpoint = state.save_checkpoint(record.to_dict())
        context.snapshot["last_checkpoint"] = checkpoint
        self._store_agent_state(context, "_cognition_layers_last_checkpoint", checkpoint)
        return checkpoint

    def restore(self, context: AgentContext) -> dict[str, Any]:
        checkpoints = state.load_checkpoints(20)
        result = RestoreResult(restored=False, resolution="none")
        if not checkpoints:
            context.snapshot["last_restore"] = result.to_dict()
            self._store_agent_state(context, "_cognition_layers_last_restore", result.to_dict())
            return result.to_dict()

        selected = None
        resolution = "latest_compatible"
        max_resolution = self._max_restore_resolution(context)
        if context.context_id:
            for checkpoint in reversed(checkpoints):
                if checkpoint.get("context_id") == context.context_id:
                    selected = checkpoint
                    resolution = "context_id"
                    break
        if selected is None and context.scope and max_resolution in {"scope_label", "scope_project", "latest_compatible"}:
            label = str((context.scope or {}).get("label", ""))
            project = str((context.scope or {}).get("project", ""))
            for checkpoint in reversed(checkpoints):
                checkpoint_scope = checkpoint.get("scope", {}) if isinstance(checkpoint.get("scope", {}), dict) else {}
                if label and str(checkpoint_scope.get("label", "")) == label:
                    selected = checkpoint
                    resolution = "scope_label"
                    break
                if project and max_resolution in {"scope_project", "latest_compatible"} and str(checkpoint_scope.get("project", "")) == project:
                    selected = checkpoint
                    resolution = "scope_project"
                    break
        if selected is None and max_resolution == "latest_compatible":
            selected = checkpoints[-1]
            resolution = "latest_compatible"
        if selected is None:
            context.snapshot["last_restore"] = result.to_dict()
            self._store_agent_state(context, "_cognition_layers_last_restore", result.to_dict())
            return result.to_dict()

        runtime_state = SelfCorrectionTrigger(context.config or self.config).restore_runtime_state(context, selected.get("correction_runtime_state", {}))
        result = RestoreResult(
            restored=True,
            checkpoint_id=selected.get("id"),
            resolution=resolution,
            checkpoint=selected,
            prompt_budget=selected.get("prompt_budget", {}) if isinstance(selected.get("prompt_budget", {}), dict) else {},
            runtime_state=runtime_state.to_dict(),
        )
        context.snapshot["last_restore"] = result.to_dict()
        self._store_agent_state(context, "_cognition_layers_last_restore", result.to_dict())
        return result.to_dict()

    def compact(self, context: AgentContext, budget_tokens: int) -> dict[str, Any]:
        restore = context.snapshot.get("last_restore") if isinstance(context.snapshot.get("last_restore"), dict) else self.restore(context)
        checkpoint = restore.get("checkpoint", {}) if isinstance(restore, dict) else {}
        budget_chars = min(
            int(get_in(context.config, "prompt_policy.max_injected_chars", 900) or 900),
            max(200, int(budget_tokens or 200) * 4),
        )
        items: list[str] = []
        for decision in checkpoint.get("recent_verification_results", [])[-3:]:
            items.append(f"verification {decision.get('action')}: {decision.get('reason')}")
        for correction in checkpoint.get("recent_correction_decisions", [])[-3:]:
            description = describe_guidance(correction)
            items.append(f"correction {correction.get('state') or correction.get('trigger')}: {description or correction.get('action')}")
        runtime_state = checkpoint.get("correction_runtime_state", {}) if isinstance(checkpoint.get("correction_runtime_state", {}), dict) else {}
        if runtime_state.get("last_correction_state"):
            items.append(f"recovery state: {runtime_state.get('last_correction_state')}")
        pending = list(runtime_state.get("pending_guidance", []) or [])
        if pending:
            latest = pending[-1]
            description = describe_guidance(latest)
            items.append(f"pending guidance: {description or latest.get('action')}")
        for pattern in checkpoint.get("recent_patterns", [])[:3]:
            items.append(str(pattern.get("pattern") or pattern.get("summary") or ""))
        raw_text = "Recovery context:\n- " + "\n- ".join(item for item in items if item) if items else ""
        text = bounded_text(raw_text, max_chars=budget_chars) if raw_text else ""
        result = CompactionResult(
            text=text,
            items=[item for item in items if item],
            budget_tokens=int(budget_tokens or 0),
            budget_chars=budget_chars,
            source_checkpoint_id=checkpoint.get("id"),
            truncated=bool(raw_text and len(raw_text) > len(text)),
        )
        context.snapshot["last_compaction"] = result.to_dict()
        self._store_agent_state(context, "_cognition_layers_last_compaction", result.to_dict())
        return result.to_dict()

    def summary(self, agent: Any | None = None) -> dict[str, Any]:
        checkpoints = state.load_checkpoints(5)
        latest = checkpoints[-1] if checkpoints else {}
        data = getattr(agent, "data", {}) if agent is not None else {}
        data = data if isinstance(data, dict) else {}
        settings = bounded_recovery_settings(self.config)
        effective = effective_bounded_recovery_settings(self.config)
        return {
            "checkpoint_count": len(checkpoints),
            "latest_checkpoint_id": latest.get("id"),
            "latest_context_id": latest.get("context_id"),
            "latest_restore": data.get("_cognition_layers_last_restore"),
            "latest_compaction": data.get("_cognition_layers_last_compaction"),
            "bounded_recovery_enabled": bool(settings.get("enabled")),
            "max_restore_resolution": effective.get("max_restore_resolution"),
            "plugin_local_only": True,
        }

    def _store_agent_state(self, context: AgentContext, key: str, value: dict[str, Any]) -> None:
        agent = context.agent
        if agent is None:
            return
        data = getattr(agent, "data", None)
        if isinstance(data, dict):
            data[key] = value
