from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Any
import re

from usr.plugins.cognition_layers.clf.pattern_persistence import PatternPersistenceCore, resolve_pattern_memory_config
from usr.plugins.cognition_layers.clf.types import AgentContext, Evidence, Observation, Pattern, PatternFilter, PatternValidationResult, utc_now_iso
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.helpers.pattern_summary import keyword_terms, summarize_pattern_evidence
from usr.plugins.cognition_layers.helpers.policy import bounded_text


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{2,}")


def _keywords(text: str, limit: int = 12) -> list[str]:
    return keyword_terms(text, limit=limit)


def response_text(response: Any) -> str:
    message = getattr(response, "message", "")
    if isinstance(message, list):
        return " ".join(str(item) for item in message)
    return str(message or response or "")


def classify_response(response: Any) -> tuple[str, str]:
    text = response_text(response).lower()
    if "without error" in text or "without errors" in text or "no errors" in text:
        return "improvement", text
    if any(marker in text for marker in ["not found", "failed", "error", "exception", "invalid", "denied", "rejected", "validation"]):
        return "error", text
    return "improvement", text


def _confidence(pattern_type: str, text: str) -> float:
    if pattern_type == "error":
        if "not found" in text:
            return 0.84
        if "validation" in text or "invalid" in text:
            return 0.80
        if "rejected" in text or "denied" in text:
            return 0.83
        return 0.76
    return 0.77


def _stable_id(*parts: Any) -> str:
    return "pattern-" + sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]


class PatternDetector:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if isinstance(config, dict) else {}

    def detect(self, context: AgentContext, last_result: Any = None) -> list[Pattern]:
        cfg = context.config or self.config
        settings = resolve_pattern_memory_config(cfg)
        observations: list[Observation] = []
        verification = (context.snapshot or {}).get("last_verification")
        tool_name = context.tool.tool_name if context.tool else None
        trigger = context.trigger or "unknown"
        if isinstance(verification, dict) and verification.get("action") in {"block", "warn"} and settings["store_failure_patterns"]:
            observations.append(
                Observation(
                    observation=str(verification.get("reason") or "verification rejected a tool call"),
                    source="verification_guardian",
                    trigger=str(verification.get("action") or trigger),
                    tool_name=tool_name or verification.get("tool") or verification.get("tool_name"),
                    scope=context.scope,
                    metadata={"policy_action": verification.get("action")},
                )
            )
        response = last_result if last_result is not None else context.response
        if response is not None:
            pattern_type, text = classify_response(response)
            should_store = (
                (pattern_type == "improvement" and settings["store_success_patterns"])
                or (pattern_type == "error" and settings["store_failure_patterns"])
            )
            if should_store:
                observations.append(
                    Observation(
                        observation=text or response_text(response),
                        source="tool_result",
                        trigger=trigger,
                        tool_name=tool_name,
                        scope=context.scope,
                        metadata={"response_kind": pattern_type},
                    )
                )
        patterns = self.detect_from_observations(observations, context=context)
        minimum = float(settings["minimum_pattern_confidence"])
        return [pattern for pattern in patterns if float(pattern.confidence) >= minimum]

    def detect_from_observations(self, observations: list[Observation | dict[str, Any]], *, context: AgentContext | None = None) -> list[Pattern]:
        patterns: list[Pattern] = []
        for observation in observations or []:
            obs = observation if isinstance(observation, Observation) else Observation(
                observation=str((observation or {}).get("observation") or ""),
                source=str((observation or {}).get("source") or "runtime"),
                trigger=(observation or {}).get("trigger"),
                tool_name=(observation or {}).get("tool_name") or (observation or {}).get("toolName"),
                scope=(observation or {}).get("scope") if isinstance((observation or {}).get("scope"), dict) else (context.scope if context else {}),
                observed_at=str((observation or {}).get("observed_at") or (observation or {}).get("observedAt") or utc_now_iso()),
                metadata=(observation or {}).get("metadata") if isinstance((observation or {}).get("metadata"), dict) else {},
            )
            observation_text = obs.observation.lower()
            looks_safe = "without error" in observation_text or "without errors" in observation_text or "no errors" in observation_text
            pattern_type = "error" if obs.source == "verification_guardian" or (not looks_safe and any(marker in observation_text for marker in ["not found", "failed", "error", "invalid", "denied", "rejected", "validation"])) else "improvement"
            guidance = summarize_pattern_evidence(
                pattern_type,
                obs.tool_name,
                [
                    {
                        "observation": obs.observation,
                        "source": obs.source,
                        "observedAt": obs.observed_at,
                        "toolName": obs.tool_name,
                        "scope": obs.scope,
                        "metadata": obs.metadata,
                    }
                ],
                fallback_text=obs.observation,
            )
            candidate = Pattern(
                id=_stable_id(pattern_type, obs.trigger, obs.tool_name, guidance["pattern"], (obs.scope or {}).get("label")),
                type=pattern_type,
                pattern=guidance["pattern"],
                confidence=round(_confidence(pattern_type, obs.observation.lower()), 3),
                firstObserved=obs.observed_at,
                lastObserved=obs.observed_at,
                evidence=[
                    Evidence(
                        observation=bounded_text(obs.observation, max_chars=240),
                        source=obs.source,
                        observedAt=obs.observed_at,
                        toolName=obs.tool_name,
                        scope=obs.scope,
                        metadata=obs.metadata,
                    )
                ],
                mitigation=guidance["mitigation"],
                metadata={
                    "title": (obs.trigger or pattern_type).replace("_", " ").title(),
                    "tags": _keywords(f"{obs.tool_name or ''} {obs.observation}", limit=8),
                    "scope": obs.scope,
                    "trigger": obs.trigger,
                    "source_phase": obs.trigger or obs.source,
                    "tool_name": obs.tool_name,
                    "context_id": str((obs.scope or {}).get("context_id") or ""),
                    "evidence_category": guidance["category"],
                    "evidence_focus_terms": guidance["example_focus"],
                    "example_focus": guidance["example_focus"],
                    "strategy": guidance["strategy"],
                    "strategy_terms": guidance["strategy_terms"],
                },
                storageLayer="L1_SESSION" if (obs.scope or {}).get("context_id") else "L2_AGENT",
            )
            validation = self.validate_pattern(candidate)
            if validation.valid and validation.normalized_pattern:
                patterns.append(self._pattern_from_dict(validation.normalized_pattern))
        return patterns

    def validate_pattern(self, pattern: Pattern | dict[str, Any]) -> PatternValidationResult:
        item = pattern.to_dict() if hasattr(pattern, "to_dict") else dict(pattern)
        normalized = state.normalize_pattern(item)
        errors: list[str] = []
        if normalized.get("type") not in {"improvement", "error"}:
            errors.append("unsupported pattern type")
        if not str(normalized.get("pattern", "")).strip():
            errors.append("pattern text is required")
        if not normalized.get("evidence"):
            errors.append("at least one evidence record is required")
        settings = resolve_pattern_memory_config(self.config)
        evidence_count = len(normalized.get("evidence", []))
        promoted = (
            float(normalized.get("confidence", 0.0) or 0.0) >= float(settings["minimum_pattern_confidence"])
            and evidence_count >= int(settings["min_evidence_count"])
        )
        if normalized.get("status") not in {"verified", "active", "deprecated", "archived", "rejected"}:
            normalized["status"] = "promoted" if promoted else "candidate"
        return PatternValidationResult(
            valid=not errors,
            errors=errors,
            normalized_pattern=normalized if not errors else None,
            promoted=promoted and not errors,
            lifecycle_state=str(normalized.get("status", "candidate")),
        )

    def store_patterns(self, patterns: list[Pattern | dict[str, Any]], persistence: PatternPersistenceCore | None = None) -> list[dict[str, Any]]:
        store = persistence or PatternPersistenceCore(self.config)
        return store.save([pattern.to_dict() if hasattr(pattern, "to_dict") else dict(pattern) for pattern in patterns])

    def query_patterns(self, pattern_filter: PatternFilter | dict[str, Any] | None = None, persistence: PatternPersistenceCore | None = None) -> list[dict[str, Any]]:
        store = persistence or PatternPersistenceCore(self.config)
        return store.loadPatterns(pattern_filter)

    def get_pattern_by_id(self, pattern_id: str, persistence: PatternPersistenceCore | None = None) -> dict[str, Any] | None:
        store = persistence or PatternPersistenceCore(self.config)
        return store.getPatternById(pattern_id)

    def _pattern_from_dict(self, data: dict[str, Any]) -> Pattern:
        evidence = [
            Evidence(
                observation=str(item.get("observation") or ""),
                source=str(item.get("source") or "runtime"),
                observedAt=str(item.get("observedAt") or utc_now_iso()),
                toolName=item.get("toolName"),
                scope=item.get("scope") if isinstance(item.get("scope"), dict) else {},
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            )
            for item in data.get("evidence", [])
            if isinstance(item, dict)
        ]
        return Pattern(
            id=str(data.get("id") or _stable_id("pattern", data.get("pattern"))),
            type=str(data.get("type") or "improvement"),
            pattern=str(data.get("pattern") or ""),
            confidence=round(float(data.get("confidence", 0.75) or 0.75), 3),
            firstObserved=str(data.get("firstObserved") or utc_now_iso()),
            lastObserved=str(data.get("lastObserved") or utc_now_iso()),
            evidence=evidence,
            mitigation=data.get("mitigation"),
            status=str(data.get("status") or "candidate"),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            storageLayer=str(data.get("storageLayer") or "L2_AGENT"),
            schema_version=str(data.get("schema_version") or "3.0"),
            spec_version=str(data.get("spec_version") or "1.0.0"),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            usage_count=max(1, int(data.get("usage_count", 1) or 1)),
        )
