from __future__ import annotations

from collections import Counter
from typing import Any
import re

from usr.plugins.cognition_layers.helpers.policy import bounded_text


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{2,}")
_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "after", "before", "about", "around", "while",
    "tool", "tools", "agent", "agents", "plan", "retry", "retries", "retrying", "pause", "check", "checked",
    "recheck", "assumptions", "input", "inputs", "output", "outputs", "response", "responses", "result", "results",
    "returned", "returning", "return", "using", "used", "direct", "directly", "successful", "success", "succeeds",
    "succeeded", "failure", "failed", "failing", "error", "errors", "invalid", "validation", "similar", "request",
    "requests", "narrow", "narrower", "focus", "focused", "specific", "single", "clean", "cleaner", "completed",
    "complete", "completion", "without", "because", "then", "they", "them", "their", "there", "here", "when",
    "work", "worked", "works", "best", "kind", "interaction", "interactions", "query", "queries", "search", "read",
    "file", "files", "call", "calls", "step", "steps", "matched", "match", "expected", "shape", "schema",
    "message", "messages", "headline", "headlines", "snippet", "snippets", "broad", "roundup", "usable", "can",
    "now", "what", "main", "more", "updated", "latest", "current", "today", "yesterday", "tomorrow",
}
_UPPER_TOKENS = {"api", "csv", "dns", "html", "http", "https", "json", "llm", "pdf", "sql", "url", "xml", "yaml"}
_ENTITY_HINTS = {
    "anthropic", "chatgpt", "claude", "copilot", "deepseek", "gemini", "google", "gpt", "grok", "llama", "meta",
    "microsoft", "openai", "opus", "perplexity", "sonnet", "xai",
}
_FEATURE_HINTS = {
    "accuracy", "capability", "capabilities", "feature", "features", "generation", "latency", "limits", "mode",
    "modes", "performance", "price", "pricing", "quality", "reasoning", "setting", "settings", "speed", "support",
    "supports", "vision",
}
_UPDATE_HINTS = {"announced", "announcement", "launch", "launched", "news", "release", "released", "update", "updates"}
_STRUCTURE_HINTS = {"column", "columns", "field", "fields", "format", "json", "schema", "structured", "yaml"}
_PATH_HINTS = {"branch", "commit", "directory", "file", "function", "identifier", "module", "path", "paths"}
_SOURCE_HINTS = {"article", "blog", "press", "reuters", "source", "sources", "verge", "www"}
_ERROR_MESSAGES = {
    "policy": "policy blocks or verification rejections",
    "validation": "validation or invalid-input errors",
    "not_found": "not-found errors",
    "denied": "permission or access errors",
    "timeout": "timeout or stall failures",
    "network": "network or connectivity failures",
    "parse": "format or parsing errors",
    "rate_limit": "rate-limit or quota failures",
    "generic": "similar failures",
}
_ERROR_MITIGATIONS = {
    "policy": "Change the plan or inputs before retrying, and do not repeat a blocked call unchanged.",
    "validation": "Validate the inputs before retrying and narrow the request to the minimum needed.",
    "not_found": "Verify the target path, identifier, or query before retrying.",
    "denied": "Re-check permissions or access assumptions before retrying with a narrower request.",
    "timeout": "Reduce the scope or amount of work before retrying.",
    "network": "Re-check connectivity and endpoint assumptions before retrying.",
    "parse": "Tighten the expected format or output shape before retrying.",
    "rate_limit": "Wait or reduce request volume before retrying.",
    "generic": "Change the plan or inputs before retrying the tool.",
}
_STRATEGY_PHRASES = {
    "specific_named_entities": "specific company, product, or model names",
    "specific_product_features": "specific product features",
    "model_capabilities": "model capabilities",
    "recent_updates": "recent updates or release news",
    "targeted_source_keywords": "targeted source or article keywords",
    "explicit_output_shape": "explicit output shapes or named fields",
    "specific_paths_or_identifiers": "specific paths or identifiers",
}


def _tool_terms(tool_name: str | None) -> set[str]:
    return {token.lower() for token in re.split(r"[^A-Za-z0-9]+", str(tool_name or "")) if token}


def _display_term(token: str, raw: str) -> str:
    cleaned = raw.replace("_", " ").replace("-", " ").strip()
    if token in _UPPER_TOKENS:
        return token.upper()
    return cleaned if cleaned else token


def _join_parts(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _entries(evidence: list[Any] | None, fallback_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in evidence or []:
        if hasattr(item, "to_dict"):
            payload = item.to_dict()
        elif isinstance(item, dict):
            payload = dict(item)
        else:
            payload = {"observation": str(item or "")}
        items.append(payload)
    if items:
        return items
    return [{"observation": str(fallback_text or ""), "metadata": {}}]


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text or "")]


def _is_urlish_token(token: str) -> bool:
    lowered = str(token or "").strip().lower()
    if not lowered:
        return True
    if "/" in lowered:
        return True
    if lowered in {"http", "https", "www", "com", "org", "net", "io", "ai", "co"}:
        return True
    if lowered.startswith(("http", "www", "com.", "org.", "net.")):
        return True
    if re.search(r"\.(com|org|net|io|ai|co)(?:$|[.-])", lowered):
        return True
    if lowered.count("-") >= 3 and any(ch.isdigit() for ch in lowered):
        return True
    return False


def _looks_like_model_name(token: str) -> bool:
    compact = token.lower().replace(" ", "-")
    return bool(re.search(r"\d", compact) and any(hint in compact for hint in _ENTITY_HINTS)) or compact.startswith(("gpt-", "claude-", "gemini-"))


def keyword_terms(text: str, *, tool_name: str | None = None, limit: int = 12, extra_stop: set[str] | None = None) -> list[str]:
    stop = set(_STOP_WORDS) | _tool_terms(tool_name)
    if extra_stop:
        stop |= {str(item).strip().lower() for item in extra_stop if str(item).strip()}
    counts: Counter[str] = Counter()
    for token in _tokens(text):
        if len(token) < 3 or token in stop or _is_urlish_token(token):
            continue
        counts[token] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[:limit]]


def _focus_terms(entries: list[dict[str, Any]], tool_name: str | None, *, limit: int = 4) -> list[str]:
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    blocked = _STOP_WORDS | _tool_terms(tool_name)
    for item in entries:
        for match in _WORD_RE.finditer(str(item.get("observation") or "")):
            raw = match.group(0)
            token = raw.lower()
            if token in blocked or len(token) < 3 or _is_urlish_token(token):
                continue
            weight = 1
            if "-" in raw or _looks_like_model_name(token):
                weight += 2
            if token in _ENTITY_HINTS or token in _FEATURE_HINTS:
                weight += 1
            counts[token] += weight
            first_seen.setdefault(token, raw)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [_display_term(token, first_seen.get(token, token)) for token, _ in ranked[:limit]]


def _strategy_topics(text: str, tool_name: str | None, example_focus: list[str]) -> list[str]:
    lowered_tool = str(tool_name or "").lower()
    tokens = set(_tokens(text))
    focus_tokens = {token.lower().replace(" ", "-") for token in example_focus if str(token).strip()}
    topics: list[str] = []

    if _STRUCTURE_HINTS & tokens:
        topics.append("explicit_output_shape")
    if _PATH_HINTS & tokens:
        topics.append("specific_paths_or_identifiers")
    if _FEATURE_HINTS & tokens:
        topics.append("specific_product_features")
    if any(token in tokens for token in {"capability", "capabilities", "reasoning", "vision", "support", "supports"}):
        topics.append("model_capabilities")
    if _UPDATE_HINTS & tokens or any(marker in text for marker in ["http://", "https://"]):
        topics.append("recent_updates")
    if _SOURCE_HINTS & tokens or any(marker in text for marker in ["http://", "https://", ".com/"]):
        topics.append("targeted_source_keywords")
    if (_ENTITY_HINTS & tokens) or any(token in _ENTITY_HINTS or _looks_like_model_name(token) for token in focus_tokens):
        topics.append("specific_named_entities")
    if "search" in lowered_tool:
        topics.insert(0, "targeted_keywords")
    else:
        topics.insert(0, "narrow_scope")
    deduped: list[str] = []
    for topic in topics:
        if topic not in deduped:
            deduped.append(topic)
    return deduped


def _strategy_phrase(strategy_terms: list[str]) -> str:
    phrases = [_STRATEGY_PHRASES[term] for term in strategy_terms if term in _STRATEGY_PHRASES][:2]
    return _join_parts(phrases)


def _primary_strategy(category: str, strategy_terms: list[str]) -> str:
    if category == "targeted_results" and "targeted_keywords" in strategy_terms:
        return "targeted_keywords"
    if "explicit_output_shape" in strategy_terms:
        return "explicit_output_shape"
    if "specific_product_features" in strategy_terms:
        return "specific_feature_query"
    if "recent_updates" in strategy_terms and "specific_named_entities" in strategy_terms:
        return "targeted_update_query"
    if "specific_paths_or_identifiers" in strategy_terms:
        return "specific_identifiers"
    if category == "error":
        return "recover_from_failure"
    return "narrow_scope"


def _success_category(text: str, tool_name: str | None) -> str:
    lowered_tool = str(tool_name or "").lower()
    if "expected shape" in text or "matched the expected" in text or "structured" in text or "schema" in text:
        return "structured_output"
    if "search" in lowered_tool or "search result" in text or "search results" in text or "snippet" in text:
        return "targeted_results"
    if "focused" in text or "narrow" in text or "specific" in text or "single" in text:
        return "focused_plan"
    if "without error" in text or "without errors" in text or "no errors" in text or "completed" in text:
        return "clean_completion"
    return "generic"


def _error_category(entries: list[dict[str, Any]], text: str) -> str:
    for item in entries:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        if str(metadata.get("policy_action") or "").lower() in {"block", "warn"}:
            return "policy"
    if "rate limit" in text or "quota" in text or "too many requests" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text or "deadline" in text or "took too long" in text:
        return "timeout"
    if "not found" in text or "missing" in text or "does not exist" in text or "no such file" in text or "404" in text:
        return "not_found"
    if "policy" in text or "blocked" in text or "verification rejected" in text:
        return "policy"
    if "permission" in text or "denied" in text or "forbidden" in text or "unauthorized" in text or "rejected" in text or "403" in text:
        return "denied"
    if "validation" in text or "invalid" in text or "bad request" in text or "malformed" in text:
        return "validation"
    if "parse" in text or "parsing" in text or "decode" in text or "json" in text or "yaml" in text or "format" in text:
        return "parse"
    if "network" in text or "connection" in text or "dns" in text or "socket" in text or "unreachable" in text or "host" in text:
        return "network"
    return "generic"


def derive_query_strategy_terms(text: str, tool_name: str | None) -> list[str]:
    lowered = str(text or "").lower()
    example_focus = _focus_terms([{"observation": lowered}], tool_name, limit=4)
    return _strategy_topics(lowered, tool_name, example_focus)


def summarize_pattern_evidence(
    pattern_type: str,
    tool_name: str | None,
    evidence: list[Any] | None,
    *,
    fallback_text: str = "",
    max_chars: int = 220,
) -> dict[str, Any]:
    items = _entries(evidence, fallback_text)
    text = " ".join(str(item.get("observation") or "") for item in items).lower()
    example_focus = _focus_terms(items, tool_name)
    strategy_terms = _strategy_topics(text, tool_name, example_focus)
    strategy_phrase = _strategy_phrase([term for term in strategy_terms if term not in {"narrow_scope", "targeted_keywords"}])
    tool = str(tool_name or "the tool")

    if pattern_type == "error":
        category = _error_category(items, text)
        problem = _ERROR_MESSAGES[category]
        error_strategy_terms = list(strategy_terms)
        if category == "validation" and "validate_inputs" not in error_strategy_terms:
            error_strategy_terms.append("validate_inputs")
        if category == "not_found" and "verify_identifiers" not in error_strategy_terms:
            error_strategy_terms.append("verify_identifiers")
        if category == "denied" and "check_permissions" not in error_strategy_terms:
            error_strategy_terms.append("check_permissions")
        if category == "policy":
            pattern = f"When {tool} is blocked by policy or verification, change the plan or inputs before retrying."
        elif "specific_paths_or_identifiers" in strategy_terms:
            pattern = f"When {tool} hits {problem}, re-check the paths, identifiers, or requested fields before retrying."
        elif category == "generic":
            pattern = f"If {tool} returns a similar failure, pause, re-check assumptions, then retry with a narrower plan."
        else:
            pattern = f"When {tool} hits {problem}, re-check the inputs or assumptions before retrying with a narrower request."
        mitigation = _ERROR_MITIGATIONS[category]
        return {
            "pattern": bounded_text(pattern, max_chars=max_chars),
            "mitigation": bounded_text(mitigation, max_chars=max_chars),
            "category": category,
            "strategy": "recover_from_failure",
            "strategy_terms": error_strategy_terms,
            "example_focus": example_focus,
        }

    category = _success_category(text, tool_name)
    if category == "structured_output" or "explicit_output_shape" in strategy_terms:
        pattern = f"Successful {tool} runs worked best when the request asked for explicit output shapes or named fields."
        mitigation = f"Keep {tool} requests explicit about the output shape when the topic changes."
    elif category == "targeted_results":
        if strategy_phrase:
            pattern = f"Successful {tool} runs worked best with targeted keywords about {strategy_phrase} rather than broad overview queries."
        else:
            pattern = f"Successful {tool} runs worked best with targeted keywords rather than broad overview queries."
        mitigation = f"Keep {tool} queries anchored to specific keywords instead of broad overview phrasing."
    elif strategy_phrase:
        pattern = f"Successful {tool} runs worked best with narrowly scoped requests about {strategy_phrase}."
        mitigation = f"Keep {tool} requests anchored to {strategy_phrase} instead of broad recaps when the topic changes."
    else:
        pattern = f"Successful {tool} runs worked best when the request stayed narrowly scoped instead of asking for a broad overview."
        mitigation = "Prefer the narrower successful strategy when the same tool/task shape recurs."
    return {
        "pattern": bounded_text(pattern, max_chars=max_chars),
        "mitigation": bounded_text(mitigation, max_chars=max_chars),
        "category": category,
        "strategy": _primary_strategy(category, strategy_terms),
        "strategy_terms": strategy_terms,
        "example_focus": example_focus,
    }
