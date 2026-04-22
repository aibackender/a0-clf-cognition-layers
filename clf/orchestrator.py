from __future__ import annotations

from copy import deepcopy
from typing import Any
import time

from usr.plugins.cognition_layers.clf.context_manager import ContextManager
from usr.plugins.cognition_layers.clf.effects import Effect, block_tool, inject_prompt_text, persist_patterns, publish_event, record_telemetry, refresh_status, show_warning
from usr.plugins.cognition_layers.clf.event_bus import EventBus
from usr.plugins.cognition_layers.clf.pattern_detector import PatternDetector
from usr.plugins.cognition_layers.clf.policy_injector import PolicyInjector
from usr.plugins.cognition_layers.clf.self_correction_trigger import SelfCorrectionTrigger
from usr.plugins.cognition_layers.clf.types import ActionExecutionResult, AgentContext, CircuitBreakerState, ComponentStatus, EvaluationResult, ExecutionResult, OrchestrationPlan, PlannedAction, ValidationResult, new_id, stable_hash
from usr.plugins.cognition_layers.clf.verification_guardian import VerificationGuardian
from usr.plugins.cognition_layers.helpers import state, telemetry
from usr.plugins.cognition_layers.helpers.policy import get_in


class CognitionOrchestrator:
    def __init__(self, config:dict[str,Any]|None=None, event_bus:EventBus|None=None):
        self.config=config if isinstance(config,dict) else {}
        self.event_bus=event_bus
        self.verification_guardian=VerificationGuardian(self.config)
        self.pattern_detector=PatternDetector(self.config)
        self.self_correction=SelfCorrectionTrigger(self.config)
        self.policy_injector=PolicyInjector(self.config)
        self.context_manager=ContextManager(self.config)
        self.components:dict[str,dict[str,Any]]={}
        self.breakers:dict[str,CircuitBreakerState]={}
        self._idempotency_cache:dict[str,dict[str,Any]]={}
        self._register_default_components()

    def _register_default_components(self)->None:
        specs = {
            "cognition_orchestrator": ["evaluate", "plan", "validate", "execute", "post_process"],
            "verification_guardian": ["tool_before"],
            "event_bus": ["post_process"],
            "cognition_adapter": ["init", "pre_llm", "prompt_injection", "loop_end"],
            "pattern_detector": ["tool_after"],
            "pattern_persistence_core": ["tool_after"],
            "context_manager": ["pre_llm", "prompt_injection", "loop_end"],
            "self_correction_trigger": ["tool_after", "prompt_injection"],
        }
        for component_id, roles in specs.items():
            self.register_component(component_id, phase_roles=roles)

    def register_component(self, component_id:str, *, phase_roles:list[str]|None=None, metadata:dict[str,Any]|None=None)->ComponentStatus:
        enabled = bool(get_in(self.config, f"surfaces.{component_id}", component_id == "cognition_orchestrator"))
        if component_id in {"event_bus", "cognition_adapter", "cognition_orchestrator"}:
            enabled = True
        self.components[component_id] = {"enabled": enabled, "available": True, "phase_roles": list(phase_roles or []), "metadata": dict(metadata or {})}
        breaker = self.breakers.get(component_id) or CircuitBreakerState(component_id=component_id)
        self.breakers[component_id] = breaker
        return self._component_status(component_id)

    def disable_component(self, component_id:str)->ComponentStatus:
        self.components.setdefault(component_id, {"enabled": True, "available": True, "phase_roles": [], "metadata": {}})
        self.components[component_id]["enabled"] = False
        return self._component_status(component_id)

    def enable_component(self, component_id:str)->ComponentStatus:
        self.components.setdefault(component_id, {"enabled": True, "available": True, "phase_roles": [], "metadata": {}})
        self.components[component_id]["enabled"] = True
        return self._component_status(component_id)

    def get_component_status(self)->list[dict[str,Any]]:
        return [self._component_status(component_id).to_dict() for component_id in sorted(self.components)]

    def get_circuit_breaker_status(self, component_id:str)->dict[str,Any]:
        return self.breakers.setdefault(component_id, CircuitBreakerState(component_id=component_id)).to_dict()

    def recordFailure(self, component_id:str, error:str|None=None)->dict[str,Any]:
        breaker = self.breakers.setdefault(component_id, CircuitBreakerState(component_id=component_id))
        breaker.failure_count += 1
        breaker.last_error = error
        if breaker.failure_count >= breaker.failure_threshold:
            breaker.state = "open"
            breaker.opened_at = state.utc_now_iso()
            breaker.half_open_calls = 0
        return breaker.to_dict()

    def recordSuccess(self, component_id:str)->dict[str,Any]:
        breaker = self.breakers.setdefault(component_id, CircuitBreakerState(component_id=component_id))
        breaker.failure_count = 0
        breaker.state = "closed"
        breaker.opened_at = None
        breaker.half_open_calls = 0
        breaker.last_error = None
        return breaker.to_dict()

    def resetCircuitBreaker(self, component_id:str)->dict[str,Any]:
        self.breakers[component_id] = CircuitBreakerState(component_id=component_id)
        return self.breakers[component_id].to_dict()

    def process(self, context:AgentContext, trigger:str)->list[Effect]:
        context.trigger=trigger
        evaluation=self.evaluate(context,trigger)
        plan=self.plan(context,evaluation)
        validation=self.validate(context,plan)
        execution=self.execute(context,plan,validation)
        context.snapshot["last_evaluation"] = evaluation.to_dict()
        context.snapshot["last_plan"] = plan.to_dict()
        context.snapshot["last_validation"] = validation.to_dict()
        context.snapshot["last_execution"] = execution["execution"].to_dict()
        return self.post_process(context,execution)

    def evaluate(self, context:AgentContext, trigger:str)->EvaluationResult:
        claims=[f"profile:{context.profile_status.effective_profile}" if context.profile_status else "profile:unknown"]
        if context.tool is not None:
            claims.append(f"tool:{context.tool.tool_name}")
        if context.surface_enabled("verification_guardian") and trigger=="tool_before":
            claims.append("verification_required")
        pressure={"prompt_chars":len(str(context.prompt_state or {})),"history_items":len((context.prompt_state or {}).get("history_output",[]) or []),"response_present":context.response is not None}
        if pressure["prompt_chars"] > int(get_in(context.config,"prompt_policy.max_injected_chars",900) or 900):
            claims.append("prompt_pressure")
        status_list=[self._component_status(component_id) for component_id in sorted(self.components)]
        return EvaluationResult(trigger=trigger,triggers=[trigger],claims=claims,patterns=[],context=pressure,component_status=status_list)

    def plan(self, context:AgentContext, evaluation:EvaluationResult)->OrchestrationPlan:
        operations:list[tuple[str,str]]=[]
        trigger=evaluation.trigger
        if trigger=="tool_before" and context.tool and context.surface_enabled("verification_guardian"): operations.append(("verification_guardian","verify_tool"))
        if trigger=="tool_after" and context.surface_enabled("pattern_detector"): operations.append(("pattern_detector","detect_patterns"))
        if trigger=="tool_after" and context.surface_enabled("self_correction_trigger"): operations.append(("self_correction_trigger","evaluate_self_correction"))
        if trigger=="pre_llm" and context.surface_enabled("context_manager"): operations.append(("context_manager","restore_context"))
        if trigger=="prompt_injection" and context.surface_enabled("self_correction_trigger"): operations.append(("self_correction_trigger","evaluate_history_failure"))
        if trigger=="prompt_injection" and context.surface_enabled("context_manager"): operations.append(("context_manager","compact_context"))
        if trigger=="prompt_injection": operations.append(("cognition_adapter","inject_policy_prompt"))
        if trigger=="loop_end": operations.append(("cognition_adapter","cleanup_state"))
        if trigger=="loop_end" and context.surface_enabled("context_manager"): operations.append(("context_manager","checkpoint_context"))
        if trigger in {"init","pre_llm"}: operations.append(("cognition_adapter","refresh_status"))
        actions:list[PlannedAction]=[]
        previous:list[str]=[]
        for index, (component, operation) in enumerate(operations, start=1):
            action_id=f"{trigger}:{index}:{operation}"
            actions.append(PlannedAction(action_id=action_id,component=component,operation=operation,priority=index,dependencies=list(previous),execution_mode="serial",timeout_ms=int(get_in(context.config,"orchestrator.default_timeout_ms",1000) or 1000),max_retries=int(get_in(context.config,"orchestrator.max_retries",2) or 2),retry_backoff_ms=int(get_in(context.config,"orchestrator.retry_backoff_ms",50) or 50),metadata={"trigger":trigger}))
            previous=[action_id]
        return OrchestrationPlan(trigger=trigger, actions=actions, warnings=[])

    def validate(self, context:AgentContext, plan:OrchestrationPlan)->ValidationResult:
        graph={action.action_id:list(action.dependencies) for action in plan.actions}
        verified_components:list[str]=[]
        issues:list[str]=[]
        conflicts:list[str]=[]
        policies=["dependency_validation","budget_validation","circuit_breaker_validation","idempotency_policy"]
        breakers:list[CircuitBreakerState]=[]
        for action in plan.actions:
            component = self.components.get(action.component)
            if component is None:
                issues.append(f"missing component: {action.component}")
                continue
            if not bool(component.get("enabled", True)):
                issues.append(f"disabled component: {action.component}")
            breaker=self._ensure_breaker(action.component)
            if breaker.state == "open":
                issues.append(f"circuit breaker open: {action.component}")
            breakers.append(deepcopy(breaker))
            verified_components.append(action.component)
        if self._has_cycle(graph):
            issues.append("dependency cycle detected")
        if int(get_in(context.config,"orchestrator.max_parallel_actions",4) or 4) < 1:
            conflicts.append("invalid max_parallel_actions")
        return ValidationResult(valid=not issues and not conflicts,issues=issues,verified_components=sorted(set(verified_components)),dependency_graph=graph,token_budget=int(get_in(context.config,"prompt_policy.max_injected_chars",900) or 900),time_budget_ms=sum(action.timeout_ms for action in plan.actions),conflicts=conflicts,circuit_breakers=breakers,policies_applied=policies)

    def execute(self, context:AgentContext, plan:OrchestrationPlan, validation:ValidationResult)->dict[str,Any]:
        effects=[publish_event("orchestrator.plan",plan.to_dict()), publish_event("orchestrator.validation",validation.to_dict())]
        execution=ExecutionResult(trigger=context.trigger or plan.trigger)
        if not validation.valid:
            execution.errors.extend(validation.issues + validation.conflicts)
            return {"effects":effects,"plan":plan,"validation":validation,"execution":execution}
        for action in plan.actions:
            if self._is_cancelled(context):
                execution.cancelled = True
                execution.action_results.append(ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="cancelled",idempotency_key=self._idempotency_key(context, action),attempt_count=0,timeout_ms=action.timeout_ms,cancelled=True,metadata={"reason":"context_cancelled"}))
                break
            action_effects, action_result = self._run_action(context, action)
            effects.extend(action_effects)
            execution.action_results.append(action_result)
            execution.execution_order.append(action.action_id)
            execution.retries_applied += max(0, action_result.attempt_count - 1)
            if action_result.status in {"failed", "timed_out"} and action_result.error:
                execution.errors.append(action_result.error)
            if action_result.status == "timed_out":
                execution.timed_out = True
        return {"effects":effects,"plan":plan,"validation":validation,"execution":execution}

    def post_process(self, context:AgentContext, result:dict[str,Any])->list[Effect]:
        effects=list(result.get("effects",[]))
        execution=result.get("execution")
        if execution is not None:
            effects.append(publish_event("orchestrator.completed",{"trigger":context.trigger,"execution":execution.to_dict(),"effects":len(effects)}))
        effects.append(refresh_status(self._status(context)))
        return effects

    def _run_action(self, context:AgentContext, action:PlannedAction)->tuple[list[Effect], ActionExecutionResult]:
        idempotency_key=self._idempotency_key(context, action)
        cached=self._idempotency_cache.get(idempotency_key)
        if cached:
            result=ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="cached",idempotency_key=idempotency_key,attempt_count=0,timeout_ms=action.timeout_ms,cached=True,produced_effects=int(cached.get("produced_effects", 0) or 0),metadata={"source":"idempotency_cache"})
            return [], result
        last_error=None
        for attempt in range(1, action.max_retries + 2):
            if self._is_cancelled(context):
                return [], ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="cancelled",idempotency_key=idempotency_key,attempt_count=attempt-1,timeout_ms=action.timeout_ms,cancelled=True,metadata={"reason":"context_cancelled"})
            if action.operation in set(context.snapshot.get("forced_timeouts", []) or []):
                last_error=f"operation timed out: {action.operation}"
                self.recordFailure(action.component, last_error)
                if attempt <= action.max_retries:
                    continue
                return [], ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="timed_out",idempotency_key=idempotency_key,attempt_count=attempt,timeout_ms=action.timeout_ms,timed_out=True,error=last_error,metadata={"forced":True})
            started=time.monotonic()
            try:
                effects=self._invoke_action(context, action.operation)
            except Exception as exc:
                last_error=str(exc)
                self.recordFailure(action.component, last_error)
                if attempt <= action.max_retries:
                    continue
                return [], ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="failed",idempotency_key=idempotency_key,attempt_count=attempt,timeout_ms=action.timeout_ms,error=last_error,metadata={"retry_backoff_ms":action.retry_backoff_ms})
            elapsed_ms=int((time.monotonic()-started)*1000)
            if elapsed_ms > action.timeout_ms:
                last_error=f"operation timed out after {elapsed_ms}ms"
                self.recordFailure(action.component, last_error)
                if attempt <= action.max_retries:
                    continue
                return [], ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="timed_out",idempotency_key=idempotency_key,attempt_count=attempt,timeout_ms=action.timeout_ms,timed_out=True,error=last_error,metadata={"elapsed_ms":elapsed_ms})
            self.recordSuccess(action.component)
            result=ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="success",idempotency_key=idempotency_key,attempt_count=attempt,timeout_ms=action.timeout_ms,produced_effects=len(effects),metadata={"elapsed_ms":elapsed_ms})
            self._idempotency_cache[idempotency_key]=result.to_dict()
            return effects, result
        return [], ActionExecutionResult(action_id=action.action_id,component=action.component,operation=action.operation,status="failed",idempotency_key=idempotency_key,attempt_count=action.max_retries+1,timeout_ms=action.timeout_ms,error=last_error or "unknown execution failure")

    def _invoke_action(self, context:AgentContext, operation:str)->list[Effect]:
        if operation=="verify_tool":
            return self._verify_tool(context)
        if operation=="detect_patterns":
            return self._detect_patterns(context)
        if operation=="evaluate_self_correction":
            return self._evaluate_self_correction(context)
        if operation=="evaluate_history_failure":
            return self._evaluate_history_failure(context)
        if operation=="restore_context":
            return self._restore_context(context)
        if operation=="compact_context":
            return self._compact_context(context)
        if operation=="inject_policy_prompt":
            text=self.policy_injector.build_prompt_text(context)
            return [inject_prompt_text(text)] if text else []
        if operation=="cleanup_state":
            return self._cleanup_state(context)
        if operation=="checkpoint_context":
            checkpoint=self.context_manager.checkpoint(context)
            telemetry.log_runtime_event(
                context.agent,
                telemetry.format_context_checkpoint_event(checkpoint),
                config=context.config,
                dedupe_key=f"context-checkpoint:{checkpoint.get('id')}",
            )
            return [publish_event("context.checkpointed", {"checkpoint_id": checkpoint.get("id"), "context_id": checkpoint.get("context_id")})]
        if operation=="refresh_status":
            return [refresh_status(self._status(context))]
        raise ValueError(f"unsupported operation: {operation}")

    def _verify_tool(self, context:AgentContext)->list[Effect]:
        assert context.tool is not None
        effects=[publish_event("verification.started",{"tool":context.tool.tool_name})]
        decision=self.verification_guardian.verify_tool(context,context.tool).to_dict()
        context.snapshot["last_verification"]=decision
        effects += [publish_event("verification.blocked" if decision.get("action")=="block" else "verification.warned" if decision.get("action")=="warn" else "verification.allowed", decision), record_telemetry("decision",decision)]
        if decision.get("action")=="warn":
            effects.append(show_warning(f"[cognition_layers] Warning for {context.tool.tool_name}: {decision.get('reason')}"))
        if decision.get("action")=="block":
            effects.append(show_warning(f"[cognition_layers] Blocked {context.tool.tool_name}: {decision.get('reason')}"))
            if context.surface_enabled("self_correction_trigger"):
                old=context.response
                context.response=f"verification rejected: {decision.get('reason')}"
                dec=self.self_correction.evaluate(context,context.response)
                context.snapshot["last_correction_state"] = dec.state
                context.snapshot["last_correction_decision"] = dec.to_dict()
                effects.extend(self.self_correction.next_effects(dec,context))
                context.response=old
            if context.surface_enabled("pattern_detector"):
                effects.extend(self._detect_patterns(context))
            effects.append(block_tool(str(decision.get("reason") or "blocked"), tool_name=context.tool.tool_name, decision=decision))
        return effects

    def _detect_patterns(self, context:AgentContext)->list[Effect]:
        records=self.pattern_detector.detect(context,last_result=context.response)
        if not records:
            return []
        dicts=[r.to_dict() for r in records]
        persisted=context.surface_enabled("pattern_persistence_core")
        telemetry.log_runtime_event(
            context.agent,
            telemetry.format_pattern_event(dicts, persisted=persisted),
            config=context.config,
            dedupe_key="patterns:" + ",".join(str(item.get("id") or item.get("pattern") or "") for item in dicts),
        )
        effects=[publish_event("pattern.detected",{"count":len(dicts),"patterns":dicts})]
        if persisted:
            effects += [persist_patterns(dicts), publish_event("pattern.persisted",{"count":len(dicts)})]
        return effects

    def _evaluate_self_correction(self, context:AgentContext)->list[Effect]:
        dec=self.self_correction.evaluate(context,context.response)
        context.snapshot["last_correction_state"] = dec.state
        context.snapshot["last_correction_decision"] = dec.to_dict()
        effects=self.self_correction.next_effects(dec,context)
        if dec.state in {"triggered","retrying","exhausted","succeeded_after_retry"}:
            effects.insert(0,publish_event("self_correction.triggered",dec.to_dict()))
        return effects

    def _evaluate_history_failure(self, context:AgentContext)->list[Effect]:
        dec=self.self_correction.evaluate_history(context)
        if dec:
            context.snapshot["last_correction_state"] = dec.state
            context.snapshot["last_correction_decision"] = dec.to_dict()
            return [publish_event("self_correction.triggered",dec.to_dict()), record_telemetry("correction",dec.to_dict())]
        return []

    def _restore_context(self, context:AgentContext)->list[Effect]:
        restored=self.context_manager.restore(context)
        context.snapshot["last_restore"] = restored
        telemetry.log_runtime_event(
            context.agent,
            telemetry.format_context_restore_event(restored),
            config=context.config,
            dedupe_key=f"context-restore:{restored.get('checkpoint_id') or 'none'}:{restored.get('resolution')}",
        )
        return [publish_event("context.restored", restored)]

    def _compact_context(self, context:AgentContext)->list[Effect]:
        budget_chars=int(get_in(context.config,"prompt_policy.max_injected_chars",900) or 900)
        compaction=self.context_manager.compact(context, budget_tokens=max(1, budget_chars // 4))
        context.snapshot["last_compaction"] = compaction
        if compaction.get("text"):
            telemetry.log_runtime_event(
                context.agent,
                telemetry.format_context_compaction_event(compaction),
                config=context.config,
                dedupe_key=f"context-compaction:{compaction.get('source_checkpoint_id')}:{len(compaction.get('items',[]) or [])}:{bool(compaction.get('truncated'))}",
            )
        effects=[publish_event("context.compacted", compaction)]
        if compaction.get("text"):
            effects.append(inject_prompt_text(str(compaction.get("text") or ""), section="cognition_layers_context"))
        return effects

    def _cleanup_state(self, context:AgentContext)->list[Effect]:
        snap=state.snapshot()
        cleaned=state.cleanup_state(snap, retain_days=int(get_in(context.config,"observability.retain_history_days",14) or 14), max_patterns=int(get_in(context.config,"pattern_memory.max_patterns",500) or 500))
        state.save_state(cleaned)
        return [publish_event("context.cleaned",{"patterns":len(cleaned.get("patterns",[]))})]

    def _status(self, context:AgentContext)->dict[str,Any]:
        status=telemetry.status_summary(context.agent,config=context.config)
        status["profile"]=context.profile_status.to_dict() if context.profile_status else {}
        return status

    def _component_status(self, component_id:str)->ComponentStatus:
        component=self.components.setdefault(component_id, {"enabled": True, "available": True, "phase_roles": [], "metadata": {}})
        breaker=self._ensure_breaker(component_id)
        return ComponentStatus(component_id=component_id,enabled=bool(component.get("enabled", True)),available=bool(component.get("available", True)),phase_roles=list(component.get("phase_roles", [])),circuit_breaker_state=breaker.state,last_error=breaker.last_error,metadata=dict(component.get("metadata", {})))

    def _ensure_breaker(self, component_id:str)->CircuitBreakerState:
        breaker=self.breakers.get(component_id)
        if breaker is None:
            breaker=CircuitBreakerState(component_id=component_id)
            self.breakers[component_id]=breaker
        if breaker.state == "open" and breaker.opened_at:
            opened_at=state.parse_dt(breaker.opened_at)
            if opened_at and state.utc_now() >= opened_at + state.timedelta(seconds=breaker.timeout_seconds):
                breaker.state = "half_open"
                breaker.half_open_calls = 0
        return breaker

    def _has_cycle(self, graph:dict[str,list[str]])->bool:
        visited:set[str]=set()
        active:set[str]=set()
        def walk(node:str)->bool:
            if node in active:
                return True
            if node in visited:
                return False
            active.add(node)
            for child in graph.get(node, []):
                if walk(child):
                    return True
            active.remove(node)
            visited.add(node)
            return False
        return any(walk(node) for node in graph)

    def _is_cancelled(self, context:AgentContext)->bool:
        return bool(context.snapshot.get("cancelled")) or bool((context.prompt_state or {}).get("cancelled")) or bool(getattr(context.response, "cancelled", False))

    def _idempotency_key(self, context:AgentContext, action:PlannedAction)->str:
        tool=context.tool.to_dict() if context.tool else {}
        return stable_hash(context.context_id, context.trigger, action.action_id, tool)
