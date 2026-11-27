from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.openapi import install_openapi_security
from app.routers import auth_router, customer_router, enhance_router, phase2_router, whmcs_router

app = FastAPI(
    title="MilesWeb Enhance Mock Control Panel & OAuth 2.1 Server",
    description="Mock implementation of Enhance org domain & plan endpoints and MCP OAuth 2.1 Authorization Server.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(customer_router.router)
app.include_router(phase2_router.router)
app.include_router(enhance_router.router)
app.include_router(whmcs_router.router)
install_openapi_security(app)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}
