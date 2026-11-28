"""Dynamic router registering all remaining Enhance API operations from the OpenAPI spec."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.routers.phase2_router import authenticated_client
from app.services.enhance_spec import EnhanceOpSpec, load_missing_enhance_operations
from app.services.enhance_state import EnhanceStateStore, enhance_state
from app.services.phase2_catalog import CatalogBadRequest, CatalogForbidden, CatalogNotFound

router = APIRouter(tags=["Phase 2 Enhance mock"])


def get_enhance_state() -> EnhanceStateStore:
    return enhance_state


def _validate_query_params(op: EnhanceOpSpec, query: dict[str, str]) -> None:
    """Validate query parameters against OpenAPI types and enums."""
    param_map = {p["name"]: p for p in op.query_params}
    for name, value in query.items():
        spec_p = param_map.get(name)
        if not spec_p:
            continue
        schema = spec_p.get("schema") or {}
        ptype = schema.get("type")
        if ptype == "integer":
            try:
                int(value)
            except ValueError as exc:
                raise CatalogBadRequest(f"Query parameter '{name}' must be an integer") from exc
        if "enum" in schema and value not in schema["enum"]:
            raise CatalogBadRequest(f"Invalid value '{value}' for query parameter '{name}'")


async def _parse_and_validate_body(op: EnhanceOpSpec, request: Request) -> Any:
    """Parse JSON request body when present and validate required fields."""
    raw = await request.body()
    if not raw:
        if op.request_body_required:
            raise HTTPException(status_code=422, detail="Request body is required")
        return None
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON request body") from exc

    if op.required_body_fields and isinstance(body, dict):
        if op.operation_id == "validateWebsiteOperation":
            missing = [
                f for f in op.required_body_fields
                if f not in body and not (f == "parameters" and "params" in body)
            ]
        else:
            missing = [f for f in op.required_body_fields if f not in body]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required field(s): {', '.join(missing)}",
            )
    return body


def make_enhance_handler(op: EnhanceOpSpec) -> Callable:
    async def handler(
        request: Request,
        client_id: int = Depends(authenticated_client),
        state: EnhanceStateStore = Depends(get_enhance_state),
    ):
        query_params = dict(request.query_params)
        path_params = dict(request.path_params)

        try:
            _validate_query_params(op, query_params)
        except CatalogBadRequest as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        body = await _parse_and_validate_body(op, request)

        try:
            result = state.handle(op, client_id, path_params, query_params, body)
        except CatalogForbidden as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except CatalogBadRequest as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except CatalogNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        if op.success_status in (302, 303):
            return RedirectResponse(url=op.redirect_location or "https://panel.milesweb.example/sso", status_code=op.success_status)
        if op.success_status == 204 or op.response_media_type is None:
            return Response(status_code=op.success_status)
        if op.response_media_type == "text/html":
            return HTMLResponse(content=str(result), status_code=op.success_status)
        if op.response_media_type == "application/gzip":
            return Response(content=result if isinstance(result, bytes) else b"", media_type="application/gzip", status_code=op.success_status)
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
            return JSONResponse(content=result[1], status_code=result[0])
        return JSONResponse(content=result, status_code=op.success_status)

    handler.__name__ = op.operation_id
    handler.__doc__ = op.summary or f"Mock response for Enhance operation {op.operation_id}."
    return handler


for _op in load_missing_enhance_operations():
    _openapi_params: list[dict[str, Any]] = [
        {"name": p_name, "in": "path", "required": True, "schema": {"type": "string"}}
        for p_name in _op.path_params
    ]
    _openapi_params.extend(_op.query_params)
    route_kwargs: dict[str, Any] = {
        "methods": [_op.method],
        "name": _op.operation_id,
        "status_code": _op.success_status,
        "openapi_extra": {"parameters": _openapi_params} if _openapi_params else None,
    }
    if _op.success_status == 204 or _op.response_media_type is None:
        route_kwargs["response_class"] = Response
    router.add_api_route(
        _op.path,
        make_enhance_handler(_op),
        **route_kwargs,
    )
