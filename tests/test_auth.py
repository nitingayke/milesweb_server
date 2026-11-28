"""Tests for single-user Manish Kulkarni authentication, mPanel customer fixtures, and token verification."""

from datetime import timedelta
import json
from pathlib import Path
import pytest

from app.services.token_service import create_access_token


MANISH_EMAIL = "manish.kulkarni@milesweb.com"
MANISH_ORG_ID = "3849700e-95b0-4656-be7b-0d1268598bb1"
PARENT_ORG_ID = "148d9193-102b-4a3e-acde-fe22dfa311d9"
MANISH_CLIENT_ID = "123"
CHINMAY_EMAIL = "chinmay.dingore@milesweb.com"
CHINMAY_ORG_ID = "569e5b5c-b632-4c23-92d5-df0c5378dea2"
DUMMY_PASSWORD = "test-dummy-password"

MPANEL_FIXTURES_PATH = Path(__file__).resolve().parents[1] / "data" / "mpanel_customers.json"

EXPECTED_11_IDS = [
    "569e5b5c-b632-4c23-92d5-df0c5378dea2",
    "3849700e-95b0-4656-be7b-0d1268598bb1",
    "313b5b22-4388-4695-aea4-73baac8b29ff",
    "19b85f01-ffec-45f8-9cda-d972b0833237",
    "8b959a3e-7fcb-4950-891a-920e4e0d110f",
    "e1c091a9-a436-4216-9c1c-47318ff9e002",
    "7edc6420-1de6-4e3e-99ec-d07d6c8848b9",
    "44e6ad20-9abb-4242-b796-b5be5cf28fae",
    "801b15f8-7f4f-44b3-8b87-f190afdfe552",
    "875ac91a-5c7f-4b02-821f-3fc225e7e894",
    "f9e95280-d5a8-499c-a121-35e8ef78884c",
]


def test_mpanel_customer_fixtures_preserve_all_11_records():
    """All 11 mPanel customer records are stored distinctly with parentId and unset missing ownerEmail."""
    data = json.loads(MPANEL_FIXTURES_PATH.read_text(encoding="utf-8"))
    items = data["items"]
    assert data["total"] == 11
    assert len(items) == 11
    assert [item["id"] for item in items] == EXPECTED_11_IDS
    assert len({item["id"] for item in items}) == 11
    assert all(item["parentId"] == PARENT_ORG_ID for item in items)

    # Duplicate names remain distinct records
    assert sum(1 for item in items if item["name"] == "MilesWeb") == 3
    assert sum(1 for item in items if item["name"] == "Chinmay Dingore") == 2

    # Missing ownerEmail fields remain unset
    missing_owner_email_ids = {
        "313b5b22-4388-4695-aea4-73baac8b29ff",
        "44e6ad20-9abb-4242-b796-b5be5cf28fae",
        "f9e95280-d5a8-499c-a121-35e8ef78884c",
    }
    for item in items:
        if item["id"] in missing_owner_email_ids:
            assert "ownerEmail" not in item


def test_login_success_manish_without_connector_key(client):
    """Manish Kulkarni can sign in with DUMMY_LOGIN_PASSWORD and no X-Connector-Key header."""
    response = client.post(
        "/auth/login",
        json={"email": MANISH_EMAIL, "password": DUMMY_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == MANISH_EMAIL
    assert data["org_id"] == MANISH_ORG_ID
    assert data["org_id"] != PARENT_ORG_ID
    assert data["clientId"] == MANISH_CLIENT_ID
    assert isinstance(data["clientId"], str)
    assert data["name"] == "MilesWeb"
    assert data["tokenType"] == "bearer"
    assert len(data["token"]) > 20


def test_login_succeeds_with_arbitrary_connector_key_header(client):
    """Older MCP connectors sending an arbitrary X-Connector-Key header still succeed."""
    response = client.post(
        "/auth/login",
        headers={"X-Connector-Key": "arbitrary-legacy-key"},
        json={"email": MANISH_EMAIL, "password": DUMMY_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == MANISH_EMAIL
    assert data["org_id"] == MANISH_ORG_ID
    assert data["clientId"] == MANISH_CLIENT_ID


def test_login_rejects_wrong_password_for_manish(client):
    """Manish's email with a wrong password is rejected with 401."""
    response = client.post(
        "/auth/login",
        json={"email": MANISH_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_credentials"


@pytest.mark.parametrize(
    "other_email",
    [
        CHINMAY_EMAIL,
        "chinmay_dingore123@yahoo.com",
        "nikhil.palde@milesweb.com",
        "gauravrj123@gmail.com",
        "cristiano@milesweb.co.uk",
        "gaurav.jadhav@milesweb.com",
        "test@test.com",
        "rahul@example.com",
        "amit@example.com",
        "neha@example.com",
        "vikram@example.com",
        "notfound@example.com",
    ],
)
def test_login_rejects_chinmay_other_fixtures_and_old_accounts(client, other_email):
    """Other mPanel fixtures, old Chinmay account, and old seeded users cannot sign in."""
    response = client.post(
        "/auth/login",
        json={"email": other_email, "password": DUMMY_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "user_not_found"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "", "password": DUMMY_PASSWORD},
        {"email": MANISH_EMAIL, "password": "  "},
        {"email": "  ", "password": "  "},
    ],
)
def test_login_rejects_empty_credentials(client, payload):
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "missing_credentials"


def test_auth_me_and_verify_resolve_manish_consistently(client):
    """/auth/me, POST /auth/verify, and GET /auth/verify resolve the same clientId and org_id."""
    login_res = client.post(
        "/auth/login",
        json={"email": MANISH_EMAIL, "password": DUMMY_PASSWORD},
    )
    token = login_res.json()["token"]

    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    profile = me_res.json()
    assert str(profile["clientId"]) == MANISH_CLIENT_ID
    assert profile["name"] == "MilesWeb"
    assert profile["email"] == MANISH_EMAIL
    assert profile["org_id"] == MANISH_ORG_ID
    assert profile["org_id"] != PARENT_ORG_ID

    post_verify = client.post("/auth/verify", json={"token": token})
    assert post_verify.status_code == 200
    post_body = post_verify.json()
    assert post_body["valid"] is True
    assert post_body["clientId"] == MANISH_CLIENT_ID
    assert post_body["email"] == MANISH_EMAIL
    assert post_body["org_id"] == MANISH_ORG_ID
    assert post_body["name"] == "MilesWeb"
    assert "exp" in post_body["claims"]

    get_verify = client.get("/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert get_verify.status_code == 200
    get_body = get_verify.json()
    assert get_body["clientId"] == MANISH_CLIENT_ID
    assert get_body["email"] == MANISH_EMAIL
    assert get_body["org_id"] == MANISH_ORG_ID


def test_old_chinmay_jwt_is_rejected_by_me_and_verify(client):
    """Previously issued Chinmay JWTs are rejected at /auth/me and both /auth/verify endpoints."""
    old_chinmay_token = create_access_token(
        data={
            "sub": CHINMAY_ORG_ID,
            "clientId": CHINMAY_ORG_ID,
            "email": CHINMAY_EMAIL,
            "name": "Chinmay Dingore",
            "org_id": CHINMAY_ORG_ID,
        }
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {old_chinmay_token}"}).status_code == 401
    assert client.post("/auth/verify", json={"token": old_chinmay_token}).status_code == 401
    assert client.get("/auth/verify", headers={"Authorization": f"Bearer {old_chinmay_token}"}).status_code == 401


def test_auth_me_rejects_missing_or_invalid_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer invalid-garbage-token"}).status_code == 401


def test_auth_me_openapi_security(client):
    """OpenAPI schema declares BearerAuth security for /auth/me without ordinary header params."""
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/auth/me"]["get"]
    assert operation["security"] == [{"BearerAuth": []}]
    parameters = operation.get("parameters", [])
    assert not any(p.get("name") == "authorization" for p in parameters)
    schemes = schema["components"]["securitySchemes"]
    assert "BearerAuth" in schemes
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"


def test_verify_endpoint_rejects_expired_token(client):
    """Expired JWT tokens are rejected by the dynamic verification endpoint."""
    expired_token = create_access_token(
        data={"clientId": MANISH_CLIENT_ID, "email": MANISH_EMAIL, "org_id": MANISH_ORG_ID},
        expires_delta=timedelta(seconds=-10),
    )
    verify_res = client.post("/auth/verify", json={"token": expired_token})
    assert verify_res.status_code == 401
    assert "expired" in verify_res.json()["detail"]["message"].lower()
