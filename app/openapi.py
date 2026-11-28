"""OpenAPI additions for the Phase 2 MCP-to-backend authentication contract."""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def install_openapi_security(app: FastAPI) -> None:
    """Describe the existing runtime authentication without changing its checks."""
    original_openapi = app.openapi

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        # Use FastAPI's generated schema first so every existing route keeps
        # its normal metadata, then add documentation-only security metadata.
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Bearer JWT issued by POST /auth/login (or configured dev test token).",
        }

        for path, path_item in schema.get("paths", {}).items():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                tags = operation.get("tags", [])
                if "Phase 2 Enhance mock" in tags or "Customer connector" in tags or path == "/auth/me":
                    operation["security"] = [{"BearerAuth": []}]
                    if "parameters" in operation:
                        operation["parameters"] = [
                            p for p in operation["parameters"] if p.get("name", "").lower() != "authorization"
                        ]

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi
