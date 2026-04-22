from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import yaml
from usr.plugins.cognition_layers.helpers.compat import get_plugin_config
PLUGIN_NAME="cognition_layers"; PLUGIN_ROOT=Path(__file__).resolve().parents[1]; DEFAULT_CONFIG_PATH=PLUGIN_ROOT/"default_config.yaml"
_LAYER_DEFAULT_MODES={"verification":"enforce","pattern_memory":"advisory","self_correction":"advisory","prompt_policy":"standard","observability":"standard"}
_VERIFICATION_REQUIRED_LIST_DEFAULTS=("protected_tools","protected_paths","blocked_shell_patterns","require_review_for")
_ORCHESTRATOR_DEFAULTS={"default_timeout_ms":1000,"max_retries":2,"retry_backoff_ms":50,"max_parallel_actions":4}
_PROFILE_LAYER_MODE_PRESETS={"full":{"self_correction":"auto"}}
_BOUNDED_RECOVERY_DEFAULTS={"enabled":False,"allow_auto_continue_after_failure":False,"max_restore_resolution":"context_id","inject_idle_recovery_policy":False}
_RESTORE_RESOLUTIONS=("context_id","scope_label","scope_project","latest_compatible")

def load_default_config()->dict[str,Any]:
    if not DEFAULT_CONFIG_PATH.exists(): return {}
    data=yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}; return data if isinstance(data,dict) else {}

def deep_merge(base:Any, override:Any)->Any:
    if isinstance(base,dict) and isinstance(override,dict):
        merged={k:deepcopy(v) for k,v in base.items()}
        for k,v in override.items(): merged[k]=deep_merge(merged[k],v) if k in merged else deepcopy(v)
        return merged
    return deepcopy(override)

def _meaningful_list(value:Any)->list[Any]:
    if not isinstance(value,list): return []
    return [item for item in value if not (isinstance(item,str) and not item.strip())]

def _normalize_safety_defaults(resolved:dict[str,Any], default:dict[str,Any])->dict[str,Any]:
    verification=resolved.setdefault("verification",{})
    default_verification=default.get("verification",{}) if isinstance(default.get("verification",{}),dict) else {}
    for key in _VERIFICATION_REQUIRED_LIST_DEFAULTS:
        if not _meaningful_list(verification.get(key)):
            fallback=deepcopy(default_verification.get(key,[]))
            if fallback: verification[key]=fallback
    return resolved

def _normalize_bounded_recovery(resolved:dict[str,Any], runtime:dict[str,Any])->dict[str,Any]:
    bounded=resolved.setdefault("bounded_recovery",{})
    if not isinstance(bounded,dict):
        bounded={}
        resolved["bounded_recovery"]=bounded
    runtime_bounded=runtime.get("bounded_recovery",{}) if isinstance(runtime.get("bounded_recovery",{}),dict) else {}
    bounded["enabled"]=bool(bounded.get("enabled",_BOUNDED_RECOVERY_DEFAULTS["enabled"]))
    for key, default in _BOUNDED_RECOVERY_DEFAULTS.items():
        if key=="enabled":
            continue
        value=bounded.get(key, default)
        if key=="max_restore_resolution":
            text=str(value or "").strip().lower()
            if text not in _RESTORE_RESOLUTIONS:
                text=str(default)
            value=text
        else:
            value=bool(value)
        bounded[key]=value
        if bounded["enabled"] and key not in runtime_bounded:
            bounded[key]=default
    return resolved

def _runtime_layer_mode_override(runtime: dict[str, Any], layer_name: str) -> Any:
    layers=runtime.get("layers",{}) if isinstance(runtime.get("layers",{}),dict) else {}
    layer=layers.get(layer_name,{}) if isinstance(layers.get(layer_name,{}),dict) else {}
    return layer.get("mode")

def _apply_profile_layer_presets(resolved:dict[str,Any], runtime:dict[str,Any], profile:str)->dict[str,Any]:
    presets=_PROFILE_LAYER_MODE_PRESETS.get(profile,{})
    layers=resolved.setdefault("layers",{})
    for layer_name, mode in presets.items():
        if _runtime_layer_mode_override(runtime, layer_name) not in {None, ""}:
            continue
        layer_cfg=layers.setdefault(layer_name,{})
        layer_cfg["mode"]=mode
    return resolved

def _migrate_legacy_profile(runtime: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(runtime)
    plugin = migrated.get("plugin", {}) if isinstance(migrated.get("plugin", {}), dict) else {}
    if plugin:
        profile = str(plugin.get("profile", "") or "").strip()
        legacy_mode = str(plugin.get("mode", "") or "").strip()
        if not profile and legacy_mode:
            plugin["profile"] = legacy_mode
        plugin.pop("mode", None)
        migrated["plugin"] = plugin
    return migrated

def resolve_config(agent:Any|None=None, explicit:dict[str,Any]|None=None)->dict[str,Any]:
    default=load_default_config(); runtime=explicit
    if runtime is None:
        try: runtime=get_plugin_config(PLUGIN_NAME,agent=agent) or {}
        except Exception: runtime={}
    if not isinstance(runtime,dict): runtime={}
    runtime=_migrate_legacy_profile(runtime)
    resolved=deep_merge(default,runtime); resolved.setdefault("plugin",{}); resolved.setdefault("layers",{}); resolved.setdefault("surfaces",{}); resolved=_normalize_safety_defaults(resolved, default); resolved=_normalize_bounded_recovery(resolved, runtime)
    plugin=resolved["plugin"]
    if isinstance(plugin,dict):
        plugin.pop("mode", None)
        plugin.setdefault("profile", "full")
    resolved.setdefault("orchestrator", {})
    for key, value in _ORCHESTRATOR_DEFAULTS.items():
        resolved["orchestrator"].setdefault(key, value)
    verification=resolved.setdefault("verification",{})
    verification.setdefault("cache_enabled", True)
    verification.setdefault("cache_ttl_seconds", 300)
    verification.setdefault("invalidate_on_config_change", True)
    for name,mode in _LAYER_DEFAULT_MODES.items():
        cfg=resolved["layers"].setdefault(name,{}); cfg.setdefault("enabled",True); cfg.setdefault("mode",mode)
    try:
        from usr.plugins.cognition_layers.clf.registry import PROFILE_DEFAULTS, normalize_profile
        selected=normalize_profile(resolved.get("plugin",{}).get("profile","full"))
        resolved=_apply_profile_layer_presets(resolved, runtime, selected)
        user_surfaces=(runtime or {}).get("surfaces",{}) if isinstance(runtime,dict) and isinstance((runtime or {}).get("surfaces",{}),dict) else {}
        if selected != "custom":
            surfaces=deepcopy(PROFILE_DEFAULTS[selected]); surfaces.update(user_surfaces); resolved["surfaces"]=surfaces
    except Exception:
        pass
    return resolved

def get_in(config:dict[str,Any], path:str, default:Any=None)->Any:
    cur:Any=config
    for part in path.split("."):
        if not isinstance(cur,dict) or part not in cur: return default
        cur=cur[part]
    return cur

def stable_config_hash(value: Any) -> str:
    try:
        canonical=json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        canonical=str(value)
    return sha256(canonical.encode("utf-8")).hexdigest()

def verification_cache_hash(config: dict[str, Any]) -> str:
    verification = get_in(config, "verification", {}) if isinstance(config, dict) else {}
    plugin = get_in(config, "plugin", {}) if isinstance(config, dict) else {}
    payload = {
        "verification": verification,
        "spec_version": plugin.get("spec_version", "1.0.0") if isinstance(plugin, dict) else "1.0.0",
    }
    return stable_config_hash(payload)

def is_plugin_enabled(config:dict[str,Any])->bool: return bool(get_in(config,"plugin.enabled",True))
def is_layer_enabled(config:dict[str,Any], layer_name:str)->bool: return is_plugin_enabled(config) and bool(get_in(config,f"layers.{layer_name}.enabled",False))
def layer_mode(config:dict[str,Any], layer_name:str, default:str|None=None)->str:
    fallback=default if default is not None else _LAYER_DEFAULT_MODES.get(layer_name,"standard"); return str(get_in(config,f"layers.{layer_name}.mode",fallback) or fallback).strip().lower()
def prompt_verbosity(config:dict[str,Any])->str: return str(get_in(config,"prompt_policy.verbosity","standard") or "standard").strip().lower()
def bounded_recovery_settings(config:dict[str,Any])->dict[str,Any]:
    bounded=get_in(config,"bounded_recovery",{}) if isinstance(config,dict) else {}
    if not isinstance(bounded,dict):
        bounded={}
    settings={key:bounded.get(key, default) for key, default in _BOUNDED_RECOVERY_DEFAULTS.items()}
    settings["enabled"]=bool(settings["enabled"])
    settings["allow_auto_continue_after_failure"]=bool(settings["allow_auto_continue_after_failure"])
    settings["inject_idle_recovery_policy"]=bool(settings["inject_idle_recovery_policy"])
    resolution=str(settings.get("max_restore_resolution") or _BOUNDED_RECOVERY_DEFAULTS["max_restore_resolution"]).strip().lower()
    settings["max_restore_resolution"]=resolution if resolution in _RESTORE_RESOLUTIONS else _BOUNDED_RECOVERY_DEFAULTS["max_restore_resolution"]
    return settings
def bounded_recovery_enabled(config:dict[str,Any])->bool: return bool(bounded_recovery_settings(config).get("enabled"))
def effective_bounded_recovery_settings(config:dict[str,Any])->dict[str,Any]:
    settings=bounded_recovery_settings(config)
    effective=dict(settings)
    if not effective.get("enabled"):
        effective["allow_auto_continue_after_failure"]=True
        effective["max_restore_resolution"]="latest_compatible"
        effective["inject_idle_recovery_policy"]=True
    return effective

def scope_for_agent(agent:Any|None)->dict[str,Any]:
    if agent is None: return {"label":"global","project":None,"agent_profile":None,"context_id":None}
    context=getattr(agent,"context",None); cfg=getattr(agent,"config",None); context_id=getattr(context,"id",None)
    project=getattr(context,"project_id",None) or getattr(context,"project",None) or getattr(context,"project_name",None) or getattr(context,"folder",None) or None
    profile=getattr(cfg,"profile",None) or getattr(agent,"agent_name",None) or None
    parts=[]
    if project: parts.append(f"project:{project}")
    if profile: parts.append(f"agent:{profile}")
    if not parts and context_id: parts.append(f"context:{context_id}")
    return {"label":" | ".join(parts) if parts else "global","project":project,"agent_profile":profile,"context_id":context_id}

def layer_states(config:dict[str,Any])->dict[str,dict[str,Any]]: return {name:{"enabled":is_layer_enabled(config,name),"mode":layer_mode(config,name)} for name in _LAYER_DEFAULT_MODES}

def plugin_status(agent:Any|None=None, explicit:dict[str,Any]|None=None)->dict[str,Any]:
    cfg=resolve_config(agent=agent, explicit=explicit)
    try:
        from usr.plugins.cognition_layers.clf.registry import resolve_profile
        profile=resolve_profile(cfg).to_dict()
    except Exception: profile={}
    selected=str((profile.get("selected_profile") if isinstance(profile,dict) else None) or get_in(cfg,"plugin.profile","full") or "full")
    return {"plugin_enabled":is_plugin_enabled(cfg),"selected_profile":selected,"profile":profile,"layers":layer_states(cfg),"scope":scope_for_agent(agent),"bounded_recovery":bounded_recovery_settings(cfg)}

def bounded_text(text:str, *, max_chars:int=900)->str:
    clean=" ".join((text or "").split())
    return clean if len(clean)<=max_chars else clean[:max_chars-1].rstrip()+"…"
