from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import json

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PLUGIN_ROOT / "data_schema"


@lru_cache(maxsize=32)
def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _fallback_validate(schema: dict[str, Any], document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(document, dict):
        return ["document is not an object"]
    if isinstance(document, dict):
        for key in schema.get("required", []) or []:
            if key not in document:
                errors.append(f"missing required field: {key}")
    return errors


def validate_document(name: str, document: Any) -> list[str]:
    schema = load_schema(name)
    if not schema:
        return []
    try:
        from jsonschema import Draft202012Validator
    except Exception:
        return _fallback_validate(schema, document)
    validator = Draft202012Validator(schema)
    return sorted(error.message for error in validator.iter_errors(document))


def is_valid(name: str, document: Any) -> tuple[bool, list[str]]:
    errors = validate_document(name, document)
    return not errors, errors
