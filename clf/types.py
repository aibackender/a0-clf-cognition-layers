from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
import uuid


ProfileName = Literal["core", "standard", "full", "custom"]
VerificationAction = Literal["allow", "warn", "block"]
CorrectionState = Literal["idle", "triggered", "retrying", "succeeded_after_retry", "exhausted", "suppressed"]
ExecutionMode = Literal["serial", "parallel", "blocking"]
ActionStatus = Literal["pending", "success", "failed", "timed_out", "cancelled", "cached"]
CircuitStateName = Literal["closed", "open", "half_open"]
PatternType = Literal["improvement", "error"]
PatternLifecycleState = Literal["candidate", "promoted", "verified", "active", "deprecated", "archived", "rejected"]
StorageLayer = Literal["L1_SESSION", "L2_AGENT", "L3_SHARED"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def stable_hash(*parts: Any) -> str:
    return sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


@dataclass
class ToolInvocation:
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProfileStatus:
    selected_profile: str = "full"
    effective_profile: str = "full"
    spec_version: str = "1.0.0"
    claim_conformance: bool = False
    conformant: bool = False
    status: str = "conformant"
    active_surfaces: dict[str, bool] = field(default_factory=dict)
    expected_surfaces: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unsupported_behaviors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentContext:
    agent: Any | None = None
    agent_id: str | None = None
    context_id: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    profile_status: ProfileStatus | None = None
    host_capabilities: dict[str, bool] = field(default_factory=dict)
    trigger: str | None = None
    tool: ToolInvocation | None = None
    response: Any | None = None
    loop_data: Any | None = None
    prompt_state: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    last_result: Any | None = None
    schema_version: str = "1.0.0"

    @property
    def active_surfaces(self) -> dict[str, bool]:
        return self.profile_status.active_surfaces if self.profile_status else {}

    def surface_enabled(self, surface_name: str) -> bool:
        return bool(self.active_surfaces.get(surface_name, False))

    def to_snapshot(self) -> dict[str, Any]:
        response_summary = None
        if self.response is not None:
            response_summary = {
                "message": str(getattr(self.response, "message", self.response) or ""),
                "break_loop": bool(getattr(self.response, "break_loop", False)),
            }
        return {
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "context_id": self.context_id,
            "scope": self.scope,
            "trigger": self.trigger,
            "tool": self.tool.to_dict() if self.tool else None,
            "profile_status": self.profile_status.to_dict() if self.profile_status else None,
            "host_capabilities": self.host_capabilities,
            "prompt_state": self.prompt_state,
            "snapshot": self.snapshot,
            "last_result_present": self.last_result is not None,
            "response_summary": response_summary,
        }


@dataclass
class NotSupportedResult:
    capability: str
    reason: str
    status: str = "NOT_SUPPORTED"
    supported: bool = False
    host_behavior: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class ComponentStatus:
    component_id: str
    enabled: bool = True
    available: bool = True
    phase_roles: list[str] = field(default_factory=list)
    circuit_breaker_state: CircuitStateName = "closed"
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class CircuitBreakerState:
    component_id: str
    state: CircuitStateName = "closed"
    failure_count: int = 0
    failure_threshold: int = 3
    timeout_seconds: int = 60
    half_open_max_calls: int = 1
    half_open_calls: int = 0
    opened_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class EvaluationResult:
    trigger: str
    triggers: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    component_status: list[ComponentStatus] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["component_status"] = [status.to_dict() for status in self.component_status]
        return data


@dataclass
class PlannedAction:
    action_id: str
    component: str
    operation: str
    priority: int
    dependencies: list[str] = field(default_factory=list)
    execution_mode: ExecutionMode = "serial"
    timeout_ms: int = 1000
    max_retries: int = 2
    retry_backoff_ms: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    valid: bool = True
    issues: list[str] = field(default_factory=list)
    verified_components: list[str] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)
    token_budget: int = 0
    time_budget_ms: int = 0
    conflicts: list[str] = field(default_factory=list)
    circuit_breakers: list[CircuitBreakerState] = field(default_factory=list)
    policies_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["circuit_breakers"] = [breaker.to_dict() for breaker in self.circuit_breakers]
        return data


@dataclass
class ActionExecutionResult:
    action_id: str
    component: str
    operation: str
    status: ActionStatus
    idempotency_key: str
    attempt_count: int = 0
    timeout_ms: int = 0
    cancelled: bool = False
    timed_out: bool = False
    cached: bool = False
    error: str | None = None
    produced_effects: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class ExecutionResult:
    trigger: str
    execution_id: str = field(default_factory=lambda: new_id("execution"))
    action_results: list[ActionExecutionResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)
    retries_applied: int = 0
    cancelled: bool = False
    timed_out: bool = False
    completed_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action_results"] = [result.to_dict() for result in self.action_results]
        return data


@dataclass
class VerificationResult:
    tool_name: str
    action: VerificationAction = "allow"
    reason: str = "allowed"
    risk_score: int = 0
    risk_categories: list[str] = field(default_factory=list)
    matched_blocked_shell_pattern: str | None = None
    matched_blocked_domain: str | None = None
    matched_allowlist_miss: str | None = None
    analysis: dict[str, Any] = field(default_factory=dict)
    policy_mode: str = "enforce"
    scope: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    cache_key: str | None = None
    cache_status: str | None = None
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["layer"] = "verification"
        data["tool"] = self.tool_name
        return data


@dataclass
class VerificationCacheEntry:
    key: str
    tool_name: str
    scope: dict[str, Any]
    config_hash: str
    spec_version: str
    decision: dict[str, Any]
    created_at: str
    expires_at: str
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    observation: str
    source: str
    observedAt: str = field(default_factory=utc_now_iso)
    toolName: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class Observation:
    observation: str
    source: str
    trigger: str | None = None
    tool_name: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["toolName"] = data.pop("tool_name")
        data["observedAt"] = data.pop("observed_at")
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class Pattern:
    id: str
    type: PatternType
    pattern: str
    confidence: float
    firstObserved: str = field(default_factory=utc_now_iso)
    lastObserved: str = field(default_factory=utc_now_iso)
    evidence: list[Evidence] = field(default_factory=list)
    mitigation: str | None = None
    status: PatternLifecycleState = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)
    storageLayer: StorageLayer = "L2_AGENT"
    schema_version: str = "3.0"
    spec_version: str = "1.0.0"
    updated_at: str = field(default_factory=utc_now_iso)
    usage_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class PatternFilter:
    pattern_type: PatternType | None = None
    statuses: list[PatternLifecycleState] = field(default_factory=list)
    scope_label: str | None = None
    storage_layer: StorageLayer | None = None
    text: str | None = None
    limit: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, [], {})}


@dataclass
class PatternValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    normalized_pattern: dict[str, Any] | None = None
    promoted: bool = False
    lifecycle_state: PatternLifecycleState = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class PatternRecord:
    id: str
    kind: str
    confidence: float
    source_phase: str
    tool_name: str | None
    trigger: str | None
    summary: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    last_confirmed_at: str | None = None
    decay_score: float = 1.0
    usage_count: int = 1
    schema_version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.kind
        data["source_tool"] = self.tool_name
        data["updated_at"] = self.last_confirmed_at or self.created_at
        if not data.get("title"):
            data["title"] = (self.trigger or self.kind).replace("_", " ").title()
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class CorrectionDecision:
    state: CorrectionState = "idle"
    trigger: str | None = None
    error_type: str | None = None
    action: str = "none"
    retry_allowed: bool = False
    attempt: int = 0
    max_attempts: int = 0
    guidance: str | None = None
    failure_summary: str | None = None
    escalated: bool = False
    response_succeeded: bool = False
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class CorrectionRuntimeState:
    attempt_counter: dict[str, int] = field(default_factory=dict)
    recent_failures: dict[str, int] = field(default_factory=dict)
    pending_guidance: list[dict[str, Any]] = field(default_factory=list)
    last_history_trigger: str | None = None
    last_correction_state: str | None = None
    last_decision: dict[str, Any] | None = None
    mode: str = "advisory"
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class CheckpointRecord:
    id: str
    context_id: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    profile_status: dict[str, Any] = field(default_factory=dict)
    recent_verification_results: list[dict[str, Any]] = field(default_factory=list)
    recent_patterns: list[dict[str, Any]] = field(default_factory=list)
    recent_correction_decisions: list[dict[str, Any]] = field(default_factory=list)
    correction_runtime_state: CorrectionRuntimeState = field(default_factory=CorrectionRuntimeState)
    prompt_budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"
    spec_version: str = "1.0.0"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["correction_runtime_state"] = self.correction_runtime_state.to_dict()
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class RestoreResult:
    restored: bool = False
    checkpoint_id: str | None = None
    resolution: str = "none"
    checkpoint: dict[str, Any] | None = None
    prompt_budget: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, {}, [])}


@dataclass
class CompactionResult:
    text: str = ""
    items: list[str] = field(default_factory=list)
    budget_tokens: int = 0
    budget_chars: int = 0
    source_checkpoint_id: str | None = None
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, [], "")}


@dataclass
class OrchestrationPlan:
    trigger: str
    phases: list[str] = field(default_factory=lambda: ["evaluate", "plan", "validate", "execute", "post_process"])
    actions: list[PlannedAction] = field(default_factory=list)
    valid: bool = True
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actions"] = [action.to_dict() for action in self.actions]
        return data
