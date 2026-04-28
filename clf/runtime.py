from __future__ import annotations

from typing import Any
import hashlib
import json

from usr.plugins.cognition_layers.clf.adapter import CognitionAdapter
from usr.plugins.cognition_layers.clf.effects import Effect, publish_event, refresh_status
from usr.plugins.cognition_layers.clf.event_bus import get_event_bus
from usr.plugins.cognition_layers.clf.orchestrator import CognitionOrchestrator
from usr.plugins.cognition_layers.clf.registry import SurfaceRegistry, resolve_profile
from usr.plugins.cognition_layers.clf.types import AgentContext
from usr.plugins.cognition_layers.helpers import state, telemetry
from usr.plugins.cognition_layers.helpers.policy import is_plugin_enabled, resolve_config


_RUNTIME_CACHE_KEY = "_cognition_layers_runtime"
_RUNTIME_CONFIG_HASH_KEY = "_cognition_layers_runtime_config_hash"


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


class CognitionRuntime:
    def __init__(self, agent: Any | None = None, config: dict[str, Any] | None = None):
        self.agent = agent
        self.config = config if isinstance(config, dict) else resolve_config(agent=agent)
        self.registry = SurfaceRegistry()
        self.profile_status = resolve_profile(self.config)
        self.event_bus = get_event_bus(max_history=500, max_queue=128)
        self.adapter = CognitionAdapter(self.config, self.profile_status)
        self.orchestrator = CognitionOrchestrator(self.config, self.event_bus)
        state.ensure_storage()
        state.save_profile_status_if_changed(agent, self.profile_status.to_dict())

    def build_context(
        self, agent_zero_ctx: Any | None = None, *, trigger: str | None = None, **kwargs: Any
    ) -> AgentContext:
        return self.adapter.build_context(
            agent_zero_ctx if agent_zero_ctx is not None else self.agent,
            trigger=trigger,
            **kwargs,
        )

    def on_init(self, context: AgentContext) -> list[Effect]:
        if not is_plugin_enabled(context.config):
            return []
        status = self.status(context.agent)
        return [
            publish_event("runtime.initialized", {"profile": self.profile_status.to_dict()}),
            refresh_status(status),
        ]

    def on_pre_llm(self, context: AgentContext) -> list[Effect]:
        return [] if not is_plugin_enabled(context.config) else self.orchestrator.process(context, "pre_llm")

    def on_tool_before(self, context: AgentContext) -> list[Effect]:
        return (
            []
            if not is_plugin_enabled(context.config) or context.tool is None
            else self.orchestrator.process(context, "tool_before")
        )

    def on_tool_after(self, context: AgentContext) -> list[Effect]:
        return [] if not is_plugin_enabled(context.config) else self.orchestrator.process(context, "tool_after")

    def on_prompt_injection(self, context: AgentContext) -> list[Effect]:
        return [] if not is_plugin_enabled(context.config) else self.orchestrator.process(context, "prompt_injection")

    def on_loop_end(self, context: AgentContext) -> list[Effect]:
        return [] if not is_plugin_enabled(context.config) else self.orchestrator.process(context, "loop_end")

    def status(self, agent: Any | None = None) -> dict[str, Any]:
        current_agent = agent if agent is not None else self.agent
        status = telemetry.status_summary(current_agent, config=self.config)
        status["profile"] = self.profile_status.to_dict()
        status["adapter_capabilities"] = self.adapter.adapter_capability_summary(current_agent)
        status["subordinate_contract"] = self.adapter.subordinate_contract_result()
        status["verification_cache"] = state.verification_cache_stats(self.config)
        return status


def get_runtime(agent: Any | None = None, config: dict[str, Any] | None = None) -> CognitionRuntime:
    cfg = config if isinstance(config, dict) else resolve_config(agent=agent)
    cfg_hash = _config_hash(cfg)

    data = getattr(agent, "data", None) if agent is not None else None
    if isinstance(data, dict):
        runtime = data.get(_RUNTIME_CACHE_KEY)
        if isinstance(runtime, CognitionRuntime) and data.get(_RUNTIME_CONFIG_HASH_KEY) == cfg_hash:
            return runtime

        runtime = CognitionRuntime(agent=agent, config=cfg)
        data[_RUNTIME_CACHE_KEY] = runtime
        data[_RUNTIME_CONFIG_HASH_KEY] = cfg_hash
        return runtime

    return CognitionRuntime(agent=agent, config=cfg)
