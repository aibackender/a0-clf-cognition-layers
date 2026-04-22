from __future__ import annotations

from typing import Any
import re

from usr.plugins.cognition_layers.clf.types import AgentContext, NotSupportedResult, PatternFilter
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.helpers.pattern_summary import derive_query_strategy_terms
from usr.plugins.cognition_layers.helpers.policy import get_in


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{2,}")


def resolve_pattern_memory_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    raw = cfg.get("pattern_memory", {}) if isinstance(cfg.get("pattern_memory", {}), dict) else {}
    default_layer = str(raw.get("default_storage_layer", "L2_AGENT") or "L2_AGENT").strip().upper()
    if default_layer not in {"L1_SESSION", "L2_AGENT", "L3_SHARED"}:
        default_layer = "L2_AGENT"
    return {
        "store_success_patterns": bool(raw.get("store_success_patterns", True)),
        "store_failure_patterns": bool(raw.get("store_failure_patterns", True)),
        "inject_top_k_patterns": max(0, int(raw.get("inject_top_k_patterns", 3) or 3)),
        "minimum_pattern_confidence": float(raw.get("minimum_pattern_confidence", 0.75) or 0.75),
        "min_evidence_count": max(1, int(raw.get("min_evidence_count", 1) or 1)),
        "similarity_threshold": min(1.0, max(0.0, float(raw.get("similarity_threshold", 0.92) or 0.92))),
        "cooldown_sessions": max(0, int(raw.get("cooldown_sessions", 1) or 1)),
        "default_storage_layer": default_layer,
        "max_patterns": max(1, int(raw.get("max_patterns", 500) or 500)),
    }


class PatternPersistenceCore:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if isinstance(config, dict) else {}
        self.settings = resolve_pattern_memory_config(self.config)

    def not_supported_storage_layer(self, layer: str) -> dict[str, Any]:
        return NotSupportedResult(
            capability=f"pattern_persistence.{layer}",
            reason="Shared/global pattern persistence is outside the plugin-only Standard CLF claim path.",
            host_behavior="shared_pattern_persistence",
        ).to_dict()

    def savePattern(self, pattern: dict[str, Any], *, storage_layer: str | None = None) -> dict[str, Any]:
        layer = str(storage_layer or pattern.get("storageLayer") or self.settings["default_storage_layer"]).strip().upper()
        if layer == "L3_SHARED":
            return self.not_supported_storage_layer(layer)
        normalized = state.normalize_pattern({**dict(pattern), "storageLayer": layer})
        evidence_count = len(normalized.get("evidence", []))
        if normalized.get("status") not in {"verified", "active", "deprecated", "archived", "rejected"}:
            normalized["status"] = (
                "promoted"
                if float(normalized.get("confidence", 0.0) or 0.0) >= float(self.settings["minimum_pattern_confidence"])
                and evidence_count >= int(self.settings["min_evidence_count"])
                else "candidate"
            )
        return state.add_pattern(
            normalized,
            max_patterns=int(self.settings["max_patterns"]),
            similarity_threshold=float(self.settings["similarity_threshold"]),
        )

    def save(self, patterns: list[dict[str, Any]] | list[Any]) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for pattern in patterns or []:
            payload = pattern.to_dict() if hasattr(pattern, "to_dict") else dict(pattern)
            saved.append(self.savePattern(payload))
        return saved

    def loadPatterns(self, pattern_filter: PatternFilter | dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = pattern_filter.to_dict() if hasattr(pattern_filter, "to_dict") else dict(pattern_filter or {})
        storage_layer = filters.get("storage_layer") or filters.get("storageLayer")
        if str(storage_layer or "").upper() == "L3_SHARED":
            return [self.not_supported_storage_layer("L3_SHARED")]
        items = state.get_patterns(
            pattern_type=filters.get("pattern_type") or filters.get("type"),
            scope_label=filters.get("scope_label"),
            statuses=list(filters.get("statuses", []) or []),
            storage_layer=storage_layer,
            context_id=filters.get("context_id"),
        )
        text = str(filters.get("text") or "").strip().lower()
        if text:
            items = [item for item in items if text in str(item.get("pattern", "")).lower() or text in str(item.get("summary", "")).lower()]
        limit = max(1, min(int(filters.get("limit", 50) or 50), 200))
        return items[:limit]

    def getPatternById(self, pattern_id: str) -> dict[str, Any] | None:
        return state.get_pattern_by_id(pattern_id)

    def transitionPattern(self, pattern_id: str, status: str, *, reason: str | None = None) -> dict[str, Any] | None:
        return state.transition_pattern(pattern_id, status, reason=reason)

    def deletePattern(self, pattern_id: str) -> dict[str, Any]:
        return state.delete_pattern(pattern_id)

    def retrieve(self, context: AgentContext, limit: int = 5) -> list[dict[str, Any]]:
        scope_label = (context.scope or {}).get("label")
        allowed_statuses = ["promoted", "verified", "active"]
        patterns = self.loadPatterns(
            PatternFilter(
                statuses=allowed_statuses,
                scope_label=scope_label,
                limit=max(1, min(int(limit or 5), 50)),
            )
        )
        if not patterns and scope_label:
            patterns = self.loadPatterns(PatternFilter(statuses=allowed_statuses, limit=max(1, min(int(limit or 5), 50))))
        query_text = str(context.prompt_state) + str(context.tool.to_dict() if context.tool else "")
        tool_name = context.tool.tool_name if context.tool else None
        query_words = set(self._words(query_text))
        query_strategy_terms = set(derive_query_strategy_terms(query_text, tool_name))
        query_words |= query_strategy_terms
        cooldown_context = str(context.context_id or "")
        scored: list[tuple[float, dict[str, Any]]] = []
        for pattern in patterns:
            metadata = pattern.get("metadata", {}) if isinstance(pattern.get("metadata"), dict) else {}
            if cooldown_context and cooldown_context in [str(item) for item in metadata.get("cooldown_context_ids", []) if str(item)]:
                continue
            words = set(self._words(" ".join([str(pattern.get("title", "")), str(pattern.get("pattern", "")), str(pattern.get("summary", ""))])))
            words |= {str(tag).lower() for tag in pattern.get("tags", [])}
            strategy_terms = {str(term).lower() for term in metadata.get("strategy_terms", []) if str(term)}
            words |= strategy_terms
            score = float(pattern.get("confidence", 0.0) or 0.0) + 0.15 * len(query_words & words) + 0.12 * len(query_strategy_terms & strategy_terms) + 0.02 * int(pattern.get("usage_count", 0) or 0)
            if scope_label and str((pattern.get("scope") or {}).get("label", "")) == str(scope_label):
                score += 0.1
            if str(pattern.get("status", "")) == "active":
                score += 0.05
            if tool_name and str(metadata.get("tool_name") or pattern.get("tool_name") or "").lower() == str(tool_name).lower():
                score += 0.08
            scored.append((score, pattern))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [pattern for score, pattern in scored[: max(1, min(int(limit or 5), 50))] if score > 0.0]
        self._mark_prompt_selection(selected, cooldown_context)
        refreshed = [self.getPatternById(str(pattern.get("id", ""))) for pattern in selected]
        return [pattern for pattern in refreshed if pattern]

    def confirm(self, pattern_id: str) -> dict[str, Any] | None:
        return self.transitionPattern(pattern_id, "verified", reason="manual_confirmation")

    def decay(self) -> None:
        snapshot = state.snapshot()
        cleaned = state.cleanup_state(
            snapshot,
            retain_days=int(get_in(self.config, "observability.retain_history_days", 14) or 14),
            max_patterns=int(self.settings["max_patterns"]),
        )
        state.save_state(cleaned)

    def summary(self, limit: int = 50, scope_label: str | None = None) -> dict[str, Any]:
        patterns = self.loadPatterns({"scope_label": scope_label, "limit": max(1, min(int(limit or 50), 200))})
        counts = state.pattern_stats(scope_label=scope_label)
        return {"patterns": patterns, "scope": scope_label, "counts": counts}

    def _mark_prompt_selection(self, patterns: list[dict[str, Any]], context_id: str) -> None:
        if not patterns:
            return
        keep_contexts = int(self.settings["cooldown_sessions"])
        for pattern in patterns:
            metadata = pattern.get("metadata", {}) if isinstance(pattern.get("metadata"), dict) else {}
            context_ids = [str(item) for item in metadata.get("cooldown_context_ids", []) if str(item)]
            if context_id:
                if context_id in context_ids:
                    context_ids.remove(context_id)
                context_ids.append(context_id)
            if keep_contexts > 0:
                metadata["cooldown_context_ids"] = context_ids[-keep_contexts:]
            else:
                metadata["cooldown_context_ids"] = []
            updated = {**pattern, "status": "active", "metadata": metadata}
            self.savePattern(updated, storage_layer=str(pattern.get("storageLayer") or self.settings["default_storage_layer"]))

    def _words(self, text: str) -> list[str]:
        stop = {"the", "and", "for", "with", "that", "this", "from", "tool", "agent", "error", "failed"}
        return [word.lower() for word in _WORD_RE.findall(text or "") if word.lower() not in stop][:32]
