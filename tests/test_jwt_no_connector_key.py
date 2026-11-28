"""Regression tests verifying JWT-only authentication without X-Connector-Key."""

import os

import pytest

MANISH_EMAIL = "manish.kulkarni@milesweb.com"
MANISH_ORG_ID = "3849700e-95b0-4656-be7b-0d1268598bb1"
MANISH_CLIENT_ID = "123"


def _login_as_manish(client) -> str:
    resp = client.post(
        "/auth/login",
        json={"email": MANISH_EMAIL, "password": os.environ["DUMMY_LOGIN_PASSWORD"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["clientId"] == MANISH_CLIENT_ID
    assert body["org_id"] == MANISH_ORG_ID
    return body["token"]


def test_fresh_jwt_accesses_enhance_and_connector_routes_without_key(client):
    token = _login_as_manish(client)
    jwt_only = {"Authorization": f"Bearer {token}"}
    jwt_with_extra_key = {
        "Authorization": f"Bearer {token}",
        "X-Connector-Key": "stale-or-arbitrary-connector-key",
    }

    for hdrs in (jwt_only, jwt_with_extra_key):
        login_resp = client.get("/login", headers=hdrs)
        assert login_resp.status_code == 200
        assert login_resp.json()["email"] == MANISH_EMAIL
        assert login_resp.json()["name"] == "MilesWeb"

        memberships_resp = client.get("/login/memberships", headers=hdrs)
        assert memberships_resp.status_code == 200
        memberships = memberships_resp.json()["memberships"]
        assert len(memberships) == 1
        assert memberships[0]["orgId"] == MANISH_ORG_ID
        assert memberships[0]["orgName"] == "MilesWeb"

        org_resp = client.get(f"/orgs/{MANISH_ORG_ID}", headers=hdrs)
        assert org_resp.status_code == 200
        assert org_resp.json()["id"] == MANISH_ORG_ID
        assert org_resp.json()["ownerEmail"] == MANISH_EMAIL

        cust_resp = client.get("/api/v1/connector/customer", headers=hdrs)
        assert cust_resp.status_code == 200
        assert cust_resp.json()["data"] == {
            "clientId": 123,
            "name": "MilesWeb",
            "email": MANISH_EMAIL,
            "status": "Active",
        }

        cust_explicit = client.get("/api/v1/connector/customer?clientId=123", headers=hdrs)
        assert cust_explicit.status_code == 200
        assert cust_explicit.json()["data"]["clientId"] == 123

        assert client.get("/api/v1/connector/customer/hosting-services", headers=hdrs).status_code == 200
        assert client.get("/api/v1/connector/customer/domains", headers=hdrs).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/login",
        "/login/memberships",
        f"/orgs/{MANISH_ORG_ID}",
        "/api/v1/connector/customer",
        "/api/v1/connector/customer/hosting-services",
        "/api/v1/connector/customer/domains",
    ],
)
def test_missing_or_invalid_jwt_is_rejected_even_with_connector_key(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Connector-Key": "any-key"}).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer not-a-valid-jwt"}).status_code == 401


def test_fresh_jwt_cannot_access_another_customers_data(client):
    token = _login_as_manish(client)
    hdrs = {"Authorization": f"Bearer {token}"}

    assert client.get("/orgs/org-rahul-001", headers=hdrs).status_code == 404
    assert client.get("/api/v1/connector/customer?clientId=12345", headers=hdrs).status_code == 403
    assert client.get("/api/v1/connector/customer/hosting-services?clientId=12345", headers=hdrs).status_code == 403
    assert client.get("/api/v1/connector/customer/domains?clientId=12345", headers=hdrs).status_code == 403
