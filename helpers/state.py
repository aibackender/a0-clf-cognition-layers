from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
import hashlib
import json
import os
import re
import shutil
import sys
import uuid

from usr.plugins.cognition_layers.helpers.schema import is_valid
from usr.plugins.cognition_layers.helpers.pattern_summary import keyword_terms, summarize_pattern_evidence


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LEGACY_STATE_DIR = PLUGIN_ROOT / "state"
USER_STATE_DIRNAME = "cognition_layers"
_STATE_LOCK = RLock()
_STATE_ROOT_OVERRIDE: Path | None = None
_PROFILE_STATUS_HASH_KEY = "_cognition_layers_profile_hash"


def resolve_usr_root(plugin_root: str | Path | None = None) -> Path:
    root = Path(plugin_root).expanduser().resolve() if plugin_root is not None else PLUGIN_ROOT
    if root.name == "cognition_layers" and root.parent.name == "plugins" and root.parent.parent.name == "usr":
        return root.parent.parent
    return root.parent


def resolve_state_root(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    _ = (platform_name, env, home)
    return resolve_usr_root() / USER_STATE_DIRNAME / "state"


def _active_state_root() -> Path:
    return _STATE_ROOT_OVERRIDE if _STATE_ROOT_OVERRIDE is not None else resolve_state_root()


def _refresh_state_paths() -> None:
    global DATA_DIR, STATE_DIR, STATE_FILE, CONFIG_FILE, PROFILE_STATUS_FILE
    global PATTERNS_FILE, EVENTS_FILE, CHECKPOINTS_FILE, VERIFICATION_CACHE_FILE, TELEMETRY_ROLLUP_FILE

    DATA_DIR = _active_state_root()
    STATE_DIR = DATA_DIR
    STATE_FILE = STATE_DIR / "state.json"
    CONFIG_FILE = STATE_DIR / "config.json"
    PROFILE_STATUS_FILE = STATE_DIR / "profile_status.json"
    PATTERNS_FILE = STATE_DIR / "patterns.json"
    EVENTS_FILE = STATE_DIR / "events.jsonl"
    CHECKPOINTS_FILE = STATE_DIR / "checkpoints.json"
    VERIFICATION_CACHE_FILE = STATE_DIR / "verification_cache.json"
    TELEMETRY_ROLLUP_FILE = STATE_DIR / "telemetry_rollup.json"


def set_state_root_for_testing(path: str | Path) -> Path:
    global _STATE_ROOT_OVERRIDE
    _STATE_ROOT_OVERRIDE = Path(path).expanduser()
    _refresh_state_paths()
    return DATA_DIR


def clear_state_root_override() -> Path:
    global _STATE_ROOT_OVERRIDE
    _STATE_ROOT_OVERRIDE = None
    _refresh_state_paths()
    return DATA_DIR


def reset_state_for_testing() -> None:
    shutil.rmtree(DATA_DIR, ignore_errors=True)


_refresh_state_paths()

_PATTERN_TYPE_MAP = {
    "success": "improvement",
    "safe": "improvement",
    "workaround": "improvement",
    "improvement": "improvement",
    "failure": "error",
    "unsafe": "error",
    "error": "error",
}
_COMPATIBILITY_KIND = {"improvement": "success", "error": "failure"}
_PATTERN_STATUSES = {"candidate", "promoted", "verified", "active", "deprecated", "archived", "rejected"}
_PATTERN_STATUS_RANK = {
    "archived": 0,
    "deprecated": 1,
    "candidate": 2,
    "promoted": 3,
    "verified": 4,
    "active": 5,
    "rejected": 6,
}
_STORAGE_LAYERS = {"L1_SESSION", "L2_AGENT", "L3_SHARED"}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{2,}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def default_state() -> dict[str, Any]:
    return {
        "version": 3,
        "updated_at": utc_now_iso(),
        "patterns": [],
        "recent_decisions": [],
        "recent_corrections": [],
        "counters": {
            "decisions_total": 0,
            "rejections_total": 0,
            "corrections_total": 0,
            "patterns_total": 0,
            "events_total": 0,
            "checkpoints_total": 0,
        },
    }


def default_rollup_state() -> dict[str, Any]:
    rollup = default_state()
    rollup.pop("patterns", None)
    return rollup


def default_verification_cache() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": utc_now_iso(),
        "items": [],
        "stats": {"hits": 0, "misses": 0, "invalidations": 0},
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return deepcopy(default)
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def ensure_storage() -> None:
    with _STATE_LOCK:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not STATE_FILE.exists():
            _write_json(STATE_FILE, default_state())
        if not PATTERNS_FILE.exists():
            _write_json(PATTERNS_FILE, [])
        if not TELEMETRY_ROLLUP_FILE.exists():
            _write_json(TELEMETRY_ROLLUP_FILE, default_rollup_state())
        if not PROFILE_STATUS_FILE.exists():
            _write_json(PROFILE_STATUS_FILE, {})
        if not CONFIG_FILE.exists():
            _write_json(CONFIG_FILE, {})
        if not CHECKPOINTS_FILE.exists():
            _write_json(CHECKPOINTS_FILE, {"version": 1, "items": []})
        if not VERIFICATION_CACHE_FILE.exists():
            _write_json(VERIFICATION_CACHE_FILE, default_verification_cache())
        if not EVENTS_FILE.exists():
            EVENTS_FILE.touch()


def _normalize_pattern_type(value: Any) -> str:
    return _PATTERN_TYPE_MAP.get(str(value or "").strip().lower(), "improvement")


def _normalize_status(value: Any) -> str:
    status = str(value or "candidate").strip().lower()
    return status if status in _PATTERN_STATUSES else "candidate"


def _normalize_storage_layer(value: Any, *, context_id: str | None = None) -> str:
    layer = str(value or "").strip().upper()
    if layer in _STORAGE_LAYERS:
        return layer
    return "L1_SESSION" if context_id else "L2_AGENT"


def _normalize_evidence(item: Any, *, fallback_observation: str, fallback_source: str, tool_name: str | None, scope: dict[str, Any], observed_at: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = deepcopy(item)
    else:
        payload = {"observation": str(item or fallback_observation), "source": fallback_source}
    payload.setdefault("observation", fallback_observation)
    payload.setdefault("source", fallback_source)
    payload.setdefault("observedAt", payload.pop("observed_at", None) or observed_at)
    payload.setdefault("toolName", payload.pop("tool_name", None) or payload.pop("source_tool", None) or tool_name)
    payload.setdefault("scope", deepcopy(scope))
    payload.setdefault("metadata", deepcopy(payload.get("metadata", {})) if isinstance(payload.get("metadata", {}), dict) else deepcopy(metadata))
    return {
        "observation": str(payload.get("observation") or fallback_observation),
        "source": str(payload.get("source") or fallback_source),
        "observedAt": str(payload.get("observedAt") or observed_at),
        "toolName": payload.get("toolName"),
        "scope": payload.get("scope") if isinstance(payload.get("scope"), dict) else deepcopy(scope),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else deepcopy(metadata),
    }


def _compatibility_counts(patterns: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(patterns), "improvement": 0, "error": 0, "success": 0, "failure": 0}
    for pattern in patterns:
        pattern_type = str(pattern.get("type", ""))
        if pattern_type in {"improvement", "error"}:
            counts[pattern_type] += 1
            counts[_COMPATIBILITY_KIND[pattern_type]] += 1
    return counts


def _pattern_sort_key(pattern: dict[str, Any]) -> tuple[int, float, int, str]:
    return (
        _PATTERN_STATUS_RANK.get(str(pattern.get("status", "candidate")), 0),
        float(pattern.get("confidence", 0.0) or 0.0),
        int(pattern.get("usage_count", 0) or 0),
        str(pattern.get("updated_at", "")),
    )


def _merge_status(existing_status: str, new_status: str) -> str:
    if new_status == "rejected":
        return "rejected"
    if existing_status == "rejected":
        return existing_status
    return existing_status if _PATTERN_STATUS_RANK.get(existing_status, 0) >= _PATTERN_STATUS_RANK.get(new_status, 0) else new_status


def _tokenize_pattern_text(text: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(text or "")}


def _canonical_pattern_text(text: str) -> str:
    return " ".join(token.lower() for token in _WORD_RE.findall(text or ""))


def _pattern_similarity_text(pattern: dict[str, Any]) -> str:
    metadata = pattern.get("metadata", {}) if isinstance(pattern.get("metadata"), dict) else {}
    focus_terms = " ".join(str(item) for item in metadata.get("evidence_focus_terms", []) if str(item))
    strategy_terms = " ".join(str(item) for item in metadata.get("strategy_terms", []) if str(item))
    tags = " ".join(str(item) for item in pattern.get("tags", []) if str(item))
    return " ".join(
        part
        for part in [
            str(pattern.get("title", "")),
            str(pattern.get("pattern", "")),
            str(pattern.get("summary", "")),
            tags,
            focus_terms,
            strategy_terms,
            str(metadata.get("strategy") or ""),
        ]
        if part
    )


def _pattern_tool_name(pattern: dict[str, Any]) -> str:
    metadata = pattern.get("metadata", {}) if isinstance(pattern.get("metadata"), dict) else {}
    return str(pattern.get("tool_name") or pattern.get("source_tool") or metadata.get("tool_name") or "").strip().lower()


def _pattern_category(pattern: dict[str, Any]) -> str:
    metadata = pattern.get("metadata", {}) if isinstance(pattern.get("metadata"), dict) else {}
    return str(metadata.get("evidence_category") or "").strip().lower()


def _pattern_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    if str(left.get("type")) != str(right.get("type")):
        return 0.0
    if str(left.get("storageLayer", "")) != str(right.get("storageLayer", "")):
        return 0.0
    left_scope = left.get("scope", {}) if isinstance(left.get("scope", {}), dict) else {}
    right_scope = right.get("scope", {}) if isinstance(right.get("scope", {}), dict) else {}
    if str(left_scope.get("label", "")) and str(right_scope.get("label", "")) and str(left_scope.get("label", "")) != str(right_scope.get("label", "")):
        return 0.0
    left_context = str(left_scope.get("context_id", "") or (left.get("metadata", {}) if isinstance(left.get("metadata", {}), dict) else {}).get("context_id") or "")
    right_context = str(right_scope.get("context_id", "") or (right.get("metadata", {}) if isinstance(right.get("metadata", {}), dict) else {}).get("context_id") or "")
    if left_context and right_context and left_context != right_context:
        return 0.0
    left_tokens = _tokenize_pattern_text(_pattern_similarity_text(left))
    right_tokens = _tokenize_pattern_text(_pattern_similarity_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    if _pattern_tool_name(left) and _pattern_tool_name(left) == _pattern_tool_name(right):
        score += 0.08
    left_category = _pattern_category(left)
    right_category = _pattern_category(right)
    if left_category and left_category == right_category:
        score += 0.04
    return min(score, 1.0)


def normalize_profile_status(status: dict[str, Any]) -> dict[str, Any]:
    profile = deepcopy(status if isinstance(status, dict) else {})
    profile.setdefault("selected_profile", "full")
    profile.setdefault("effective_profile", profile.get("selected_profile", "full"))
    profile.setdefault("spec_version", "1.0.0")
    profile.setdefault("claim_conformance", False)
    profile.setdefault("conformant", False)
    profile.setdefault("status", "custom override")
    profile.setdefault("active_surfaces", {})
    profile.setdefault("expected_surfaces", {})
    profile.setdefault("warnings", [])
    profile.setdefault("unsupported_behaviors", [])
    profile.setdefault("updated_at", utc_now_iso())
    return profile


def normalize_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(checkpoint if isinstance(checkpoint, dict) else {})
    snapshot.setdefault("id", f"checkpoint-{uuid.uuid4().hex[:12]}")
    snapshot.setdefault("context_id", None)
    snapshot.setdefault("scope", {})
    snapshot.setdefault("profile_status", {})
    snapshot.setdefault("recent_verification_results", [])
    snapshot.setdefault("recent_patterns", [])
    snapshot.setdefault("recent_correction_decisions", [])
    runtime_state = snapshot.get("correction_runtime_state", {}) if isinstance(snapshot.get("correction_runtime_state", {}), dict) else {}
    runtime_state.setdefault("attempt_counter", {})
    runtime_state.setdefault("recent_failures", {})
    runtime_state.setdefault("pending_guidance", [])
    runtime_state.setdefault("last_history_trigger", None)
    runtime_state.setdefault("last_correction_state", None)
    runtime_state.setdefault("last_decision", None)
    runtime_state.setdefault("mode", "advisory")
    runtime_state.setdefault("schema_version", "1.0.0")
    snapshot["correction_runtime_state"] = runtime_state
    snapshot.setdefault("prompt_budget", {})
    snapshot.setdefault("metadata", {})
    snapshot.setdefault("schema_version", "1.0.0")
    snapshot.setdefault("spec_version", "1.0.0")
    snapshot.setdefault("created_at", utc_now_iso())
    snapshot.setdefault("updated_at", snapshot.get("created_at"))
    return snapshot


def normalize_verification_cache_entry(entry: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(entry if isinstance(entry, dict) else {})
    item.setdefault("key", f"verification-cache-{uuid.uuid4().hex[:12]}")
    item.setdefault("tool_name", "unknown")
    item.setdefault("scope", {})
    item.setdefault("config_hash", "")
    item.setdefault("spec_version", "1.0.0")
    item.setdefault("decision", {})
    item.setdefault("created_at", utc_now_iso())
    item.setdefault("expires_at", utc_now_iso())
    item.setdefault("schema_version", "1.0.0")
    return item


def normalize_pattern(record: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    item = deepcopy(record if isinstance(record, dict) else {})
    scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    metadata = deepcopy(metadata)
    metadata_scope = metadata.get("scope") if isinstance(metadata.get("scope"), dict) else {}
    if not scope and metadata_scope:
        scope = deepcopy(metadata_scope)
    tool_name = item.get("toolName") or item.get("tool_name") or item.get("source_tool") or metadata.get("tool_name")
    trigger = item.get("trigger") or metadata.get("trigger")
    source_phase = item.get("source_phase") or metadata.get("source_phase")
    pattern_type = _normalize_pattern_type(item.get("type", item.get("kind")))
    pattern_text = str(item.get("pattern") or item.get("summary") or item.get("title") or "").strip()
    if not pattern_text:
        pattern_text = "Unspecified reusable pattern"
    first_observed = str(item.get("firstObserved") or item.get("first_observed") or item.get("created_at") or now)
    last_observed = str(item.get("lastObserved") or item.get("last_observed") or item.get("updated_at") or item.get("last_confirmed_at") or first_observed)
    evidence_raw = item.get("evidence") if isinstance(item.get("evidence"), list) else []
    fallback_source = str(source_phase or trigger or "legacy_migration")
    fallback_metadata = {"trigger": trigger, "source_phase": source_phase}
    evidence = [
        _normalize_evidence(
            evidence_item,
            fallback_observation=pattern_text,
            fallback_source=fallback_source,
            tool_name=tool_name,
            scope=scope,
            observed_at=last_observed,
            metadata=fallback_metadata,
        )
        for evidence_item in evidence_raw
    ]
    if not evidence:
        evidence = [
            _normalize_evidence(
                {
                    "observation": str(item.get("summary") or item.get("pattern") or pattern_text),
                    "source": fallback_source,
                    "toolName": tool_name,
                    "observedAt": last_observed,
                    "scope": scope,
                    "metadata": fallback_metadata,
                },
                fallback_observation=pattern_text,
                fallback_source=fallback_source,
                tool_name=tool_name,
                scope=scope,
                observed_at=last_observed,
                metadata=fallback_metadata,
            )
        ]
    context_id = str((scope or {}).get("context_id") or metadata.get("context_id") or "")
    storage_layer = _normalize_storage_layer(item.get("storageLayer") or item.get("storage_layer") or metadata.get("storage_layer"), context_id=context_id or None)
    status = _normalize_status(item.get("status") or metadata.get("status") or ("verified" if item.get("last_confirmed_at") else "candidate"))
    title = str(item.get("title") or metadata.get("title") or (trigger or pattern_type).replace("_", " ").title())
    tags = [str(tag) for tag in (item.get("tags") or metadata.get("tags") or []) if str(tag)]
    confidence = round(float(item.get("confidence", 0.75) or 0.75), 3)
    mitigation = item.get("mitigation")
    runtime_derived = (
        str(source_phase or "").lower() == "tool_after"
        or any(str(entry.get("source") or "").lower() in {"tool_result", "verification_guardian", "helper_capture"} for entry in evidence if isinstance(entry, dict))
        or str((evidence[0].get("metadata", {}) if evidence and isinstance(evidence[0], dict) and isinstance(evidence[0].get("metadata", {}), dict) else {}).get("helper") or "").lower() == "patterns"
    )
    if runtime_derived:
        guidance = summarize_pattern_evidence(pattern_type, tool_name, evidence, fallback_text=pattern_text)
        pattern_text = guidance["pattern"]
        mitigation = guidance["mitigation"] or mitigation
        evidence_text = " ".join(str(entry.get("observation") or "") for entry in evidence if isinstance(entry, dict))
        tags = keyword_terms(f"{tool_name or ''} {evidence_text}", tool_name=tool_name, limit=8)
        metadata["evidence_category"] = guidance["category"]
        metadata["strategy"] = guidance["strategy"]
        metadata["strategy_terms"] = list(guidance["strategy_terms"])
        metadata["example_focus"] = list(guidance["example_focus"])
        metadata["evidence_focus_terms"] = list(guidance["example_focus"])
    metadata.setdefault("title", title)
    metadata["tags"] = tags
    metadata.setdefault("scope", deepcopy(scope))
    metadata.setdefault("trigger", trigger)
    metadata.setdefault("source_phase", source_phase)
    metadata.setdefault("tool_name", tool_name)
    metadata.setdefault("context_id", context_id or None)
    metadata.setdefault("cooldown_context_ids", list(metadata.get("cooldown_context_ids", [])) if isinstance(metadata.get("cooldown_context_ids", []), list) else [])
    normalized = {
        "id": str(item.get("id") or f"pattern-{uuid.uuid4().hex[:12]}"),
        "type": pattern_type,
        "pattern": pattern_text,
        "confidence": confidence,
        "firstObserved": first_observed,
        "lastObserved": last_observed,
        "evidence": evidence,
        "mitigation": mitigation,
        "status": status,
        "metadata": metadata,
        "storageLayer": storage_layer,
        "schema_version": "3.0",
        "spec_version": "1.0.0",
        "updated_at": str(item.get("updated_at") or last_observed or now),
        "usage_count": max(1, int(item.get("usage_count", 1) or 1)),
        "kind": _COMPATIBILITY_KIND[pattern_type],
        "summary": str(item.get("summary") or pattern_text),
        "title": title,
        "scope": deepcopy(scope),
        "tags": tags,
        "tool_name": tool_name,
        "source_tool": tool_name,
        "trigger": trigger,
        "source_phase": source_phase,
        "created_at": first_observed,
        "last_confirmed_at": item.get("last_confirmed_at"),
        "decay_score": round(float(item.get("decay_score", 1.0) or 1.0), 4),
    }
    return normalized


def _drop_invalid_documents(schema_name: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for item in items:
        ok, _ = is_valid(schema_name, item)
        if ok:
            valid.append(item)
    return valid


def _normalize_rollup_state(data: Any) -> dict[str, Any]:
    snapshot = deepcopy(data if isinstance(data, dict) else default_rollup_state())
    snapshot.setdefault("version", 3)
    snapshot.setdefault("updated_at", utc_now_iso())
    snapshot["recent_decisions"] = [item for item in snapshot.get("recent_decisions", []) if isinstance(item, dict)]
    snapshot["recent_corrections"] = [item for item in snapshot.get("recent_corrections", []) if isinstance(item, dict)]
    defaults = default_state()["counters"]
    counters = snapshot.get("counters", {}) if isinstance(snapshot.get("counters", {}), dict) else {}
    snapshot["counters"] = {key: int(counters.get(key, value) or value) for key, value in defaults.items()}
    snapshot.pop("patterns", None)
    return snapshot


def _load_rollup_unlocked() -> dict[str, Any]:
    data = _normalize_rollup_state(_read_json(TELEMETRY_ROLLUP_FILE, default_rollup_state()))
    if not data["recent_decisions"] and not data["recent_corrections"] and not any(int(value or 0) for value in data["counters"].values()):
        legacy = _normalize_rollup_state(_read_json(STATE_FILE, default_rollup_state()))
        if legacy["recent_decisions"] or legacy["recent_corrections"] or any(int(value or 0) for value in legacy["counters"].values()):
            data = legacy
    return data


def _save_rollup_unlocked(snapshot: dict[str, Any]) -> dict[str, Any]:
    rollup = _normalize_rollup_state(snapshot)
    rollup["updated_at"] = utc_now_iso()
    _write_json(TELEMETRY_ROLLUP_FILE, rollup)
    _write_json(STATE_FILE, rollup)
    return rollup


def load_rollup() -> dict[str, Any]:
    with _STATE_LOCK:
        ensure_storage()
        return _load_rollup_unlocked()


def save_rollup(snapshot: dict[str, Any]) -> dict[str, Any]:
    with _STATE_LOCK:
        ensure_storage()
        return _save_rollup_unlocked(snapshot)


def _compact_patterns_exact(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    id_index: dict[str, int] = {}
    identity_index: dict[tuple[str, str, str, str, str, str], int] = {}
    for pattern in patterns:
        incoming = normalize_pattern(pattern)
        pattern_id = str(incoming.get("id", ""))
        identity = _pattern_identity(incoming)
        index = id_index.get(pattern_id) if pattern_id else None
        if index is None:
            index = identity_index.get(identity)
        if index is not None:
            compacted[index] = _merge_pattern(compacted[index], incoming)
            merged = compacted[index]
            merged_id = str(merged.get("id", ""))
            if merged_id:
                id_index[merged_id] = index
            identity_index[_pattern_identity(merged)] = index
            continue
        index = len(compacted)
        compacted.append(incoming)
        if pattern_id:
            id_index[pattern_id] = index
        identity_index[identity] = index
    compacted.sort(key=_pattern_sort_key, reverse=True)
    return compacted


def _load_patterns_unlocked(*, limit: int | None = None) -> list[dict[str, Any]]:
    raw_patterns = _read_json(PATTERNS_FILE, [])
    if not isinstance(raw_patterns, list):
        raw_patterns = []
    normalized_patterns = [normalize_pattern(pattern) for pattern in raw_patterns if isinstance(pattern, dict)]
    normalized_patterns = _compact_patterns_exact(normalized_patterns)
    normalized_patterns = _drop_invalid_documents("patterns", normalized_patterns)
    if limit is not None:
        return normalized_patterns[: max(0, int(limit or 0))]
    return normalized_patterns


def load_patterns(*, limit: int | None = None) -> list[dict[str, Any]]:
    with _STATE_LOCK:
        ensure_storage()
        return _load_patterns_unlocked(limit=limit)


def _save_patterns_unlocked(
    patterns: list[dict[str, Any]],
    *,
    max_patterns: int | None = None,
    similarity_threshold: float | None = None,
    update_rollup: bool = True,
) -> list[dict[str, Any]]:
    normalized = [normalize_pattern(pattern) for pattern in patterns if isinstance(pattern, dict)]
    if similarity_threshold is None:
        normalized = _compact_patterns_exact(normalized)
    else:
        normalized = _compact_patterns(normalized, similarity_threshold=similarity_threshold)
    normalized = _drop_invalid_documents("patterns", normalized)
    if max_patterns is not None:
        normalized = normalized[: max(1, int(max_patterns or 1))]
    _write_json(PATTERNS_FILE, normalized)
    if update_rollup:
        rollup = _load_rollup_unlocked()
        rollup.setdefault("counters", {})["patterns_total"] = len(normalized)
        _save_rollup_unlocked(rollup)
    return normalized


def save_patterns(
    patterns: list[dict[str, Any]],
    *,
    max_patterns: int | None = None,
    similarity_threshold: float | None = None,
) -> list[dict[str, Any]]:
    with _STATE_LOCK:
        ensure_storage()
        return _save_patterns_unlocked(
            patterns,
            max_patterns=max_patterns,
            similarity_threshold=similarity_threshold,
            update_rollup=True,
        )


def load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        ensure_storage()
        data = _load_rollup_unlocked()
        data["patterns"] = _load_patterns_unlocked()
        data.setdefault("counters", default_state()["counters"])["patterns_total"] = len(data["patterns"])
        return data


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    with _STATE_LOCK:
        ensure_storage()
        snapshot = deepcopy(state if isinstance(state, dict) else default_state())
        patterns = _save_patterns_unlocked(
            snapshot.get("patterns", []),
            max_patterns=None,
            similarity_threshold=None,
            update_rollup=False,
        )
        snapshot.setdefault("counters", {})["patterns_total"] = len(patterns)
        snapshot["patterns"] = patterns
        _save_rollup_unlocked(snapshot)
        return snapshot


def _append_bounded(items: list[dict[str, Any]], item: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    items.append(item)
    if len(items) > limit:
        del items[:-limit]
    return items


def cleanup_state(state: dict[str, Any], *, retain_days: int = 14, max_patterns: int = 500) -> dict[str, Any]:
    cutoff = utc_now() - timedelta(days=max(1, retain_days))

    def keep(entry: dict[str, Any], keys: tuple[str, ...]) -> bool:
        for key in keys:
            parsed = parse_dt(str(entry.get(key, "")))
            if parsed:
                return parsed >= cutoff
        return True

    state["recent_decisions"] = [item for item in state.get("recent_decisions", []) if keep(item, ("timestamp", "updated_at", "created_at"))][-200:]
    state["recent_corrections"] = [item for item in state.get("recent_corrections", []) if keep(item, ("timestamp", "updated_at", "created_at"))][-150:]
    cleaned_patterns: list[dict[str, Any]] = []
    for pattern in [normalize_pattern(item) for item in state.get("patterns", []) if isinstance(item, dict)]:
        last_seen = parse_dt(str(pattern.get("lastObserved") or pattern.get("updated_at") or ""))
        if last_seen and last_seen < cutoff - timedelta(days=30):
            pattern["status"] = "archived"
        elif last_seen and last_seen < cutoff:
            pattern["status"] = "deprecated"
        pattern["decay_score"] = round(max(0.0, float(pattern.get("decay_score", 1.0)) * 0.98), 4)
        cleaned_patterns.append(pattern)
    cleaned_patterns.sort(key=_pattern_sort_key, reverse=True)
    state["patterns"] = cleaned_patterns[:max(1, max_patterns)]
    return state


def add_decision(record: dict[str, Any], *, retain_limit: int = 200) -> dict[str, Any]:
    item = deepcopy(record)
    item.setdefault("timestamp", utc_now_iso())
    snapshot = load_rollup()
    snapshot["recent_decisions"] = _append_bounded(snapshot.get("recent_decisions", []), item, retain_limit)
    counters = snapshot.setdefault("counters", {})
    counters["decisions_total"] = int(counters.get("decisions_total", 0) or 0) + 1
    if str(item.get("action", "")).lower() == "block":
        counters["rejections_total"] = int(counters.get("rejections_total", 0) or 0) + 1
    save_rollup(snapshot)
    return item


def add_correction(record: dict[str, Any], *, retain_limit: int = 150) -> dict[str, Any]:
    item = deepcopy(record)
    item.setdefault("timestamp", utc_now_iso())
    snapshot = load_rollup()
    snapshot["recent_corrections"] = _append_bounded(snapshot.get("recent_corrections", []), item, retain_limit)
    counters = snapshot.setdefault("counters", {})
    counters["corrections_total"] = int(counters.get("corrections_total", 0) or 0) + 1
    save_rollup(snapshot)
    return item


def _pattern_identity(record: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    scope = record.get("scope", {}) or {}
    metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
    context_id = str(metadata.get("context_id") or scope.get("context_id") or "")
    return (
        str(record.get("type", "")),
        _canonical_pattern_text(str(record.get("pattern", ""))),
        str(record.get("tool_name") or record.get("source_tool") or metadata.get("tool_name") or "").strip().lower(),
        str(scope.get("label", "")).strip().lower(),
        str(record.get("storageLayer", "")).strip().upper(),
        context_id,
    )


def _compact_patterns(patterns: list[dict[str, Any]], *, similarity_threshold: float = 0.97) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    threshold = max(0.0, min(float(similarity_threshold or 0.97), 1.0))
    for pattern in patterns:
        incoming = normalize_pattern(pattern)
        for index, existing in enumerate(compacted):
            same_id = str(existing.get("id", "")) == str(incoming.get("id", ""))
            same_identity = _pattern_identity(existing) == _pattern_identity(incoming)
            similar = _pattern_similarity(existing, incoming) >= threshold
            if same_id or same_identity or similar:
                compacted[index] = _merge_pattern(existing, incoming)
                break
        else:
            compacted.append(incoming)
    compacted.sort(key=_pattern_sort_key, reverse=True)
    return compacted


def _merge_pattern(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    merged = normalize_pattern(existing)
    new_item = normalize_pattern(incoming)
    merged["confidence"] = max(float(merged.get("confidence", 0.0) or 0.0), float(new_item.get("confidence", 0.0) or 0.0))
    merged["firstObserved"] = min(str(merged.get("firstObserved") or now), str(new_item.get("firstObserved") or now))
    merged["lastObserved"] = max(str(merged.get("lastObserved") or now), str(new_item.get("lastObserved") or now))
    merged["updated_at"] = now
    merged["usage_count"] = int(merged.get("usage_count", 1) or 1) + max(1, int(new_item.get("usage_count", 1) or 1))
    merged["status"] = _merge_status(str(merged.get("status", "candidate")), str(new_item.get("status", "candidate")))
    if new_item.get("mitigation"):
        merged["mitigation"] = new_item.get("mitigation")
    existing_evidence = list(merged.get("evidence", []))
    seen = {(str(item.get("observation")), str(item.get("source")), str(item.get("observedAt"))) for item in existing_evidence if isinstance(item, dict)}
    for evidence in new_item.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        identity = (str(evidence.get("observation")), str(evidence.get("source")), str(evidence.get("observedAt")))
        if identity not in seen:
            existing_evidence.append(evidence)
            seen.add(identity)
    merged["evidence"] = existing_evidence
    merged_metadata = merged.get("metadata", {}) if isinstance(merged.get("metadata"), dict) else {}
    incoming_metadata = new_item.get("metadata", {}) if isinstance(new_item.get("metadata"), dict) else {}
    for key, value in incoming_metadata.items():
        if key == "tags":
            current_tags = [str(tag) for tag in merged_metadata.get("tags", []) if str(tag)]
            for tag in [str(tag) for tag in value if str(tag)]:
                if tag not in current_tags:
                    current_tags.append(tag)
            merged_metadata["tags"] = current_tags
        elif key == "cooldown_context_ids":
            current_ids = [str(item) for item in merged_metadata.get("cooldown_context_ids", []) if str(item)]
            for context_id in [str(item) for item in value if str(item)]:
                if context_id not in current_ids:
                    current_ids.append(context_id)
            merged_metadata["cooldown_context_ids"] = current_ids
        elif value not in (None, "", [], {}):
            merged_metadata[key] = deepcopy(value)
    guidance = summarize_pattern_evidence(
        str(merged.get("type") or new_item.get("type") or "improvement"),
        str(merged.get("tool_name") or new_item.get("tool_name") or merged_metadata.get("tool_name") or "") or None,
        merged["evidence"],
        fallback_text=str(new_item.get("summary") or merged.get("summary") or merged.get("pattern")),
    )
    merged["pattern"] = guidance["pattern"]
    merged["summary"] = guidance["pattern"]
    if guidance.get("mitigation"):
        merged["mitigation"] = guidance["mitigation"]
    merged_metadata["evidence_category"] = guidance["category"]
    merged_metadata["evidence_focus_terms"] = guidance["example_focus"]
    merged_metadata["example_focus"] = guidance["example_focus"]
    merged_metadata["strategy"] = guidance["strategy"]
    merged_metadata["strategy_terms"] = guidance["strategy_terms"]
    merged["metadata"] = merged_metadata
    merged["title"] = str(merged_metadata.get("title") or merged.get("title") or merged.get("type", "")).strip()
    merged["tags"] = [str(tag) for tag in merged_metadata.get("tags", []) if str(tag)]
    return normalize_pattern(merged)


def add_pattern(record: dict[str, Any], *, max_patterns: int = 500, similarity_threshold: float = 0.92) -> dict[str, Any]:
    patterns = load_patterns()
    incoming = normalize_pattern(record)
    result = incoming
    for index, existing in enumerate(patterns):
        same_id = str(existing.get("id", "")) == str(incoming.get("id", ""))
        same_identity = _pattern_identity(existing) == _pattern_identity(incoming)
        similar = _pattern_similarity(existing, incoming) >= max(0.0, min(float(similarity_threshold or 0.92), 1.0))
        if same_id or same_identity or similar:
            patterns[index] = _merge_pattern(existing, incoming)
            result = patterns[index]
            break
    else:
        patterns.append(incoming)
    patterns = _compact_patterns(patterns, similarity_threshold=max(0.97, float(similarity_threshold or 0.92)))
    saved = save_patterns(patterns[: max(1, max_patterns)], similarity_threshold=None)
    for item in saved:
        if str(item.get("id", "")) == str(result.get("id", "")):
            return item
        if _pattern_identity(item) == _pattern_identity(result):
            return item
    return result


def get_patterns(
    *,
    pattern_type: str | None = None,
    scope_label: str | None = None,
    statuses: list[str] | None = None,
    storage_layer: str | None = None,
    context_id: str | None = None,
) -> list[dict[str, Any]]:
    patterns = load_patterns()
    if pattern_type:
        normalized_type = _normalize_pattern_type(pattern_type)
        patterns = [pattern for pattern in patterns if str(pattern.get("type", "")) == normalized_type]
    if statuses:
        normalized_statuses = {_normalize_status(status) for status in statuses}
        patterns = [pattern for pattern in patterns if str(pattern.get("status", "")) in normalized_statuses]
    if storage_layer:
        normalized_layer = _normalize_storage_layer(storage_layer, context_id=context_id)
        patterns = [pattern for pattern in patterns if str(pattern.get("storageLayer", "")) == normalized_layer]
    if scope_label:
        scoped = [pattern for pattern in patterns if str((pattern.get("scope") or {}).get("label", "")) == scope_label]
        if scoped:
            patterns = scoped
    if context_id:
        patterns = [
            pattern
            for pattern in patterns
            if str((pattern.get("metadata") or {}).get("context_id") or (pattern.get("scope") or {}).get("context_id") or "") == str(context_id)
            or str(pattern.get("storageLayer", "")) != "L1_SESSION"
        ]
    patterns.sort(key=_pattern_sort_key, reverse=True)
    return patterns


def get_pattern_by_id(pattern_id: str) -> dict[str, Any] | None:
    for pattern in get_patterns():
        if str(pattern.get("id", "")) == str(pattern_id):
            return pattern
    return None


def transition_pattern(pattern_id: str, status: str, *, reason: str | None = None) -> dict[str, Any] | None:
    normalized_status = _normalize_status(status)
    updated: dict[str, Any] | None = None
    patterns: list[dict[str, Any]] = []
    for pattern in load_patterns():
        item = normalize_pattern(pattern)
        if str(item.get("id", "")) == str(pattern_id):
            item["status"] = normalized_status
            item["updated_at"] = utc_now_iso()
            if normalized_status in {"verified", "active"}:
                item["last_confirmed_at"] = item["updated_at"]
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            if reason:
                metadata["transition_reason"] = reason
            item["metadata"] = metadata
            updated = item
        patterns.append(item)
    if updated is None:
        return None
    save_patterns(patterns, similarity_threshold=None)
    return updated


def delete_pattern(pattern_id: str) -> dict[str, Any]:
    patterns = load_patterns()
    before = len(patterns)
    remaining = [normalize_pattern(pattern) for pattern in patterns if str(pattern.get("id", "")) != str(pattern_id)]
    save_patterns(remaining, similarity_threshold=None)
    return {"ok": True, "deleted": len(remaining) != before, "pattern_id": pattern_id}


def clear_patterns() -> dict[str, Any]:
    save_patterns([], similarity_threshold=None)
    return {"ok": True, "patterns_cleared": True}


def append_event(event: dict[str, Any], *, retain_limit: int = 1000) -> dict[str, Any]:
    item = deepcopy(event)
    item.setdefault("id", f"event-{uuid.uuid4().hex[:12]}")
    item.setdefault("timestamp", utc_now_iso())
    ok, _ = is_valid("events", item)
    if not ok:
        item["payload"] = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    with _STATE_LOCK:
        ensure_storage()
        EVENTS_FILE.open("a", encoding="utf-8").write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        lines = EVENTS_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > retain_limit:
            EVENTS_FILE.write_text("\n".join(lines[-retain_limit:]) + "\n", encoding="utf-8")
    return item


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    ensure_storage()
    limit = max(1, min(int(limit or 100), 1000))
    events: list[dict[str, Any]] = []
    for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            event = json.loads(line)
            if is_valid("events", event)[0]:
                events.append(event)
        except Exception:
            pass
    return events


def save_profile_status(status: dict[str, Any]) -> dict[str, Any]:
    ensure_storage()
    normalized = normalize_profile_status(status)
    _write_json(PROFILE_STATUS_FILE, normalized)
    return normalized


def save_profile_status_if_changed(agent: Any | None, status: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_profile_status(status)
    hash_source = deepcopy(normalized)
    hash_source.pop("updated_at", None)
    profile_hash = hashlib.sha256(
        json.dumps(hash_source, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    data = getattr(agent, "data", None) if agent is not None else None
    if isinstance(data, dict) and data.get(_PROFILE_STATUS_HASH_KEY) == profile_hash:
        return normalized

    saved = save_profile_status(normalized)
    if isinstance(data, dict):
        data[_PROFILE_STATUS_HASH_KEY] = profile_hash
    return saved


def load_profile_status() -> dict[str, Any]:
    ensure_storage()
    data = normalize_profile_status(_read_json(PROFILE_STATUS_FILE, {}))
    ok, _ = is_valid("profile_status", data)
    return data if ok else normalize_profile_status({})


def save_checkpoint(checkpoint: dict[str, Any], *, retain_limit: int = 20) -> dict[str, Any]:
    ensure_storage()
    normalized = normalize_checkpoint(checkpoint)
    data = _read_json(CHECKPOINTS_FILE, {"version": 1, "items": []})
    items = [normalize_checkpoint(item) for item in data.setdefault("items", []) if isinstance(item, dict)]
    items.append(normalized)
    items = _drop_invalid_documents("checkpoints", items)
    data["items"] = items[-max(1, retain_limit):]
    _write_json(CHECKPOINTS_FILE, data)
    snapshot = load_rollup()
    snapshot.setdefault("counters", {})["checkpoints_total"] = int(snapshot.setdefault("counters", {}).get("checkpoints_total", 0) or 0) + 1
    save_rollup(snapshot)
    return normalized


def load_checkpoints(limit: int = 20) -> list[dict[str, Any]]:
    ensure_storage()
    data = _read_json(CHECKPOINTS_FILE, {"version": 1, "items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    normalized = [normalize_checkpoint(item) for item in items if isinstance(item, dict)]
    normalized = _drop_invalid_documents("checkpoints", normalized)
    return normalized[-max(1, int(limit or 20)):] if isinstance(normalized, list) else []


def load_verification_cache() -> dict[str, Any]:
    ensure_storage()
    raw = _read_json(VERIFICATION_CACHE_FILE, default_verification_cache())
    if not isinstance(raw, dict):
        raw = default_verification_cache()
    items = [normalize_verification_cache_entry(item) for item in raw.get("items", []) if isinstance(item, dict)]
    stats = raw.get("stats", {}) if isinstance(raw.get("stats", {}), dict) else {}
    return {
        "version": int(raw.get("version", 1) or 1),
        "updated_at": str(raw.get("updated_at") or utc_now_iso()),
        "items": _drop_invalid_documents("verification_cache_entry", items),
        "stats": {
            "hits": int(stats.get("hits", 0) or 0),
            "misses": int(stats.get("misses", 0) or 0),
            "invalidations": int(stats.get("invalidations", 0) or 0),
        },
    }


def save_verification_cache(cache: dict[str, Any]) -> dict[str, Any]:
    ensure_storage()
    data = load_verification_cache()
    if isinstance(cache, dict):
        data["items"] = [normalize_verification_cache_entry(item) for item in cache.get("items", []) if isinstance(item, dict)]
        stats = cache.get("stats", {}) if isinstance(cache.get("stats", {}), dict) else {}
        data["stats"] = {
            "hits": int(stats.get("hits", data["stats"].get("hits", 0)) or 0),
            "misses": int(stats.get("misses", data["stats"].get("misses", 0)) or 0),
            "invalidations": int(stats.get("invalidations", data["stats"].get("invalidations", 0)) or 0),
        }
    data["items"] = _drop_invalid_documents("verification_cache_entry", data["items"])
    data["updated_at"] = utc_now_iso()
    _write_json(VERIFICATION_CACHE_FILE, data)
    return data


def _touch_verification_cache_stat(name: str) -> None:
    cache = load_verification_cache()
    cache["stats"][name] = int(cache["stats"].get(name, 0) or 0) + 1
    save_verification_cache(cache)


def clear_verification_cache() -> dict[str, Any]:
    cache = default_verification_cache()
    cache["stats"]["invalidations"] = 1
    save_verification_cache(cache)
    return {"ok": True, "cache_cleared": True}


def invalidate_verification_cache(*, config_hash: str | None = None, spec_version: str | None = None) -> dict[str, Any]:
    cache = load_verification_cache()
    kept: list[dict[str, Any]] = []
    now = utc_now()
    invalidated = 0
    for item in cache["items"]:
        expires_at = parse_dt(str(item.get("expires_at", "")))
        expired = bool(expires_at and expires_at < now)
        config_mismatch = bool(config_hash and str(item.get("config_hash", "")) != config_hash)
        spec_mismatch = bool(spec_version and str(item.get("spec_version", "")) != spec_version)
        if expired or config_mismatch or spec_mismatch:
            invalidated += 1
            continue
        kept.append(item)
    cache["items"] = kept
    cache["stats"]["invalidations"] = int(cache["stats"].get("invalidations", 0) or 0) + invalidated
    save_verification_cache(cache)
    return {"invalidated": invalidated, "items": kept}


def get_verification_cache_entry(key: str) -> dict[str, Any] | None:
    cache = load_verification_cache()
    now = utc_now()
    for item in cache["items"]:
        if str(item.get("key", "")) != key:
            continue
        expires_at = parse_dt(str(item.get("expires_at", "")))
        if expires_at and expires_at < now:
            invalidate_verification_cache()
            _touch_verification_cache_stat("misses")
            return None
        _touch_verification_cache_stat("hits")
        return item
    _touch_verification_cache_stat("misses")
    return None


def put_verification_cache_entry(entry: dict[str, Any]) -> dict[str, Any]:
    cache = load_verification_cache()
    normalized = normalize_verification_cache_entry(entry)
    kept = [item for item in cache["items"] if str(item.get("key", "")) != normalized["key"]]
    kept.append(normalized)
    cache["items"] = kept
    save_verification_cache(cache)
    return normalized


def verification_cache_stats(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cache = load_verification_cache()
    cfg = config if isinstance(config, dict) else {}
    verification = cfg.get("verification", {}) if isinstance(cfg.get("verification", {}), dict) else {}
    return {
        "cache_enabled": bool(verification.get("cache_enabled", False)),
        "cache_ttl_seconds": int(verification.get("cache_ttl_seconds", 0) or 0),
        "entry_count": len(cache.get("items", [])),
        "stats": cache.get("stats", {}),
        "updated_at": cache.get("updated_at"),
    }


def pattern_stats(*, scope_label: str | None = None) -> dict[str, int]:
    return _compatibility_counts(get_patterns(scope_label=scope_label))


def snapshot() -> dict[str, Any]:
    snap = load_state()
    snap["profile_status"] = load_profile_status()
    snap["recent_events"] = recent_events(50)
    snap["checkpoints"] = load_checkpoints(5)
    snap["verification_cache"] = load_verification_cache()
    return snap
