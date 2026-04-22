from __future__ import annotations

from typing import Any

from usr.plugins.cognition_layers.clf.self_correction_trigger import SelfCorrectionTrigger, consume_guidance, describe_guidance
from usr.plugins.cognition_layers.clf.types import AgentContext, ToolInvocation
from usr.plugins.cognition_layers.helpers.policy import bounded_text, resolve_config, scope_for_agent


def _build_context(agent: Any, config: dict[str, Any], *, response: Any | None = None, tool_name: str | None = None, loop_data: Any | None = None) -> AgentContext:
    cfg = resolve_config(explicit=config)
    return AgentContext(
        agent=agent,
        agent_id=getattr(agent, "agent_name", None) or getattr(getattr(agent, "config", None), "profile", None),
        context_id=str(getattr(getattr(agent, "context", None), "id", None) or ""),
        scope=scope_for_agent(agent),
        config=cfg,
        trigger="tool_after" if tool_name else "prompt_injection",
        tool=ToolInvocation(tool_name=tool_name, tool_args={}) if tool_name else None,
        response=response,
        loop_data=loop_data,
        prompt_state={"history_output": list(getattr(loop_data, "history_output", []) or [])} if loop_data is not None else {},
        snapshot={},
    )


def note_verification_rejection(agent: Any, decision: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    response = type("BlockedResponse", (), {"message": f"verification rejected: {decision.get('reason', 'blocked')}", "break_loop": True})()
    context = _build_context(agent, config, response=response, tool_name=str(decision.get("tool") or decision.get("tool_name") or "tool"))
    trigger = SelfCorrectionTrigger(context.config)
    event = trigger.evaluate(context, response)
    trigger.next_effects(event, context)
    return event.to_dict()


def classify_tool_response(tool_name: str, response: Any) -> str | None:
    _ = tool_name
    context = _build_context(None, {}, response=response, tool_name=tool_name)
    return SelfCorrectionTrigger(context.config).evaluate(context, response).error_type


def handle_tool_response(agent: Any, tool_name: str, response: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    context = _build_context(agent, config, response=response, tool_name=tool_name)
    trigger = SelfCorrectionTrigger(context.config)
    decision = trigger.evaluate(context, response)
    if decision.state in {"idle", "suppressed"}:
        return None
    for effect in trigger.next_effects(decision, context):
        if effect.type == "SetResponseBreakLoop":
            try:
                response.break_loop = bool(effect.payload.get("break_loop", False))
            except Exception:
                pass
    return decision.to_dict()


def history_failure_event(agent: Any, loop_data: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    context = _build_context(agent, config, loop_data=loop_data)
    trigger = SelfCorrectionTrigger(context.config)
    decision = trigger.evaluate_history(context)
    return decision.to_dict() if decision is not None else None


def render_guidance_block(agent: Any, *, max_chars: int = 420) -> str:
    queued = consume_guidance(agent)
    if not queued:
        return ""
    lines = [f"- {describe_guidance(item)}" for item in queued if describe_guidance(item)]
    if not lines:
        return ""
    text = "Recovery guidance:\n" + "\n".join(lines)
    return bounded_text(text, max_chars=max_chars)
