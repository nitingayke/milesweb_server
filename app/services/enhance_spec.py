"""OpenAPI specification loader, validator, and schema-driven response synthesizer
for the Enhance API mock server.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

SPEC_PATH = Path(__file__).resolve().parents[2] / "enhance-api-reference-updated.json"
EXCLUDED_AUTH_OPS = {("POST", "/auth/login"), ("POST", "/mpanel/token")}
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def normalize_path(path: str) -> str:
    """Normalize OpenAPI path parameter names for set comparison."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


@dataclass(frozen=True)
class EnhanceOpSpec:
    """Normalized metadata for a single Enhance API operation."""

    operation_id: str
    method: str
    path: str
    tags: tuple[str, ...]
    summary: str
    path_params: tuple[str, ...]
    query_params: tuple[dict[str, Any], ...]
    required_body_fields: tuple[str, ...]
    request_body_schema: dict[str, Any] | None
    request_body_required: bool
    success_status: int
    response_media_type: str | None
    response_schema: dict[str, Any] | None
    response_example: Any
    redirect_location: str | None = None


def _resolve_ref(spec: dict[str, Any], obj: Any, seen: set[str] | None = None) -> dict[str, Any]:
    """Resolve local JSON pointer $ref into components."""
    if not isinstance(obj, dict):
        return {}
    ref = obj.get("$ref")
    if not ref or not isinstance(ref, str) or not ref.startswith("#/"):
        return obj
    seen = seen or set()
    if ref in seen:
        return {}
    seen = seen | {ref}
    cur: Any = spec
    for part in ref[2:].split("/"):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return {}
    if isinstance(cur, dict) and "$ref" in cur:
        return _resolve_ref(spec, cur, seen)
    return cur if isinstance(cur, dict) else {}


def _extract_parameters(spec: dict[str, Any], path_item: dict[str, Any], op: dict[str, Any]) -> list[dict[str, Any]]:
    """Combine path-level and operation-level parameters with $ref resolution."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*(path_item.get("parameters") or []), *(op.get("parameters") or [])]:
        p = _resolve_ref(spec, raw)
        name = p.get("name")
        loc = p.get("in")
        if name and loc:
            schema = _resolve_ref(spec, p.get("schema") or {})
            merged[(loc, name)] = {
                "name": name,
                "in": loc,
                "required": bool(p.get("required", False)),
                "schema": schema,
            }
    return list(merged.values())


def _pick_success_response(spec: dict[str, Any], op: dict[str, Any]) -> tuple[int, str | None, dict[str, Any] | None, Any, str | None]:
    """Pick the primary success status code, media type, schema, and example."""
    responses = op.get("responses") or {}
    # Prefer 201 for POST creates if present, else 200, 202, 204, or redirect 302/303.
    preferred_order = ("201", "200", "202", "204", "206", "302", "303")
    chosen_code: str | None = None
    for code in preferred_order:
        if code in responses:
            chosen_code = code
            break
    if chosen_code is None:
        for code in sorted(responses):
            if code.startswith(("2", "3")):
                chosen_code = code
                break
    if chosen_code is None:
        return 200, "application/json", None, None, None

    status_int = int(chosen_code)
    resp_obj = _resolve_ref(spec, responses[chosen_code])
    if status_int in (302, 303):
        return status_int, None, None, None, "https://panel.milesweb.example/sso"

    content = resp_obj.get("content") or {}
    if not content:
        return status_int, None, None, None, None

    if "application/json" in content:
        media_type = "application/json"
    else:
        media_type = next(iter(content.keys()))

    media_obj = content[media_type]
    raw_schema = media_obj.get("x-expanded-schema") or media_obj.get("schema")
    schema = _resolve_ref(spec, raw_schema) if isinstance(raw_schema, dict) else None
    example = media_obj.get("example")
    return status_int, media_type, schema, example, None


def synthesize_from_schema(
    spec: dict[str, Any],
    schema: dict[str, Any] | None,
    example: Any = None,
    overrides: dict[str, Any] | None = None,
    depth: int = 0,
) -> Any:
    """Synthesize a schema-valid JSON value from an OpenAPI schema/example."""
    if example is not None and overrides is None and depth == 0:
        # Use example directly when it already matches the top-level schema type
        if schema is None:
            return example
        stype = schema.get("type")
        if (
            (stype == "object" and isinstance(example, dict))
            or (stype == "array" and isinstance(example, list))
            or (stype == "string" and isinstance(example, str))
            or (stype == "boolean" and isinstance(example, bool))
            or (stype in ("integer", "number") and isinstance(example, (int, float)))
        ):
            return example

    if not schema or depth > 5:
        return {} if example is None else example

    schema = _resolve_ref(spec, schema)

    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged: dict[str, Any] = {}
        for sub in schema["allOf"]:
            val = synthesize_from_schema(spec, sub, None, None, depth + 1)
            if isinstance(val, dict):
                merged.update(val)
        if overrides:
            merged.update(overrides)
        return merged

    if "oneOf" in schema and isinstance(schema["oneOf"], list) and schema["oneOf"]:
        return synthesize_from_schema(spec, schema["oneOf"][0], None, overrides, depth + 1)

    if "anyOf" in schema and isinstance(schema["anyOf"], list) and schema["anyOf"]:
        return synthesize_from_schema(spec, schema["anyOf"][0], None, overrides, depth + 1)

    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]

    stype = schema.get("type")
    if stype == "string":
        fmt = schema.get("format", "")
        if fmt == "uuid":
            return "00000000-0000-4000-8000-000000000001"
        if fmt == "date-time":
            return "2026-11-27T10:00:00Z"
        if fmt == "date":
            return "2026-11-27"
        if fmt == "email":
            return "mock@rahulcloud.example"
        if fmt == "uri":
            return "https://rahulcloud.example"
        if fmt == "ipv4":
            return "198.51.100.42"
        if "default" in schema:
            return schema["default"]
        return example if isinstance(example, str) else "ok"

    if stype == "integer":
        return schema.get("default", example if isinstance(example, int) else 1)

    if stype == "number":
        return schema.get("default", example if isinstance(example, (int, float)) else 1.0)

    if stype == "boolean":
        return schema.get("default", example if isinstance(example, bool) else True)

    if stype == "array":
        if isinstance(example, list) and depth == 0:
            return example
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            item_val = synthesize_from_schema(spec, items_schema, None, None, depth + 1)
            return [item_val]
        return []

    if stype == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        out: dict[str, Any] = {}
        ex_dict = example if isinstance(example, dict) else {}
        for k, prop_schema in props.items():
            if k in ex_dict and overrides is None:
                out[k] = ex_dict[k]
            else:
                out[k] = synthesize_from_schema(spec, prop_schema, ex_dict.get(k), None, depth + 1)
        if not out and isinstance(example, dict):
            out.update(example)
        if overrides:
            out.update(overrides)
        return out

    return example if example is not None else {}


@lru_cache(maxsize=1)
def load_raw_spec() -> dict[str, Any]:
    """Load the Enhance OpenAPI JSON file once."""
    with SPEC_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def route_sort_key(op: EnhanceOpSpec) -> tuple[int, tuple[tuple[int, str], ...], str]:
    """Sort static path segments before parameterized segments so Starlette matches cleanly."""
    segments = [seg for seg in op.path.strip("/").split("/") if seg]
    seg_key = tuple((1 if seg.startswith("{") else 0, seg) for seg in segments)
    return (-len(segments), seg_key, op.method)


@lru_cache(maxsize=1)
def load_missing_enhance_operations() -> tuple[EnhanceOpSpec, ...]:
    """Return all Enhance operations not already registered by phase2_router or excluded auth."""
    from app.routers.phase2_router import EXTRA_OPERATIONS, OPERATIONS

    existing_keys = {
        ("GET", normalize_path(path))
        for _, path in [*EXTRA_OPERATIONS, *OPERATIONS]
    }
    spec = load_raw_spec()
    ops: list[EnhanceOpSpec] = []

    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        norm = normalize_path(path)
        for method_lower, op_obj in path_item.items():
            method = method_lower.upper()
            if method not in HTTP_METHODS or not isinstance(op_obj, dict):
                continue
            if (method, norm) in existing_keys or (method, path) in EXCLUDED_AUTH_OPS:
                continue

            params = _extract_parameters(spec, path_item, op_obj)
            path_params = tuple(re.findall(r"\{([^}]+)\}", path))
            query_params = tuple(p for p in params if p["in"] == "query")

            req_body = _resolve_ref(spec, op_obj.get("requestBody") or {})
            req_required = bool(req_body.get("required", False))
            req_schema: dict[str, Any] | None = None
            req_fields: tuple[str, ...] = ()
            req_content = req_body.get("content") or {}
            if "application/json" in req_content:
                raw_req_schema = req_content["application/json"].get("x-expanded-schema") or req_content["application/json"].get("schema")
                if isinstance(raw_req_schema, dict):
                    req_schema = _resolve_ref(spec, raw_req_schema)
                    req_fields = tuple(req_schema.get("required") or [])

            status_code, media_type, resp_schema, resp_example, redirect_loc = _pick_success_response(spec, op_obj)

            ops.append(
                EnhanceOpSpec(
                    operation_id=op_obj.get("operationId") or f"{method.lower()}_{norm}",
                    method=method,
                    path=path,
                    tags=tuple(op_obj.get("tags") or ()),
                    summary=op_obj.get("summary") or "",
                    path_params=path_params,
                    query_params=query_params,
                    required_body_fields=req_fields,
                    request_body_schema=req_schema,
                    request_body_required=req_required,
                    success_status=status_code,
                    response_media_type=media_type,
                    response_schema=resp_schema,
                    response_example=resp_example,
                    redirect_location=redirect_loc,
                )
            )

    ops.sort(key=route_sort_key)
    return tuple(ops)
