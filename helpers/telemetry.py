from __future__ import annotations

from copy import deepcopy
from typing import Any
import re

from usr.plugins.cognition_layers.helpers.compat import mq
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.clf.context_manager import ContextManager
from usr.plugins.cognition_layers.helpers.policy import bounded_recovery_settings, bounded_text, effective_bounded_recovery_settings, plugin_status, scope_for_agent
from usr.plugins.cognition_layers.clf.conformance import claim_readiness
from usr.plugins.cognition_layers.clf.self_correction_trigger import SelfCorrectionTrigger


_SECRET_KEYS = re.compile(r"(api[_-]?key|token|password|secret|authorization|bearer)", re.I)
_LONG_SECRET = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9])")
_RUNTIME_EVENT_KEYS = "_cognition_layers_runtime_events"
_PROFILE_ACTIVATION_KEY = "_cognition_layers_profile_activation"
_DETAIL_MAX_CHARS = 220
_RUNTIME_LOG_TYPE = "clf"


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _SECRET_KEYS.search(str(key)):
                cleaned[key] = "***redacted***"
            else:
                cleaned[key] = redact_value(item)
        return cleaned
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        if _SECRET_KEYS.search(value):
            return "***redacted***"
        return _LONG_SECRET.sub("***redacted***", value)
    return value


def log_debug(agent: Any | None, message: str, *, source: str = "Cognition Layers") -> None:
    if not agent:
        return
    context = getattr(agent, "context", None)
    try:
        log = getattr(context, "log", None)
        if log:
            log.log(type="info", content=message)
            return
    except Exception:
        pass

    context_id = getattr(context, "id", None)
    if context_id:
        try:
            mq.log_user_message(context_id, message, source=source)
        except Exception:
            return


def _runtime_block_parts(message: str) -> tuple[str, str]:
    text = str(message or "").replace("\r\n", "\n").strip()
    if not text:
        return "", ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return "", ""
    headline = lines[0]
    body = "\n".join(lines[1:])
    return headline, body


def _agent_label(agent: Any | None) -> str:
    if not agent:
        return ""
    for candidate in (
        getattr(agent, "agent_name", None),
        getattr(agent, "name", None),
        getattr(getattr(agent, "config", None), "agent_name", None),
        getattr(getattr(agent, "config", None), "name", None),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _runtime_heading(agent: Any | None, headline: str) -> str:
    text = str(headline or "").strip()
    if not text:
        return ""
    label = _agent_label(agent)
    if label and not text.startswith(f"{label}:"):
        return f"{label}: {text}"
    return text


def _log_runtime_summary(agent: Any | None, headline: str, content: str) -> bool:
    if not agent:
        return False
    context = getattr(agent, "context", None)
    log = getattr(context, "log", None)
    if not log:
        return False

    heading = _runtime_heading(agent, headline)
    payload = heading
    if content:
        payload = f"{payload}\n\n{content}"

    for log_type in (_RUNTIME_LOG_TYPE, "agent"):
        try:
            log.log(
                type=log_type,
                heading=heading,
                content=content,
                update_progress="none",
            )
            return True
        except TypeError:
            try:
                log.log(type=log_type, content=payload, update_progress="none")
                return True
            except Exception:
                continue
        except Exception:
            continue
    return False


def _agent_data(agent: Any | None) -> dict[str, Any]:
    if agent is None:
        return {}
    data = getattr(agent, "data", None)
    if not isinstance(data, dict):
        try:
            agent.data = {}
            data = agent.data
        except Exception:
            data = {}
    return data


def _remember_runtime_event(agent: Any | None, dedupe_key: str) -> bool:
    if not dedupe_key:
        return False
    data = _agent_data(agent)
    seen = data.get(_RUNTIME_EVENT_KEYS)
    if not isinstance(seen, list):
        seen = []
        data[_RUNTIME_EVENT_KEYS] = seen
    if dedupe_key in seen:
        return True
    seen.append(dedupe_key)
    if len(seen) > 100:
        del seen[:-100]
    return False


def _detail_text(value: Any, *, fallback: str = "none", max_chars: int = _DETAIL_MAX_CHARS) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return bounded_text(text, max_chars=max_chars)


def _compact_pairs(*pairs: tuple[str, Any]) -> str:
    items: list[str] = []
    for key, value in pairs:
        text = str(value or "").strip()
        if text:
            items.append(f"{key}={text}")
    return "; ".join(items) if items else "none"


def format_runtime_block(
    headline: str,
    *,
    why: Any,
    state: Any,
    interpretation: Any,
    next_step: Any,
    max_chars: int = _DETAIL_MAX_CHARS,
) -> str:
    return "\n".join(
        [
            str(headline or "").strip(),
            f"Why: {_detail_text(why, max_chars=max_chars)}",
            f"State: {_detail_text(state, max_chars=max_chars)}",
            f"Interpretation: {_detail_text(interpretation, max_chars=max_chars)}",
            f"Next: {_detail_text(next_step, max_chars=max_chars)}",
        ]
    )


def _verification_interpretation(action: str) -> str:
    if action == "block":
        return "blocked: the current request should not run as-is."
    if action == "warn":
        return "warning: proceed only with awareness of the flagged risk."
    return "safe to proceed: structured checks did not find a blocking issue."


def _verification_next_step(action: str) -> str:
    if action == "block":
        return "Stop this tool call and queue corrective guidance or fallback behavior."
    if action == "warn":
        return "Show a warning, continue the tool call, and keep monitoring the result."
    return "Proceed with the tool call and continue normal monitoring."


def format_verification_event(record: dict[str, Any]) -> str:
    action = str(record.get("action") or "allow")
    reason = str(record.get("reason") or "no reason")
    tool_name = str(record.get("tool") or record.get("tool_name") or "tool")
    signal = (
        record.get("matched_blocked_shell_pattern")
        or record.get("matched_blocked_domain")
        or record.get("matched_allowlist_miss")
        or "none"
    )
    cache_status = record.get("cache_status") or ("hit" if record.get("cached") else "miss")
    categories = ",".join(str(item) for item in record.get("risk_categories", []) if item) or "none"
    return format_runtime_block(
        f"[verification] {action}: {reason}",
        why=f"{tool_name} was checked by structured verification before execution.",
        state=_compact_pairs(
            ("tool", tool_name),
            ("mode", record.get("policy_mode") or "enforce"),
            ("risk", record.get("risk_score")),
            ("cache", cache_status),
            ("signal", signal),
            ("categories", categories),
        ),
        interpretation=_verification_interpretation(action),
        next_step=_verification_next_step(action),
    )


def _correction_interpretation(state_name: str, escalated: bool) -> str:
    if state_name == "exhausted":
        return "exhausted: repeated failures hit the retry limit."
    if state_name == "succeeded_after_retry":
        return "good recovery: a previous retry succeeded and retry state can be cleared."
    if escalated:
        return "recovery in progress with escalation because the same failure kept recurring."
    if state_name == "retrying":
        return "recovery in progress: the agent is retrying with adjusted guidance."
    if state_name == "triggered":
        return "recovery in progress: the first corrective attempt has been queued."
    if state_name == "suppressed":
        return "suppressed: self-correction is disabled for this run."
    return "neutral: no corrective action is needed right now."


def _correction_next_step(state_name: str, retry_allowed: bool) -> str:
    if state_name == "succeeded_after_retry":
        return "Clear retry state and continue the current workflow."
    if not retry_allowed:
        return "Stop retrying, summarize the failure, and switch to a different plan."
    if state_name in {"triggered", "retrying"}:
        return "Inject the queued guidance into the next attempt and watch for a materially different result."
    return "Continue without changing the current response flow."


def format_self_correction_event(record: dict[str, Any]) -> str:
    state_name = str(record.get("state") or "triggered")
    trigger = str(record.get("trigger") or "correction")
    action = str(record.get("action") or "updated")
    attempt = record.get("attempt")
    max_attempts = record.get("max_attempts")
    suffix = f" ({attempt}/{max_attempts})" if attempt is not None and max_attempts is not None else ""
    failure_summary = record.get("failure_summary") or "none"
    guidance = record.get("guidance") or "none"
    retry_allowed = bool(record.get("retry_allowed", False))
    escalated = bool(record.get("escalated", False))
    return format_runtime_block(
        f"[self-correction] {state_name}: {trigger} -> {action}{suffix}",
        why=f"The plugin detected {trigger.replace('_', ' ')} and evaluated whether a retry should change course.",
        state=_compact_pairs(
            ("trigger", trigger),
            ("state", state_name),
            ("attempt", f"{attempt}/{max_attempts}" if attempt is not None and max_attempts is not None else ""),
            ("retry_allowed", "yes" if retry_allowed else "no"),
            ("failure", _detail_text(failure_summary, max_chars=110)),
            ("guidance", _detail_text(guidance, max_chars=120)),
        ),
        interpretation=_correction_interpretation(state_name, escalated),
        next_step=_correction_next_step(state_name, retry_allowed),
    )


def format_pattern_event(patterns: list[dict[str, Any]], *, persisted: bool) -> str:
    count = len(patterns or [])
    first = patterns[0] if patterns else {}
    metadata = first.get("metadata", {}) if isinstance(first.get("metadata", {}), dict) else {}
    evidence = first.get("evidence", []) if isinstance(first.get("evidence", []), list) else []
    first_evidence = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
    dominant_source = first_evidence.get("source") or metadata.get("source_phase") or "runtime"
    dominant_trigger = metadata.get("trigger") or metadata.get("source_phase") or "unknown"
    top_pattern = metadata.get("title") or first.get("title") or first.get("pattern") or "unlabeled pattern"
    headline = f"[patterns] detected {count} pattern(s){' and saved them to plugin memory' if persisted else ''}."
    return format_runtime_block(
        headline,
        why="Recent verification or tool output matched behavior worth remembering for future hints.",
        state=_compact_pairs(
            ("count", count),
            ("persisted", "yes" if persisted else "no"),
            ("kind", first.get("type") or "unknown"),
            ("source", dominant_source),
            ("trigger", dominant_trigger),
            ("top", _detail_text(top_pattern, max_chars=100)),
        ),
        interpretation="memory-building signal captured; this is not automatically a failure by itself.",
        next_step="Store these patterns for future hinting." if persisted else "Keep these patterns in the current run without persistence.",
    )


def format_profile_activation_event(effective: str, mode: str) -> str:
    context_recovery = "enabled" if effective == "full" else "disabled"
    headline = f"[profile] {effective} active: patterns, context recovery, self-correction {mode}."
    return format_runtime_block(
        headline,
        why="The resolved cognition profile turned on the CLF runtime layers configured for this agent.",
        state=_compact_pairs(
            ("profile", effective),
            ("patterns", "enabled"),
            ("context_recovery", context_recovery),
            ("self_correction_mode", mode),
        ),
        interpretation="normal activation: CLF is ready to capture reusable outcomes, checkpoint local state, and add corrective guidance when repeated failures warrant it.",
        next_step="Use the active layers as the turn progresses and report only meaningful runtime changes.",
    )

def format_context_checkpoint_event(checkpoint: dict[str, Any]) -> str:
    return format_runtime_block(
        f"[context] checkpoint saved: {checkpoint.get('id')} ({checkpoint.get('context_id') or 'global'}).",
        why="This turn produced local recovery state that may help future turns resume cleanly.",
        state=_compact_pairs(
            ("context", checkpoint.get("context_id") or "global"),
            ("decisions", len(checkpoint.get("recent_verification_results", []) or [])),
            ("patterns", len(checkpoint.get("recent_patterns", []) or [])),
            ("corrections", len(checkpoint.get("recent_correction_decisions", []) or [])),
        ),
        interpretation="normal bookkeeping: this snapshot is for recovery and is not a warning by itself.",
        next_step="Keep this checkpoint available for restore and compaction on later turns.",
    )


def _restore_why(resolution: str) -> str:
    mapping = {
        "context_id": "A checkpoint matched the active conversation context exactly.",
        "scope_label": "No exact context match was found, so the plugin matched the scope label.",
        "scope_project": "No exact context or label match was found, so the plugin matched the project scope.",
        "latest_compatible": "No scoped match was found, so the plugin fell back to the latest compatible checkpoint.",
        "none": "No compatible checkpoint was available in local storage for this context.",
    }
    return mapping.get(resolution, "The plugin selected the best available checkpoint for recovery.")


def format_context_restore_event(restored: dict[str, Any]) -> str:
    restored_ok = bool(restored.get("restored"))
    checkpoint_id = restored.get("checkpoint_id")
    resolution = str(restored.get("resolution") or "none")
    runtime_state = restored.get("runtime_state", {}) if isinstance(restored.get("runtime_state", {}), dict) else {}
    if restored_ok:
        headline = f"[context] restored checkpoint {checkpoint_id} via {resolution}."
        interpretation = "recovery in progress: a compatible local snapshot is back in working state."
        next_step = "Compact the recovered material before the next prompt is assembled."
    else:
        headline = "[context] restored checkpoint unavailable via none."
        interpretation = "neutral: recovery will continue from a fresh state because nothing compatible was found."
        next_step = "Proceed without restored context and create a fresh checkpoint later if needed."
    return format_runtime_block(
        headline,
        why=_restore_why(resolution),
        state=_compact_pairs(
            ("resolution", resolution),
            ("checkpoint", checkpoint_id or "none"),
            ("recovery_state", runtime_state.get("last_correction_state") or "fresh"),
            ("pending_guidance", len(runtime_state.get("pending_guidance", []) or [])),
        ),
        interpretation=interpretation,
        next_step=next_step,
    )


def _compaction_categories(items: list[str]) -> str:
    labels: list[str] = []
    mapping = (
        ("verification ", "verification"),
        ("correction ", "correction"),
        ("recovery state:", "recovery_state"),
        ("pending guidance:", "pending_guidance"),
    )
    for item in items or []:
        text = str(item or "")
        matched = False
        for prefix, label in mapping:
            if text.startswith(prefix):
                if label not in labels:
                    labels.append(label)
                matched = True
                break
        if not matched and "pattern_memory" not in labels:
            labels.append("pattern_memory")
    return ",".join(labels) if labels else "none"


def format_context_compaction_event(compaction: dict[str, Any]) -> str:
    items = list(compaction.get("items", []) or [])
    truncated = bool(compaction.get("truncated"))
    return format_runtime_block(
        f"[context] injected recovery context from {compaction.get('source_checkpoint_id')} ({len(items)} item(s)).",
        why="Recovered decisions, guidance, and patterns were condensed to fit the prompt budget.",
        state=_compact_pairs(
            ("source", compaction.get("source_checkpoint_id") or "none"),
            ("items", len(items)),
            ("categories", _compaction_categories(items)),
            ("truncated", "yes" if truncated else "no"),
            ("budget_chars", compaction.get("budget_chars") or 0),
        ),
        interpretation="recovery in progress: the most relevant local context is being prepared for the next prompt.",
        next_step="Inject this recovery block into the next prompt as cognition_layers_context.",
    )


def log_runtime_event(
    agent: Any | None,
    message: str,
    *,
    config: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    source: str = "Cognition Layers",
) -> None:
    cfg = config if isinstance(config, dict) else {}
    if not bool(cfg.get("observability", {}).get("log_decisions", True)):
        return
    if dedupe_key and _remember_runtime_event(agent, dedupe_key):
        return
    headline, content = _runtime_block_parts(message)
    if _log_runtime_summary(agent, headline, content):
        return
    fallback = headline
    if content:
        fallback = f"{headline}\n\n{content}" if headline else content
    if fallback:
        log_debug(agent, fallback, source=source)


def announce_profile_activation(agent: Any | None, status: dict[str, Any], config: dict[str, Any]) -> None:
    profile = status.get("profile", {}) if isinstance(status.get("profile", {}), dict) else {}
    effective = str(profile.get("effective_profile") or "")
    if effective not in {"standard", "full"}:
        return
    layers = status.get("layers", {}) if isinstance(status.get("layers", {}), dict) else {}
    self_correction = layers.get("self_correction", {}) if isinstance(layers.get("self_correction", {}), dict) else {}
    mode = str(self_correction.get("mode") or "advisory")
    data = _agent_data(agent)
    dedupe_key = f"{effective}:{mode}"
    if data.get(_PROFILE_ACTIVATION_KEY) == dedupe_key:
        return
    data[_PROFILE_ACTIVATION_KEY] = dedupe_key
    log_runtime_event(
        agent,
        format_profile_activation_event(effective, mode),
        config=config,
        dedupe_key=f"profile:{dedupe_key}",
    )


def record_decision(agent: Any | None, decision: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    record = deepcopy(redact_value(decision))
    record.setdefault("scope", scope_for_agent(agent))
    saved = state.add_decision(record)
    if record.get("action") in {"warn", "block"} and bool(config.get("observability", {}).get("log_rejections", True)):
        log_runtime_event(agent, format_verification_event(record), config=config)
    elif bool(config.get("observability", {}).get("log_decisions", True)):
        log_runtime_event(agent, format_verification_event(record), config=config)
    return saved


def record_correction(agent: Any | None, event: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    record = deepcopy(redact_value(event))
    record.setdefault("scope", scope_for_agent(agent))
    saved = state.add_correction(record)
    if bool(config.get("observability", {}).get("log_decisions", True)):
        log_runtime_event(
            agent,
            format_self_correction_event(record),
            config=config,
            dedupe_key=f"self-correction:{record.get('state')}:{record.get('trigger')}:{record.get('attempt')}:{record.get('action')}",
        )
    return saved


def status_summary(agent: Any | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    snap = state.snapshot()
    base = plugin_status(agent=agent, explicit=cfg if cfg else None)
    profile = base.get("profile", {}) if isinstance(base.get("profile", {}), dict) else {}
    bounded = bounded_recovery_settings(cfg)
    effective_bounded = effective_bounded_recovery_settings(cfg)
    base["counters"] = snap.get("counters", {})
    base["recent_decisions"] = snap.get("recent_decisions", [])[-20:]
    base["recent_corrections"] = snap.get("recent_corrections", [])[-20:]
    base["pattern_count"] = len(snap.get("patterns", []))
    base["verification_cache"] = state.verification_cache_stats(cfg)
    base["unsupported_behaviors"] = profile.get("unsupported_behaviors", [])
    base["checkpoint_summary"] = ContextManager(cfg).summary(agent)
    base["self_correction_summary"] = SelfCorrectionTrigger(cfg).summary(agent, cfg)
    base["bounded_recovery_summary"] = {
        "enabled": bool(bounded.get("enabled")),
        "allow_auto_continue_after_failure": bool(effective_bounded.get("allow_auto_continue_after_failure")),
        "max_restore_resolution": effective_bounded.get("max_restore_resolution"),
        "inject_idle_recovery_policy": bool(effective_bounded.get("inject_idle_recovery_policy")),
        "claim_override_active": bool(bounded.get("enabled")) and bool(cfg.get("plugin", {}).get("claim_conformance", False)),
    }
    base["pattern_summary"] = [
        {
            "id": p.get("id"),
            "type": p.get("type"),
            "title": p.get("title"),
            "pattern": p.get("pattern"),
            "status": p.get("status"),
            "confidence": p.get("confidence"),
            "usage_count": p.get("usage_count"),
            "updated_at": p.get("updated_at"),
        }
        for p in snap.get("patterns", [])[:10]
    ]
    base["claim_readiness"] = claim_readiness(cfg, profile, {"errors": []}, base["verification_cache"])
    base["available_claim_paths"] = base["claim_readiness"].get("available_claim_paths", {})
    base["required_suite_status"] = base["claim_readiness"]["required_suite_status"]
    return redact_value(base)
