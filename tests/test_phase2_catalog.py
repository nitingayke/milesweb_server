from app.routers.phase2_router import OPERATIONS, router


def headers(token: str = "test-token-rahul"):
    return {"Authorization": f"Bearer {token}"}


def test_all_42_phase2_get_routes_are_registered_and_respond(client):
    get_paths = {route.path for route in router.routes if "GET" in getattr(route, "methods", set())}
    assert len(OPERATIONS) == 42
    assert {path for _, path in OPERATIONS}.issubset(get_paths)
    replacements = {
        "{org_id}": "org-rahul-001", "{website_id}": "site-rahul-001",
        "{subscription_id}": "5001", "{domain_id}": "domain-rahul-001",
        "{app_id}": "app-rahul-wp-001", "{backup_id}": "9001",
    }
    for _, path in OPERATIONS:
        for placeholder, value in replacements.items():
            path = path.replace(placeholder, value)
        assert client.get(path, headers=headers()).status_code == 200


def test_login_uses_bearer_identity(client):
    response = client.get("/login", headers=headers("test-token-amit"))
    assert response.status_code == 200
    assert response.json()["email"] == "amit@example.com"


def test_customer_can_access_owned_website(client):
    response = client.get("/orgs/org-rahul-001/websites/site-rahul-001", headers=headers())
    assert response.status_code == 200
    assert response.json()["domain"] == "rahulcloud.example"


def test_ftp_users_accepts_rahuls_connector_key_and_bearer_token(client):
    response = client.get(
        "/orgs/org-rahul-001/websites/site-rahul-001/ftp/users",
        headers=headers("test-token-rahul"),
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["account"] == "siteuser"


def test_ftp_users_rejects_a_bearer_token_for_another_customer(client):
    response = client.get(
        "/orgs/org-rahul-001/websites/site-rahul-001/ftp/users",
        headers=headers("test-token-amit"),
    )
    assert response.status_code == 404


def test_customer_cannot_access_another_customers_resources(client):
    assert client.get("/orgs/org-amit-001", headers=headers()).status_code == 404
    assert client.get("/orgs/org-rahul-001/websites/site-amit-001", headers=headers()).status_code == 404


def test_phase2_requires_bearer_token_and_ignores_connector_key(client):
    assert client.get("/login").status_code == 401
    assert client.get("/login", headers={"X-Connector-Key": "test-connector-key"}).status_code == 401
    assert client.get("/login", headers={"Authorization": "Bearer test-token-rahul"}).status_code == 200
    assert client.get(
        "/login",
        headers={"Authorization": "Bearer test-token-rahul", "X-Connector-Key": "arbitrary-key"},
    ).status_code == 200


def test_phase2_routes_are_get_only(client):
    assert client.post("/login", headers=headers()).status_code == 405
    assert client.post("/orgs/org-rahul-001/websites/site-rahul-001", headers=headers()).status_code == 405


def test_swagger_declares_ftp_path_inputs(client):
    operation = client.get("/openapi.json").json()["paths"]["/orgs/{org_id}/websites/{website_id}/ftp/users"]["get"]
    assert {(parameter["name"], parameter["in"]) for parameter in operation["parameters"]} >= {
        ("org_id", "path"),
        ("website_id", "path"),
    }


def test_swagger_declares_bearer_auth_without_connector_key(client):
    schema = client.get("/openapi.json").json()
    schemes = schema["components"]["securitySchemes"]
    assert "ConnectorKeyAuth" not in schemes
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"

    ftp_operation = schema["paths"]["/orgs/{org_id}/websites/{website_id}/ftp/users"]["get"]
    assert ftp_operation["security"] == [{"BearerAuth": []}]
    assert not {(parameter["name"], parameter["in"]) for parameter in ftp_operation["parameters"]} & {
        ("authorization", "header"),
        ("X-Connector-Key", "header"),
    }


def test_user_without_hosting_gets_empty_memberships_not_404(client):
    """Users who have registered but have no active hosting get 200 with empty memberships."""
    response = client.get("/login/memberships", headers=headers("test-token-priya"))
    assert response.status_code == 200
    assert response.json() == {"memberships": []}


def test_user_without_hosting_can_access_login_profile(client):
    response = client.get("/login", headers=headers("test-token-priya"))
    assert response.status_code == 200
    assert response.json()["email"] == "priya@example.com"


def test_user_without_hosting_cannot_access_other_organizations(client):
    assert client.get("/orgs/org-rahul-001", headers=headers("test-token-priya")).status_code == 404
