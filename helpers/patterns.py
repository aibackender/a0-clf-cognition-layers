from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
import re

from usr.plugins.cognition_layers.clf.pattern_persistence import PatternPersistenceCore, resolve_pattern_memory_config
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.helpers.policy import bounded_text, scope_for_agent
from usr.plugins.cognition_layers.helpers.pattern_summary import keyword_terms, summarize_pattern_evidence


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{2,}")


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text or "") if len(token) >= 3]


def _keywords(text: str, *, limit: int = 12) -> list[str]:
    return keyword_terms(text, limit=limit)


def response_text(response: Any) -> str:
    message = getattr(response, "message", "")
    if isinstance(message, list):
        return " ".join(str(item) for item in message)
    return str(message or "")


def classify_response(response: Any) -> tuple[str, str]:
    text = response_text(response).lower()
    if any(marker in text for marker in ["not found", "failed", "error", "exception", "invalid", "denied", "rejected", "validation"]):
        return "error", text
    return "improvement", text


def _pattern_confidence(pattern_type: str, text: str) -> float:
    if pattern_type == "error":
        if "not found" in text:
            return 0.84
        if "validation" in text or "invalid" in text:
            return 0.80
        if "rejected" in text or "denied" in text:
            return 0.83
        return 0.76
    return 0.77


def build_pattern_record(
    *,
    pattern_type: str,
    title: str,
    summary: str,
    confidence: float,
    scope: dict[str, Any],
    tags: list[str] | None = None,
    source_tool: str | None = None,
    mitigation: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    storage_layer = "L1_SESSION" if scope.get("context_id") else "L2_AGENT"
    extra_metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "type": pattern_type,
        "pattern": bounded_text(summary, max_chars=220),
        "summary": bounded_text(summary, max_chars=220),
        "title": bounded_text(title, max_chars=110),
        "confidence": round(float(confidence), 2),
        "usage_count": 1,
        "firstObserved": now,
        "lastObserved": now,
        "status": "candidate",
        "scope": scope,
        "tags": tags or [],
        "source_tool": source_tool,
        "tool_name": source_tool,
        "storageLayer": storage_layer,
        "mitigation": bounded_text(str(mitigation or ""), max_chars=220) if mitigation else None,
        "metadata": {
            "title": bounded_text(title, max_chars=110),
            "tags": tags or [],
            "scope": scope,
            "tool_name": source_tool,
            "context_id": scope.get("context_id"),
            **extra_metadata,
        },
        "evidence": evidence or [
            {
                "observation": bounded_text(summary, max_chars=220),
                "source": "helper_capture",
                "observedAt": now,
                "toolName": source_tool,
                "scope": scope,
                "metadata": {"helper": "patterns"},
            }
        ],
    }


def capture_tool_result(agent: Any | None, tool_name: str, response: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    settings = resolve_pattern_memory_config(config)
    scope = scope_for_agent(agent)
    pattern_type, text = classify_response(response)
    should_store = (
        (pattern_type == "improvement" and settings["store_success_patterns"])
        or (pattern_type == "error" and settings["store_failure_patterns"])
    )
    if not should_store:
        return []
    confidence = _pattern_confidence(pattern_type, text)
    if confidence < float(settings["minimum_pattern_confidence"]):
        return []
    tags = _keywords(f"{tool_name} {text}", limit=8)
    evidence = [
        {
            "observation": bounded_text(text or response_text(response), max_chars=240),
            "source": "tool_result",
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "toolName": tool_name,
            "scope": scope,
            "metadata": {"helper": "patterns", "response_kind": pattern_type},
        }
    ]
    summary_info = summarize_pattern_evidence(pattern_type, tool_name, evidence, fallback_text=text)
    if pattern_type == "error":
        title = f"{tool_name}: reusable failure recovery"
    else:
        title = f"{tool_name}: reusable success pattern"
    record = build_pattern_record(
        pattern_type=pattern_type,
        title=title,
        summary=summary_info["pattern"],
        confidence=confidence,
        scope=scope,
        tags=tags,
        source_tool=tool_name,
        mitigation=summary_info["mitigation"],
        evidence=evidence,
        metadata={
            "evidence_category": summary_info["category"],
            "evidence_focus_terms": summary_info["example_focus"],
            "example_focus": summary_info["example_focus"],
            "strategy": summary_info["strategy"],
            "strategy_terms": summary_info["strategy_terms"],
        },
    )
    saved = PatternPersistenceCore(config).savePattern(record)
    return [saved]


def capture_named_failure(
    agent: Any | None,
    *,
    trigger: str,
    summary: str,
    config: dict[str, Any],
    source_tool: str | None = None,
    confidence: float = 0.82,
) -> dict[str, Any] | None:
    settings = resolve_pattern_memory_config(config)
    if not settings["store_failure_patterns"]:
        return None
    if confidence < float(settings["minimum_pattern_confidence"]):
        return None
    record = build_pattern_record(
        pattern_type="error",
        title=trigger.replace("_", " ").strip().title(),
        summary=summary,
        confidence=confidence,
        scope=scope_for_agent(agent),
        tags=_keywords(f"{trigger} {summary}", limit=8),
        source_tool=source_tool,
    )
    return PatternPersistenceCore(config).savePattern(record)


def current_query_text(loop_data: Any) -> str:
    pieces: list[str] = []
    if loop_data is None:
        return ""
    user_message = getattr(loop_data, "user_message", None)
    pieces.append(str(getattr(user_message, "content", "") or ""))
    pieces.append(str(getattr(loop_data, "last_response", "") or ""))
    for item in getattr(loop_data, "history_output", []) or []:
        pieces.append(str(item))
    return " ".join(part for part in pieces if part)


def retrieve_relevant_patterns(agent: Any | None, loop_data: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    settings = resolve_pattern_memory_config(config)
    top_k = int(settings["inject_top_k_patterns"])
    if top_k <= 0:
        return []
    query = current_query_text(loop_data)
    query_keywords = set(_keywords(query, limit=12))
    scope_label = scope_for_agent(agent).get("label")
    patterns = PatternPersistenceCore(config).loadPatterns({"statuses": ["promoted", "verified", "active"], "scope_label": scope_label, "limit": top_k * 4 or 4})
    if not patterns:
        patterns = PatternPersistenceCore(config).loadPatterns({"statuses": ["promoted", "verified", "active"], "limit": top_k * 4 or 4})
    scored: list[tuple[float, dict[str, Any]]] = []
    for pattern in patterns:
        tags = {str(tag).lower() for tag in pattern.get("tags", [])}
        title_words = set(_keywords(str(pattern.get("title", "")), limit=8))
        summary_words = set(_keywords(str(pattern.get("pattern", "") or pattern.get("summary", "")), limit=12))
        overlap = len(query_keywords & (tags | title_words | summary_words))
        score = float(pattern.get("confidence", 0.0) or 0.0) + (0.15 * overlap) + (0.02 * int(pattern.get("usage_count", 0) or 0))
        if scope_label and str((pattern.get("scope") or {}).get("label", "")) == scope_label:
            score += 0.1
        scored.append((score, pattern))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [pattern for _, pattern in scored[:top_k] if _ > 0.0]


def render_pattern_hints(patterns: list[dict[str, Any]], *, max_chars: int = 550) -> str:
    if not patterns:
        return ""
    bullets = [f"- {pattern.get('pattern') or pattern.get('summary')}" for pattern in patterns if pattern.get("pattern") or pattern.get("summary")]
    return bounded_text("Pattern hints:\n" + "\n".join(bullets), max_chars=max_chars)


def pattern_api_summary(limit: int = 50, scope_label: str | None = None) -> dict[str, Any]:
    scoped_patterns = PatternPersistenceCore().loadPatterns({"scope_label": scope_label, "limit": limit})
    counts = state.pattern_stats(scope_label=scope_label)
    return {"patterns": scoped_patterns, "scope": scope_label, "counts": counts}
