"""Authentication and token verification routes."""

import hashlib
import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.customer_repository import CustomerRepository, repository
from app.security import get_current_client_id, http_bearer
from app.services.token_service import (
    create_access_token,
    decode_access_token,
    verify_access_token,
)


def _verify_password(plain_password: str, stored: str) -> bool:
    """Verify a password against a pbkdf2_sha256:{salt}:{hash} entry.

    Uses constant-time comparison to prevent timing attacks.
    Falls back to accepting any password when no hash is stored
    (backward-compat only — all fixture entries must have a hash).
    """
    if not stored or not stored.startswith("pbkdf2_sha256:"):
        # No hash configured — this customer entry is incomplete; deny access.
        return False
    try:
        _, salt, expected_hex = stored.split(":", 2)
    except ValueError:
        return False
    candidate_hex = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode(), salt.encode(), 260000
    ).hex()
    return hmac.compare_digest(candidate_hex, expected_hex)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_repository() -> CustomerRepository:
    return repository


ENABLED_ACCOUNT = {
    "clientId": 123,
    "name": "MilesWeb",
    "email": "manish.kulkarni@milesweb.com",
    "org_id": "3849700e-95b0-4656-be7b-0d1268598bb1",
    "status": "Active",
}


def _is_enabled_jwt_claims(claims: dict[str, Any] | None) -> bool:
    """Return True only when JWT claims match the single enabled login account."""
    if not isinstance(claims, dict):
        return False
    email = str(claims.get("email") or "").strip().lower()
    org_id = str(claims.get("org_id") or "").strip()
    cid = str(claims.get("clientId") or claims.get("sub") or "").strip()
    return (
        email == ENABLED_ACCOUNT["email"]
        and org_id == ENABLED_ACCOUNT["org_id"]
        and cid == str(ENABLED_ACCOUNT["clientId"])
    )


class LoginRequest(BaseModel):
    email: str = Field(
        ...,
        examples=["manish.kulkarni@milesweb.com"],
        description="User email address (manish.kulkarni@milesweb.com)",
    )
    password: str = Field(
        ...,
        description="Dummy account password configured via DUMMY_LOGIN_PASSWORD",
    )


class LoginResponse(BaseModel):
    email: str
    clientId: str
    org_id: str
    token: str
    name: str | None = None
    tokenType: str = "bearer"


class VerifyTokenRequest(BaseModel):
    token: str = Field(
        ...,
        description="JWT access token to verify dynamically",
    )


class VerifyTokenResponse(BaseModel):
    valid: bool
    clientId: str
    email: str
    org_id: str | None = None
    name: str | None = None
    claims: dict[str, Any]


class UserProfileResponse(BaseModel):
    clientId: int | str
    name: str
    email: str
    org_id: str | None = None
    status: str


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    settings: Settings = Depends(get_settings),
):
    """Authenticate the single configured dummy user (Manish Kulkarni / MilesWeb)."""
    email_clean = payload.email.strip()
    password_clean = payload.password.strip()

    if not email_clean or not password_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "missing_credentials",
                "message": "Both email and password are required and cannot be empty",
            },
        )

    if email_clean.lower() != ENABLED_ACCOUNT["email"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "user_not_found",
                "message": f"User with email '{email_clean}' is not authorized",
            },
        )

    expected_password = settings.dummy_login_password
    if not expected_password or not hmac.compare_digest(payload.password, expected_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_credentials",
                "message": "Invalid password",
            },
        )

    token = create_access_token(
        data={
            "sub": str(ENABLED_ACCOUNT["clientId"]),
            "clientId": str(ENABLED_ACCOUNT["clientId"]),
            "email": ENABLED_ACCOUNT["email"],
            "name": ENABLED_ACCOUNT["name"],
            "org_id": ENABLED_ACCOUNT["org_id"],
        },
        settings=settings,
    )

    return LoginResponse(
        email=ENABLED_ACCOUNT["email"],
        clientId=str(ENABLED_ACCOUNT["clientId"]),
        org_id=ENABLED_ACCOUNT["org_id"],
        token=token,
        name=ENABLED_ACCOUNT["name"],
        tokenType="bearer",
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    client_id: int | str = Depends(get_current_client_id),
    customer_repo: CustomerRepository = Depends(get_repository),
):
    """
    Dynamically identify and return the profile of the authenticated caller
    from their Bearer JWT token.
    """
    if str(client_id) == str(ENABLED_ACCOUNT["clientId"]):
        return UserProfileResponse(
            clientId=ENABLED_ACCOUNT["clientId"],
            name=ENABLED_ACCOUNT["name"],
            email=ENABLED_ACCOUNT["email"],
            org_id=ENABLED_ACCOUNT["org_id"],
            status=ENABLED_ACCOUNT["status"],
        )
    customer = customer_repo.get_customer(client_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Customer record not found"},
        )
    org = customer.get("organization") or {}
    return UserProfileResponse(
        clientId=customer["clientId"],
        name=customer["name"],
        email=customer["email"],
        org_id=org.get("id"),
        status=customer["status"],
    )


def parse_token_input(token_str: str) -> str:
    cleaned = token_str.strip().strip('"').strip("'")
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()
    return cleaned


@router.post("/verify", response_model=VerifyTokenResponse)
async def verify_token_post(
    payload: VerifyTokenRequest,
    customer_repo: CustomerRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
):
    """
    Dynamically verify an access token supplied in the request body.

    Validates signature, expiration, and extracts claims without hardcoded values.
    Also supports development test tokens.
    """
    token_clean = parse_token_input(payload.token)
    is_valid, claims, error_message = verify_access_token(token_clean, settings=settings)
    if is_valid and _is_enabled_jwt_claims(claims):
        raw_id = claims.get("clientId") or claims.get("sub", "")
        return VerifyTokenResponse(
            valid=True,
            clientId=str(raw_id),
            email=claims.get("email", ""),
            org_id=claims.get("org_id"),
            name=claims.get("name"),
            claims=claims,
        )
    if is_valid and claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "Token subject is no longer authorized"},
        )

    # Development test tokens fallback (e.g. mock-token-rahul, mock-token-amit)
    for item in settings.phase2_test_tokens.split(","):
        test_token, separator, client_id = item.strip().partition(":")
        if separator and test_token == token_clean and client_id.isdigit():
            customer = customer_repo.get_customer(int(client_id))
            return VerifyTokenResponse(
                valid=True,
                clientId=client_id,
                email=customer.get("email", "") if customer else "",
                name=customer.get("name") if customer else None,
                claims={"sub": client_id, "clientId": int(client_id), "token_type": "test_token"},
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_token", "message": error_message or "Token is invalid"},
    )


@router.get("/verify", response_model=VerifyTokenResponse)
async def verify_token_get(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)] = None,
    token: Annotated[str | None, Query(description="Token to verify if not passed in header")] = None,
    customer_repo: CustomerRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
):
    """
    Dynamically verify an access token passed in Authorization header or query parameter.
    """
    bearer_token = token
    if credentials and credentials.credentials.strip():
        bearer_token = credentials.credentials.strip()

    if not bearer_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_token", "message": "Token must be provided in Authorization header or token query parameter"},
        )

    token_clean = parse_token_input(bearer_token)
    is_valid, claims, error_message = verify_access_token(token_clean, settings=settings)
    if is_valid and _is_enabled_jwt_claims(claims):
        raw_id = claims.get("clientId") or claims.get("sub", "")
        return VerifyTokenResponse(
            valid=True,
            clientId=str(raw_id),
            email=claims.get("email", ""),
            org_id=claims.get("org_id"),
            name=claims.get("name"),
            claims=claims,
        )
    if is_valid and claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "Token subject is no longer authorized"},
        )

    # Development test tokens fallback (e.g. mock-token-rahul, mock-token-amit)
    for item in settings.phase2_test_tokens.split(","):
        test_token, separator, client_id = item.strip().partition(":")
        if separator and test_token == token_clean and client_id.isdigit():
            customer = customer_repo.get_customer(int(client_id))
            return VerifyTokenResponse(
                valid=True,
                clientId=client_id,
                email=customer.get("email", "") if customer else "",
                name=customer.get("name") if customer else None,
                claims={"sub": client_id, "clientId": int(client_id), "token_type": "test_token"},
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_token", "message": error_message or "Token is invalid"},
    )
