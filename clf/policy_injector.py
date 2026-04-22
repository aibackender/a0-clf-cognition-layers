from __future__ import annotations
from typing import Any
from usr.plugins.cognition_layers.clf.pattern_persistence import PatternPersistenceCore
from usr.plugins.cognition_layers.clf.self_correction_trigger import consume_guidance, describe_guidance
from usr.plugins.cognition_layers.clf.types import AgentContext
from usr.plugins.cognition_layers.helpers.policy import bounded_text, effective_bounded_recovery_settings, get_in, is_layer_enabled, layer_mode, prompt_verbosity

def _verification_block(context:AgentContext)->str:
    mode=layer_mode(context.config,"verification",default="enforce")
    return bounded_text("Verification policy:\n"+f"- Verification mode: {mode}.\n"+"- For protected tools, avoid blocked shell operations, blocked domains, destructive edits, and likely credential exposure.\n"+"- If a tool call is rejected, do not repeat it unchanged.", max_chars=380)

def _generic_recovery_block()->str:
    return bounded_text("Recovery policy:\n- When a tool or validation step fails, summarize the failure, re-check available tools, and retry once with a materially narrower plan.\n- Avoid repeating the same failing action without a change.", max_chars=340)

class PolicyInjector:
    def __init__(self, config:dict[str,Any]|None=None): self.config=config if isinstance(config,dict) else {}
    def build_prompt_text(self, context:AgentContext)->str:
        cfg=context.config or self.config
        if not bool(get_in(cfg,"plugin.enabled",True)) or not is_layer_enabled(cfg,"prompt_policy"): return ""
        verbosity=prompt_verbosity(cfg); max_chars=int(get_in(cfg,"prompt_policy.max_injected_chars",0) or (900 if verbosity=="detailed" else 700 if verbosity=="standard" else 450))
        blocks=[]
        if context.surface_enabled("verification_guardian") and bool(get_in(cfg,"prompt_policy.inject_verification_policy",True)): blocks.append(_verification_block(context))
        if context.surface_enabled("pattern_persistence_core") and bool(get_in(cfg,"prompt_policy.inject_pattern_hints",True)):
            patterns=PatternPersistenceCore(cfg).retrieve(context, limit=int(get_in(cfg,"pattern_memory.inject_top_k_patterns",3) or 3)); bullets=[f"- {p.get('pattern') or p.get('summary')}" for p in patterns if p.get("pattern") or p.get("summary")]
            if bullets: blocks.append(bounded_text("Pattern hints:\n"+"\n".join(bullets), max_chars=540 if verbosity!="minimal" else 350))
        if context.surface_enabled("self_correction_trigger") and bool(get_in(cfg,"prompt_policy.inject_recovery_policy",True)):
            settings = effective_bounded_recovery_settings(cfg)
            queued=consume_guidance(context.agent); lines=[f"- {describe_guidance(e)}" for e in queued if describe_guidance(e)]
            if lines:
                blocks.append(bounded_text("Recovery guidance:\n"+"\n".join(lines), max_chars=540 if verbosity!="minimal" else 380))
            elif bool(settings.get("inject_idle_recovery_policy", True)):
                blocks.append(_generic_recovery_block())
        return bounded_text("\n\n".join(b for b in blocks if b).strip(), max_chars=max_chars)
