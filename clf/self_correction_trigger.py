from __future__ import annotations

from collections import defaultdict
from typing import Any
import re

from usr.plugins.cognition_layers.clf.effects import Effect, record_telemetry, set_response_break_loop
from usr.plugins.cognition_layers.clf.pattern_detector import response_text
from usr.plugins.cognition_layers.clf.types import AgentContext, CorrectionDecision, CorrectionRuntimeState
from usr.plugins.cognition_layers.helpers.pattern_summary import summarize_pattern_evidence
from usr.plugins.cognition_layers.helpers.policy import bounded_text, effective_bounded_recovery_settings, layer_mode


ATTEMPT_COUNTER_KEY = "_cognition_layers_attempt_counter"
RECENT_FAILURES_KEY = "_cognition_layers_recent_failures"
PENDING_GUIDANCE_KEY = "_cognition_layers_pending_guidance"
LAST_HISTORY_TRIGGER_KEY = "_cognition_layers_last_history_trigger"
LAST_CORRECTION_STATE_KEY = "_cognition_layers_last_correction_state"
LAST_CORRECTION_DECISION_KEY = "_cognition_layers_last_correction_decision"

_TOOL_NOT_FOUND_RE = re.compile(r"Tool '.*' not found or could not be initialized|could not be initialized|not found", re.I)
_VALIDATION_RE = re.compile(r"tool request must have|validation|invalid request|must have a tool_name|must have a tool_args", re.I)
_VERIFICATION_RE = re.compile(r"verification rejected|blocked by cognition layers|matched blocked|rejected|denied", re.I)
_FIELD_TOKEN_RE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
_CATEGORY_SUMMARY = {
    "policy": "was blocked by verification",
    "validation": "hit a validation or invalid-input error",
    "not_found": "could not be found or initialized",
    "denied": "hit a permission or access error",
    "timeout": "timed out",
    "network": "hit a network or connectivity error",
    "parse": "hit a parsing or format error",
    "rate_limit": "hit a rate limit or quota error",
    "generic": "failed",
}


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


def _data(context: AgentContext) -> dict[str, Any]:
    return _agent_data(context.agent)


def _counter(data: dict[str, Any], key: str) -> defaultdict[str, int]:
    counter = data.get(key)
    if not isinstance(counter, defaultdict):
        counter = defaultdict(int, counter or {})
        data[key] = counter
    return counter


def classify_failure_text(text: str) -> str | None:
    lowered = (text or "").lower()
    if _VALIDATION_RE.search(lowered):
        return "validation_failure"
    if _TOOL_NOT_FOUND_RE.search(lowered):
        return "tool_not_found"
    if _VERIFICATION_RE.search(lowered):
        return "verification_rejection"
    if any(marker in lowered for marker in ["failed", "error", "exception", "traceback"]):
        return "tool_runtime_error"
    return None


def _join_parts(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _failure_evidence(context: AgentContext | None, text: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()

    verification = (context.snapshot or {}).get("last_verification") if context is not None else None
    if isinstance(verification, dict):
        reason = bounded_text(str(verification.get("reason") or "").strip(), max_chars=180)
        if reason:
            key = reason.lower()
            if key not in seen:
                evidence.append(
                    {
                        "observation": reason,
                        "metadata": {"policy_action": verification.get("action")},
                    }
                )
                seen.add(key)

    excerpt = bounded_text(str(text or "").strip(), max_chars=220)
    if excerpt:
        key = excerpt.lower()
        if key not in seen:
            evidence.append({"observation": excerpt})

    return evidence


def _failure_analysis(
    error_type: str | None,
    tool_name: str | None,
    *,
    failure_text: str = "",
    context: AgentContext | None = None,
) -> dict[str, Any]:
    evidence = _failure_evidence(context, failure_text)
    derived = summarize_pattern_evidence("error", tool_name, evidence, fallback_text=failure_text, max_chars=220)
    focus_terms = [str(item) for item in derived.get("focus_terms", []) if str(item).strip()][:3]
    if error_type == "validation_failure":
        field_terms: list[str] = []
        for match in _FIELD_TOKEN_RE.finditer(str(failure_text or "")):
            token = match.group(0)
            if token not in field_terms:
                field_terms.append(token)
        if field_terms:
            focus_terms = field_terms[:3]
    verification = (context.snapshot or {}).get("last_verification") if context is not None else None
    reason = ""
    if isinstance(verification, dict):
        reason = bounded_text(str(verification.get("reason") or "").strip(), max_chars=90)
    if not reason and error_type == "verification_rejection":
        raw = str(failure_text or "").strip()
        raw = re.sub(r"^verification rejected:?\s*", "", raw, flags=re.I)
        reason = bounded_text(raw, max_chars=90)
    return {
        "category": str(derived.get("category") or "generic"),
        "focus_terms": focus_terms,
        "focus_phrase": _join_parts(focus_terms),
        "verification_reason": reason,
    }


def _build_failure_summary(
    error_type: str | None,
    tool_name: str | None,
    *,
    analysis: dict[str, Any],
) -> str:
    subject = tool_name or "The last tool call"
    focus_phrase = str(analysis.get("focus_phrase") or "")
    verification_reason = str(analysis.get("verification_reason") or "")
    category = str(analysis.get("category") or "generic")

    if error_type == "tool_not_found":
        summary = f"{subject} could not be found or initialized"
    elif error_type == "verification_rejection":
        summary = f"{subject} was blocked by verification"
    elif error_type == "validation_failure":
        summary = f"{subject} hit a validation or invalid-input error"
    elif error_type == "tool_runtime_error":
        summary = f"{subject} returned a runtime error"
    else:
        summary = f"{subject} {_CATEGORY_SUMMARY.get(category, _CATEGORY_SUMMARY['generic'])}"

    if verification_reason and error_type == "verification_rejection":
        summary += f" ({verification_reason})"
    elif focus_phrase:
        summary += f" around {focus_phrase}"

    return bounded_text(summary, max_chars=220)


def build_guidance_payload(
    trigger: str | None,
    tool_name: str | None = None,
    *,
    error_type: str | None = None,
    failure_text: str = "",
    attempt: int = 0,
    max_attempts: int = 0,
    context: AgentContext | None = None,
) -> dict[str, str]:
    trigger = (trigger or "").lower()
    effective_error = (error_type or trigger or "").lower()
    analysis = _failure_analysis(effective_error, tool_name, failure_text=failure_text, context=context)
    focus_phrase = str(analysis.get("focus_phrase") or "")
    summary = _build_failure_summary(effective_error, tool_name, analysis=analysis)

    if trigger == "tool_not_found":
        guidance = "Re-read the available tools list before retrying, and do not assume a tool exists without checking."
    elif trigger == "validation_failure":
        guidance = "Fix the request shape before retrying, keep arguments minimal and explicit, and only send fields the tool actually accepts."
        if focus_phrase:
            guidance += f" Re-check {focus_phrase} before retrying."
    elif trigger == "verification_rejection":
        guidance = "Do not repeat the blocked action unchanged. Choose a safer alternative or narrow the command."
    elif trigger == "repeat_same_failure":
        prefix = f"This failed again on attempt {attempt} of {max_attempts}. " if attempt and max_attempts else "This failed repeatedly. "
        guidance = prefix + "Stop repeating the same action, summarize what changed, and retry once with a materially different plan."
    elif trigger == "tool_runtime_error":
        guidance = "Inspect the error, reduce the next step, and retry only if the cause is clear."
        if focus_phrase:
            guidance += f" Start by isolating {focus_phrase}."
    elif trigger == "retry_exhausted":
        finished_attempts = max_attempts or max(0, attempt - 1)
        prefix = f"Retries are exhausted after {finished_attempts} attempt{'s' if finished_attempts != 1 else ''}. " if finished_attempts else "Retries are exhausted. "
        guidance = prefix + "Stop retrying, explain what failed, and choose a different approach."
    else:
        guidance = "Pause, summarize the failure, and retry with a narrower, verifiable step."

    return {
        "failure_summary": summary,
        "guidance": bounded_text(guidance, max_chars=280),
    }


def build_guidance(
    trigger: str | None,
    tool_name: str | None = None,
    *,
    error_type: str | None = None,
    failure_text: str = "",
    attempt: int = 0,
    max_attempts: int = 0,
    context: AgentContext | None = None,
) -> str:
    return build_guidance_payload(
        trigger,
        tool_name,
        error_type=error_type,
        failure_text=failure_text,
        attempt=attempt,
        max_attempts=max_attempts,
        context=context,
    )["guidance"]


def describe_guidance(item: dict[str, Any] | CorrectionDecision | None) -> str:
    payload = item.to_dict() if hasattr(item, "to_dict") else dict(item or {})
    summary = str(payload.get("failure_summary") or "").strip().rstrip(".")
    guidance = str(payload.get("guidance") or payload.get("action") or "").strip()
    if summary and guidance:
        return bounded_text(f"{summary}. Next: {guidance}", max_chars=320)
    if summary:
        return bounded_text(summary, max_chars=220)
    if guidance:
        return bounded_text(guidance, max_chars=220)
    return ""


def queue_guidance(context: AgentContext, decision: CorrectionDecision) -> None:
    data = _data(context)
    queued = data.setdefault(PENDING_GUIDANCE_KEY, [])
    queued.append(decision.to_dict())
    if len(queued) > 5:
        del queued[:-5]


def consume_guidance(agent: Any) -> list[dict[str, Any]]:
    data = _agent_data(agent)
    items = list(data.get(PENDING_GUIDANCE_KEY, []))
    data[PENDING_GUIDANCE_KEY] = []
    return items


class SelfCorrectionTrigger:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if isinstance(config, dict) else {}

    def runtime_state(self, agent: Any | None = None) -> CorrectionRuntimeState:
        data = _agent_data(agent)
        return CorrectionRuntimeState(
            attempt_counter=dict(_counter(data, ATTEMPT_COUNTER_KEY)),
            recent_failures=dict(_counter(data, RECENT_FAILURES_KEY)),
            pending_guidance=list(data.get(PENDING_GUIDANCE_KEY, [])) if isinstance(data.get(PENDING_GUIDANCE_KEY, []), list) else [],
            last_history_trigger=data.get(LAST_HISTORY_TRIGGER_KEY),
            last_correction_state=data.get(LAST_CORRECTION_STATE_KEY),
            last_decision=data.get(LAST_CORRECTION_DECISION_KEY),
            mode=str(data.get("_cognition_layers_self_correction_mode", "advisory") or "advisory"),
        )

    def restore_runtime_state(self, context: AgentContext, runtime_state: dict[str, Any] | CorrectionRuntimeState | None) -> CorrectionRuntimeState:
        data = _data(context)
        if hasattr(runtime_state, "to_dict"):
            payload = runtime_state.to_dict()
        elif isinstance(runtime_state, dict):
            payload = dict(runtime_state)
        else:
            payload = {}
        data[ATTEMPT_COUNTER_KEY] = defaultdict(int, payload.get("attempt_counter", {}) or {})
        data[RECENT_FAILURES_KEY] = defaultdict(int, payload.get("recent_failures", {}) or {})
        data[PENDING_GUIDANCE_KEY] = list(payload.get("pending_guidance", []) or [])
        data[LAST_HISTORY_TRIGGER_KEY] = payload.get("last_history_trigger")
        data[LAST_CORRECTION_STATE_KEY] = payload.get("last_correction_state")
        data[LAST_CORRECTION_DECISION_KEY] = payload.get("last_decision")
        data["_cognition_layers_self_correction_mode"] = str(payload.get("mode", layer_mode(context.config, "self_correction", default="advisory")) or "advisory")
        return self.runtime_state(context.agent)

    def summary(self, agent: Any | None, config: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = config if isinstance(config, dict) else self.config
        state = self.runtime_state(agent).to_dict()
        return {
            "mode": layer_mode(cfg, "self_correction", default="advisory"),
            "pending_guidance_count": len(state.get("pending_guidance", []) or []),
            "last_correction_state": state.get("last_correction_state"),
            "last_decision": state.get("last_decision"),
            "attempt_counter": state.get("attempt_counter", {}),
            "recent_failures": state.get("recent_failures", {}),
            "plugin_local_only": True,
        }

    def evaluate(self, context: AgentContext, failure: Any = None) -> CorrectionDecision:
        cfg = context.config or self.config
        mode = layer_mode(cfg, "self_correction", default="advisory")
        max_attempts = int(cfg.get("self_correction", {}).get("max_correction_attempts", 2) or 2)
        data = _data(context)
        data["_cognition_layers_self_correction_mode"] = mode
        if mode == "off":
            decision = CorrectionDecision(state="suppressed", max_attempts=max_attempts, action="none")
            data[LAST_CORRECTION_STATE_KEY] = decision.state
            data[LAST_CORRECTION_DECISION_KEY] = decision.to_dict()
            return decision

        text = response_text(failure if failure is not None else context.response)
        trigger = classify_failure_text(text)
        tool_name = context.tool.tool_name if context.tool else None
        attempts = _counter(data, ATTEMPT_COUNTER_KEY)
        failures = _counter(data, RECENT_FAILURES_KEY)

        if trigger is None:
            if tool_name:
                for key in [key for key in list(failures.keys()) if key.startswith(f"{tool_name}:")]:
                    failures.pop(key, None)
            previous_state = data.get(LAST_CORRECTION_STATE_KEY)
            if previous_state in {"triggered", "retrying"}:
                decision = CorrectionDecision(
                    state="succeeded_after_retry",
                    trigger="success_after_retry",
                    action="clear_retry_state",
                    max_attempts=max_attempts,
                    response_succeeded=True,
                )
            else:
                decision = CorrectionDecision(state="idle", max_attempts=max_attempts, response_succeeded=True)
            data[LAST_CORRECTION_STATE_KEY] = decision.state
            data[LAST_CORRECTION_DECISION_KEY] = decision.to_dict()
            return decision

        failure_key = f"{tool_name or 'unknown'}:{trigger}"
        failures[failure_key] += 1
        effective_trigger = "repeat_same_failure" if failures[failure_key] >= 2 and cfg.get("self_correction", {}).get("escalate_after_repeated_failures", True) else trigger
        attempts[effective_trigger] += 1
        attempt = attempts[effective_trigger]
        exhausted = attempt > max_attempts
        state_name = "exhausted" if exhausted else "retrying" if attempt > 1 else "triggered"
        guidance_payload = build_guidance_payload(
            "retry_exhausted" if exhausted else effective_trigger,
            tool_name,
            error_type=trigger,
            failure_text=text,
            attempt=attempt,
            max_attempts=max_attempts,
            context=context,
        )
        decision = CorrectionDecision(
            state=state_name,
            trigger="retry_exhausted" if exhausted else effective_trigger,
            error_type=trigger,
            action="stop_retrying" if exhausted else "inject_corrective_guidance",
            retry_allowed=not exhausted,
            attempt=attempt,
            max_attempts=max_attempts,
            guidance=guidance_payload["guidance"],
            failure_summary=guidance_payload["failure_summary"],
            escalated=exhausted or effective_trigger == "repeat_same_failure",
        )
        data[LAST_CORRECTION_STATE_KEY] = decision.state
        data[LAST_CORRECTION_DECISION_KEY] = decision.to_dict()
        return decision

    def next_effects(self, decision: CorrectionDecision, context: AgentContext | None = None) -> list[Effect]:
        effects: list[Effect] = []
        if context is not None and decision.guidance and decision.state in {"triggered", "retrying", "exhausted"}:
            queue_guidance(context, decision)
        if decision.state in {"triggered", "retrying", "exhausted", "succeeded_after_retry"}:
            effects.append(record_telemetry("correction", decision.to_dict()))
        allow_auto_continue = False
        if context is not None:
            allow_auto_continue = bool(effective_bounded_recovery_settings(context.config).get("allow_auto_continue_after_failure", True))
        if (
            context is not None
            and layer_mode(context.config, "self_correction", default="advisory") == "auto"
            and allow_auto_continue
            and decision.retry_allowed
            and context.response is not None
            and bool(getattr(context.response, "break_loop", False))
        ):
            effects.append(set_response_break_loop(False))
        return effects

    def evaluate_history(self, context: AgentContext) -> CorrectionDecision | None:
        cfg = context.config or self.config
        history = " ".join(str(item) for item in (context.prompt_state or {}).get("history_output", []) or [])
        trigger = None
        if _TOOL_NOT_FOUND_RE.search(history) and cfg.get("self_correction", {}).get("retry_on_tool_not_found", True):
            trigger = "tool_not_found"
        elif _VALIDATION_RE.search(history) and cfg.get("self_correction", {}).get("retry_on_validation_failure", True):
            trigger = "validation_failure"
        elif _VERIFICATION_RE.search(history):
            trigger = "verification_rejection"
        if not trigger:
            return None

        data = _data(context)
        fingerprint = f"{trigger}:{hash(history[-500:])}"
        if data.get(LAST_HISTORY_TRIGGER_KEY) == fingerprint:
            return None
        data[LAST_HISTORY_TRIGGER_KEY] = fingerprint
        attempts = _counter(data, ATTEMPT_COUNTER_KEY)
        attempts[trigger] += 1
        max_attempts = int(cfg.get("self_correction", {}).get("max_correction_attempts", 2) or 2)
        exhausted = attempts[trigger] > max_attempts
        guidance_payload = build_guidance_payload(
            "retry_exhausted" if exhausted else trigger,
            context.tool.tool_name if context.tool else None,
            error_type=trigger,
            failure_text=history,
            attempt=attempts[trigger],
            max_attempts=max_attempts,
            context=context,
        )
        decision = CorrectionDecision(
            state="exhausted" if exhausted else "triggered",
            trigger="retry_exhausted" if exhausted else trigger,
            error_type=trigger,
            action="stop_retrying" if exhausted else "inject_corrective_guidance",
            retry_allowed=not exhausted,
            attempt=attempts[trigger],
            max_attempts=max_attempts,
            guidance=guidance_payload["guidance"],
            failure_summary=guidance_payload["failure_summary"],
            escalated=exhausted,
        )
        data[LAST_CORRECTION_STATE_KEY] = decision.state
        data[LAST_CORRECTION_DECISION_KEY] = decision.to_dict()
        queue_guidance(context, decision)
        return decision
