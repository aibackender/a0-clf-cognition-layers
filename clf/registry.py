from __future__ import annotations
from copy import deepcopy
from typing import Any
from usr.plugins.cognition_layers.clf.types import ProfileStatus
from usr.plugins.cognition_layers.helpers.policy import bounded_recovery_enabled

SPEC_VERSION="1.0.0"
SURFACES=("cognition_adapter","event_bus","cognition_orchestrator","verification_guardian","pattern_detector","pattern_persistence_core","context_manager","self_correction_trigger")
PROFILE_REQUIRED={"core":{"cognition_adapter","event_bus","cognition_orchestrator","verification_guardian"},"standard":{"cognition_adapter","event_bus","cognition_orchestrator","verification_guardian","pattern_detector","pattern_persistence_core"},"full":{"cognition_adapter","event_bus","cognition_orchestrator","verification_guardian","pattern_detector","pattern_persistence_core","context_manager","self_correction_trigger"}}
PROFILE_DEFAULTS={name:{s:s in req for s in SURFACES} for name,req in PROFILE_REQUIRED.items()}
PROFILE_DEFAULTS["custom"]=deepcopy(PROFILE_DEFAULTS["core"])

def normalize_profile(value: Any) -> str:
    p=str(value or "full").strip().lower(); return p if p in {"core","standard","full","custom"} else "custom"

class SurfaceRegistry:
    surfaces=SURFACES
    def expected_for_profile(self, profile: str) -> dict[str,bool]:
        p=normalize_profile(profile); return deepcopy(PROFILE_DEFAULTS["core" if p=="custom" else p])
    def resolve(self, config: dict[str,Any] | None) -> ProfileStatus:
        cfg=config if isinstance(config,dict) else {}; plugin=cfg.get("plugin",{}) if isinstance(cfg.get("plugin",{}),dict) else {}
        selected=normalize_profile(plugin.get("profile","full")); expected=self.expected_for_profile(selected)
        active=deepcopy(expected); overrides=cfg.get("surfaces",{}) if isinstance(cfg.get("surfaces",{}),dict) else {}
        for s in SURFACES:
            if s in overrides: active[s]=bool(overrides[s])
        warnings=[]; effective=selected; status="conformant"; claim=bool(plugin.get("claim_conformance",False))
        bounded_override = bounded_recovery_enabled(cfg)
        if selected=="custom":
            effective="custom"; status="custom override"; warnings.append("Custom profile selected; public CLF conformance is not claimed.")
        else:
            missing=sorted(s for s in PROFILE_REQUIRED[selected] if not active.get(s,False)); changed=sorted(s for s in SURFACES if active.get(s,False)!=expected.get(s,False))
            if missing or changed:
                effective="custom"; status="non-conformant override"
                if missing: warnings.append("Required surface(s) disabled for selected profile: "+", ".join(missing))
                if changed: warnings.append("Surface override differs from selected profile: "+", ".join(changed))
        if bounded_override:
            warnings.append("Bounded recovery override is active; this run is outside the certified Full-profile behavior contract.")
        conformant=effective in {"core","standard","full"} and status=="conformant"
        if claim and not conformant: warnings.append("claim_conformance=true ignored because effective profile is custom."); claim=False
        unsupported=["subordinates: NOT_SUPPORTED by this plugin runtime facade","L3_SHARED pattern persistence: NOT_SUPPORTED; Agent Zero usr-local JSON only","shared/global recovery state: NOT_SUPPORTED; Agent Zero usr-local checkpoints only","discovery mode: NOT_SUPPORTED","external invalidation sources: NOT_SUPPORTED"]+[f"{s}: NOT_SUPPORTED in active profile" for s in SURFACES if not active.get(s,False)]
        return ProfileStatus(selected,effective,str(plugin.get("spec_version",SPEC_VERSION) or SPEC_VERSION),bool(claim and conformant),conformant,status,active,expected,warnings,unsupported)
    def validate_dependencies(self, active: dict[str,bool]) -> list[str]:
        w=[]
        if active.get("pattern_detector") and not active.get("pattern_persistence_core"): w.append("pattern_detector is enabled without pattern_persistence_core; detected patterns will not persist.")
        if active.get("self_correction_trigger") and not active.get("context_manager"): w.append("self_correction_trigger is enabled without context_manager; retry state is agent-local only.")
        if any(active.get(s) for s in ("verification_guardian","pattern_detector","context_manager")) and not active.get("event_bus"): w.append("event_bus is disabled; surface events will not be delivered.")
        return w

def resolve_profile(config: dict[str,Any] | None) -> ProfileStatus:
    r=SurfaceRegistry(); status=r.resolve(config); status.warnings.extend(r.validate_dependencies(status.active_surfaces)); return status
