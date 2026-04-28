from __future__ import annotations
from typing import Any
from usr.plugins.cognition_layers.clf.effects import Effect, EffectType
from usr.plugins.cognition_layers.clf.event_bus import get_event_bus
from usr.plugins.cognition_layers.clf.pattern_persistence import PatternPersistenceCore
from usr.plugins.cognition_layers.clf.registry import resolve_profile
from usr.plugins.cognition_layers.clf.types import AgentContext, NotSupportedResult, ProfileStatus, ToolInvocation
from usr.plugins.cognition_layers.helpers import state, telemetry
from usr.plugins.cognition_layers.helpers.compat import RepairableException
from usr.plugins.cognition_layers.helpers.schema import is_valid
from usr.plugins.cognition_layers.helpers.policy import layer_states, resolve_config, scope_for_agent
class CognitionAdapter:
    def __init__(self, config:dict[str,Any]|None=None, profile_status:ProfileStatus|None=None): self.config=config if isinstance(config,dict) else {}; self.profile_status=profile_status
    def build_context(self, agent_zero_ctx:Any|None, *, trigger:str|None=None, **kwargs:Any)->AgentContext:
        agent=agent_zero_ctx; cfg=self.config or resolve_config(agent=agent); prof=self.profile_status or resolve_profile(cfg); state.ensure_storage(); state.save_profile_status_if_changed(agent, prof.to_dict())
        context=getattr(agent,"context",None) if agent is not None else None; config_obj=getattr(agent,"config",None) if agent is not None else None; context_id=getattr(context,"id",None); agent_id=getattr(config_obj,"profile",None) or getattr(agent,"agent_name",None) or getattr(agent,"name",None) or context_id
        loop_data=self.get_loop_data(kwargs); tool=self.get_pending_tool(agent,kwargs); prompt=self.get_prompt_state(agent,loop_data)
        built=AgentContext(agent=agent,agent_id=str(agent_id) if agent_id is not None else None,context_id=str(context_id) if context_id is not None else None,scope=scope_for_agent(agent),config=cfg,profile_status=prof,host_capabilities=self.host_capabilities(agent,loop_data=loop_data),trigger=trigger,tool=tool,response=self.get_response_payload(kwargs),loop_data=loop_data,prompt_state=prompt,snapshot=self.snapshot_context(agent),last_result=self.get_last_tool_result(agent))
        self.validate_context_snapshot(built)
        return built
    def get_pending_tool(self, agent_zero_ctx:Any|None, kwargs:dict[str,Any]|None=None)->ToolInvocation|None:
        data=kwargs or {}; name=data.get("tool_name") or data.get("name") or data.get("tool"); args=data.get("tool_args") or data.get("args") or data.get("arguments") or {}
        if not name: return None
        if not isinstance(args,dict): args={"value":args}
        return ToolInvocation(str(name),args,raw=dict(data))
    def get_last_tool_result(self, agent_zero_ctx:Any|None)->Any:
        d=getattr(agent_zero_ctx,"data",{}) if agent_zero_ctx is not None else {}; return d.get("_cognition_layers_last_tool_result") if isinstance(d,dict) else None
    def get_response_payload(self, kwargs:dict[str,Any]|None=None)->Any:
        data=kwargs or {}
        for key in ("response","result","tool_result","tool_response","output","return_value","value"):
            if key in data and data.get(key) is not None:
                return data.get(key)
        return None
    def get_loop_data(self, kwargs:dict[str,Any]|None=None)->Any:
        data=kwargs or {}
        for key in ("loop_data","loop","prompt_loop"):
            if key in data and data.get(key) is not None:
                return data.get(key)
        return None
    def get_prompt_state(self, agent_zero_ctx:Any|None, loop_data:Any|None=None)->dict[str,Any]:
        if loop_data is None: return {}
        um=getattr(loop_data,"user_message",None); return {"user_message":str(getattr(um,"content","") or ""),"history_output":list(getattr(loop_data,"history_output",[]) or []),"system_count":len(getattr(loop_data,"system",[]) or [])}
    def snapshot_context(self, agent_zero_ctx:Any|None)->dict[str,Any]:
        d=getattr(agent_zero_ctx,"data",{}) if agent_zero_ctx is not None else {}; d=d if isinstance(d,dict) else {}
        return {"last_verification":d.get("_cognition_layers_last_verification"),"last_correction_state":d.get("_cognition_layers_last_correction_state"),"last_correction_decision":d.get("_cognition_layers_last_correction_decision"),"pending_guidance_count":len(d.get("_cognition_layers_pending_guidance",[]) or []),"last_restore":d.get("_cognition_layers_last_restore"),"last_compaction":d.get("_cognition_layers_last_compaction"),"last_checkpoint":d.get("_cognition_layers_last_checkpoint")}
    def host_capabilities(self, agent_zero_ctx:Any|None, *, loop_data:Any|None=None)->dict[str,Any]:
        supported={
            "warning_channel": bool(hasattr(agent_zero_ctx,"hist_add_warning") or getattr(getattr(agent_zero_ctx,"context",None),"log",None)),
            "agent_data": isinstance(getattr(agent_zero_ctx,"data",None),dict),
            "prompt_injection": bool(loop_data is not None and hasattr(loop_data,"system")) or isinstance(getattr(agent_zero_ctx,"data",None),dict),
            "context_snapshot": True,
            "repairable_exception": RepairableException is not None,
        }
        unsupported=[self.not_supported("subordinates","Agent Zero subordinate execution is not implemented in this plugin-only adapter.","subordinate_execution").to_dict()]
        return {"supported":supported,"unsupported":unsupported,"errors":[]}
    def adapter_capability_summary(self, agent_zero_ctx:Any|None, *, loop_data:Any|None=None)->dict[str,Any]:
        caps=self.host_capabilities(agent_zero_ctx, loop_data=loop_data)
        supported_caps=[name for name, enabled in sorted((caps.get("supported") or {}).items()) if enabled]
        return {"supported":supported_caps,"unsupported":caps.get("unsupported",[]),"errors":caps.get("errors",[])}
    def not_supported(self, capability:str, reason:str, host_behavior:str|None=None)->NotSupportedResult:
        return NotSupportedResult(capability=capability, reason=reason, host_behavior=host_behavior)
    def subordinate_contract_result(self)->dict[str,Any]:
        return self.not_supported("subordinates", "Subordinate execution is outside the plugin-only CLF core claim path for this adapter.", "subordinate_execution").to_dict()
    def validate_context_snapshot(self, context:AgentContext)->tuple[bool,list[str]]:
        ok, errors=is_valid("agent_context", context.to_snapshot())
        if errors:
            context.snapshot["_context_schema_errors"]=errors
        return ok, errors
    def emit_effects(self, agent_zero_ctx:Any|None, effects:list[Effect], *, context:AgentContext|None=None)->None:
        pending_block=None
        if context is not None and agent_zero_ctx is not None and context.profile_status is not None:
            telemetry.announce_profile_activation(
                agent_zero_ctx,
                {"profile": context.profile_status.to_dict(), "layers": layer_states(context.config or self.config or {})},
                (context.config if context else self.config) or {},
            )
        for effect in effects or []:
            et=getattr(effect,"type",None) or (effect.get("type") if isinstance(effect,dict) else None); payload=getattr(effect,"payload",None) or (effect.get("payload",{}) if isinstance(effect,dict) else {}) or {}
            if et==EffectType.PUBLISH_EVENT: get_event_bus().publish(str(payload.get("event_name") or "unknown"), payload.get("payload") or {})
            elif et==EffectType.RECORD_TELEMETRY: self._record_telemetry(agent_zero_ctx,payload,context=context)
            elif et==EffectType.PERSIST_PATTERNS: PatternPersistenceCore((context.config if context else self.config) or {}).save(payload.get("patterns") or [])
            elif et==EffectType.CHECKPOINT_CONTEXT: state.save_checkpoint(payload.get("snapshot") or (context.to_snapshot() if context else {}))
            elif et==EffectType.INJECT_PROMPT_TEXT: self._inject_prompt_text(agent_zero_ctx,str(payload.get("text") or ""),context=context)
            elif et==EffectType.SHOW_WARNING: self._show_warning(agent_zero_ctx,str(payload.get("message") or ""))
            elif et==EffectType.REFRESH_STATUS: self._refresh_status(agent_zero_ctx,payload.get("status") or None,context=context)
            elif et==EffectType.SET_RESPONSE_BREAK_LOOP and context is not None and context.response is not None:
                try: context.response.break_loop=bool(payload.get("break_loop",False))
                except Exception: pass
            elif et==EffectType.BLOCK_TOOL: pending_block=payload
        if context is not None and agent_zero_ctx is not None:
            d=getattr(agent_zero_ctx,"data",None)
            if isinstance(d,dict):
                d["_cognition_layers_last_tool_result"]=context.response
                if context.snapshot.get("last_verification"): d["_cognition_layers_last_verification"]=context.snapshot.get("last_verification")
                if context.snapshot.get("last_restore"): d["_cognition_layers_last_restore"]=context.snapshot.get("last_restore")
                if context.snapshot.get("last_compaction"): d["_cognition_layers_last_compaction"]=context.snapshot.get("last_compaction")
                if context.snapshot.get("last_checkpoint"): d["_cognition_layers_last_checkpoint"]=context.snapshot.get("last_checkpoint")
                if context.snapshot.get("last_correction_state"): d["_cognition_layers_last_correction_state"]=context.snapshot.get("last_correction_state")
                if context.snapshot.get("last_correction_decision"): d["_cognition_layers_last_correction_decision"]=context.snapshot.get("last_correction_decision")
        if pending_block:
            raise RepairableException(f"Cognition Layers blocked tool '{pending_block.get('tool_name') or 'tool'}': {pending_block.get('reason') or 'blocked'}")
    def _record_telemetry(self, agent:Any|None, payload:dict[str,Any], *, context:AgentContext|None=None)->None:
        kind=str(payload.get("kind") or ""); rec=payload.get("record") or {}; cfg=(context.config if context else self.config) or {}
        if kind=="decision": telemetry.record_decision(agent,rec,cfg)
        elif kind=="correction": telemetry.record_correction(agent,rec,cfg)
        else: state.add_correction({"kind":kind,"record":rec})
    def _inject_prompt_text(self, agent:Any|None, text:str, *, context:AgentContext|None=None)->None:
        if not text: return
        loop=context.loop_data if context else None
        if loop is not None and hasattr(loop,"system"):
            try: loop.system.append(text); return
            except Exception: pass
        d=getattr(agent,"data",{}) if agent is not None else {}
        if isinstance(d,dict): d.setdefault("_cognition_layers_pending_prompt_text",[]).append(text)
    def _show_warning(self, agent:Any|None, message:str)->None:
        if not message: return
        try: agent.hist_add_warning(message); return
        except Exception: pass
        telemetry.log_debug(agent,message)
    def _refresh_status(self, agent:Any|None, status:dict[str,Any]|None=None, *, context:AgentContext|None=None)->None:
        if agent is None: return
        d=getattr(agent,"data",None)
        if not isinstance(d,dict):
            try: agent.data={}; d=agent.data
            except Exception: return
        if not status:
            status=telemetry.status_summary(agent,config=(context.config if context else self.config) or {})
            if context and context.profile_status: status["profile"]=context.profile_status.to_dict()
        caps=self.adapter_capability_summary(agent, loop_data=context.loop_data if context else None)
        status["adapter_capabilities"]=caps
        status["subordinate_contract"]=self.subordinate_contract_result()
        telemetry.announce_profile_activation(agent, status, (context.config if context else self.config) or {})
        d["_cognition_layers_config"]=(context.config if context else self.config) or {}; d["_cognition_layers_status"]=status
