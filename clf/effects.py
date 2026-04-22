from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

class EffectType:
    BLOCK_TOOL="BlockTool"; INJECT_PROMPT_TEXT="InjectPromptText"; RECORD_TELEMETRY="RecordTelemetry"; PUBLISH_EVENT="PublishEvent"; PERSIST_PATTERNS="PersistPatterns"; CHECKPOINT_CONTEXT="CheckpointContext"; SHOW_WARNING="ShowWarning"; REFRESH_STATUS="RefreshStatus"; SET_RESPONSE_BREAK_LOOP="SetResponseBreakLoop"

@dataclass
class Effect:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return asdict(self)

def block_tool(reason: str, *, tool_name: str | None = None, decision: dict[str, Any] | None = None) -> Effect: return Effect(EffectType.BLOCK_TOOL, {"reason": reason, "tool_name": tool_name, "decision": decision or {}})
def inject_prompt_text(text: str, *, section: str = "cognition_layers") -> Effect: return Effect(EffectType.INJECT_PROMPT_TEXT, {"text": text, "section": section})
def record_telemetry(kind: str, record: dict[str, Any]) -> Effect: return Effect(EffectType.RECORD_TELEMETRY, {"kind": kind, "record": record})
def publish_event(event_name: str, payload: dict[str, Any] | None = None) -> Effect: return Effect(EffectType.PUBLISH_EVENT, {"event_name": event_name, "payload": payload or {}})
def persist_patterns(patterns: list[dict[str, Any]]) -> Effect: return Effect(EffectType.PERSIST_PATTERNS, {"patterns": patterns})
def checkpoint_context(snapshot: dict[str, Any] | None = None) -> Effect: return Effect(EffectType.CHECKPOINT_CONTEXT, {"snapshot": snapshot or {}})
def show_warning(message: str) -> Effect: return Effect(EffectType.SHOW_WARNING, {"message": message})
def refresh_status(status: dict[str, Any] | None = None) -> Effect: return Effect(EffectType.REFRESH_STATUS, {"status": status or {}})
def set_response_break_loop(value: bool) -> Effect: return Effect(EffectType.SET_RESPONSE_BREAK_LOOP, {"break_loop": bool(value)})
