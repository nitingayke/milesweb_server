"""Comprehensive HTTP tests for all 440 newly added Enhance API operations,
ownership/permission enforcement, input validation, and stateful CRUD flows.
"""

import re
import pytest

from app.routers import enhance_router, phase2_router
from app.services.enhance_spec import (
    load_missing_enhance_operations,
    load_raw_spec,
    normalize_path,
    synthesize_from_schema,
)


def headers(token: str = "test-token-rahul") -> dict[str, str]:
    return {"X-Connector-Key": "test-connector-key", "Authorization": f"Bearer {token}"}


RAHUL_PATH_PARAMS = {
    "org_id": "org-rahul-001",
    "customer_org_id": "org-rahul-001",
    "website_id": "site-rahul-001",
    "websiteId": "site-rahul-001",
    "subscription_id": "5001",
    "domain_id": "domain-rahul-001",
    "domain_name": "rahulcloud.example",
    "domain": "rahulcloud.example",
    "app_id": "app-rahul-wp-001",
    "backup_id": "9001",
    "clone_id": "clone-rahul-001",
    "member_id": "login-vikram-001",
    "login_id": "login-rahul-001",
    "email_address": "hello@rahulcloud.example",
    "deployment_id": "deploy-rahul-001",
    "deploy_id": "deploy-rahul-001",
    "record_id": "dns-001",
    "db_name": "site_db",
    "db_id": "db-001",
    "username": "site_user",
    "key_id": "ssh-001",
    "server_id": "srv-mock-01",
    "plan_id": "1",
    "user_id": "user-001",
    "name": "default",
    "setting_kind": "general",
    "setting_key": "theme",
    "interface": "eth0",
    "role": "application",
    "ip": "198.51.100.42",
    "group_id": "grp-default",
    "session_id": "sess-001",
    "cloudflare_key": "cf-key-001",
    "repo_owner": "rahul",
    "repo_name": "cloud-site",
    "token_id": "tok-001",
    "wp_option": "blogname",
    "autoresponder_id": "ar-rahul-001",
    "plugin": "akismet",
    "theme": "twentytwentyfour",
    "invite_id": "inv-001",
    "migrationId": "mig-001",
    "import_migration_id": "imp-001",
    "import_migration_kind": "cpanel",
    "provider_id": "prov-001",
}


def _resolve_path(path: str) -> str:
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return RAHUL_PATH_PARAMS.get(key, "mock-id-001")

    return re.sub(r"\{([^}]+)\}", _sub, path)


def test_enhance_route_inventory_matches_spec_minus_excluded_auth():
    spec = load_raw_spec()
    missing_ops = load_missing_enhance_operations()
    assert len(missing_ops) == 440

    registered_enhance = {
        (m, normalize_path(r.path))
        for rtr in (phase2_router.router, enhance_router.router)
        for r in rtr.routes
        for m in getattr(r, "methods", set())
        if m in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    # 58 Phase 2 GETs + 440 newly added Enhance operations = 498
    assert len(registered_enhance) == 498
    assert ("POST", "/mpanel/token") not in registered_enhance
    assert len(spec["paths"]) == 316


@pytest.mark.parametrize("op", load_missing_enhance_operations(), ids=lambda o: f"{o.method}:{o.path}")
def test_every_new_enhance_operation_responds_with_expected_status_and_type(client, op):
    url = _resolve_path(op.path)
    # Use specific valid IDs for postgresql / ftp / joomla routes where needed
    if "/postgresql-dbs/" in op.path:
        url = url.replace("/site_db", "/site_postgres")
    if "/postgresql-users/" in op.path:
        url = url.replace("/site_user", "/site_pg_user")
    if "/ftp/users/" in op.path:
        url = url.replace("/site_user", "/siteuser")
    if "/joomla/" in op.path:
        url = url.replace("app-rahul-wp-001", "app-rahul-joomla-001")

    raw_spec = load_raw_spec()
    req_kwargs: dict = {"headers": headers("test-token-rahul"), "follow_redirects": False}
    if op.request_body_schema is not None or op.request_body_required:
        body = synthesize_from_schema(raw_spec, op.request_body_schema)
        if isinstance(body, dict) and op.required_body_fields:
            for req_field in op.required_body_fields:
                body.setdefault(req_field, "mock-value")
        if op.path == "/orgs/{org_id}/websites" and op.method == "DELETE":
            body = {"ids": ["site-rahul-001"]}
        req_kwargs["json"] = body

    resp = client.request(op.method, url, **req_kwargs)
    assert resp.status_code == op.success_status, f"{op.method} {url} -> {resp.status_code} {resp.text}"

    if op.success_status == 204 or op.response_media_type is None:
        assert resp.content == b""
    elif op.response_media_type == "application/json" and op.response_schema:
        expected_type = op.response_schema.get("type")
        parsed = resp.json()
        if expected_type == "string":
            assert isinstance(parsed, str)
        elif expected_type == "array":
            assert isinstance(parsed, list)
        elif expected_type == "object":
            assert isinstance(parsed, dict)
        elif expected_type == "boolean":
            assert isinstance(parsed, bool)


class TestEnhanceSecurityAndValidation:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("POST", "/orgs/org-rahul-001/websites"),
            ("POST", "/orgs/org-rahul-001/websites/site-rahul-001/domains"),
            ("PATCH", "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-zone"),
            ("DELETE", "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example"),
            ("GET", "/servers"),
        ],
    )
    def test_missing_headers_return_401(self, client, method, path):
        assert client.request(method, path).status_code == 401
        assert client.request(method, path, headers={"X-Connector-Key": "test-connector-key"}).status_code == 401

    @pytest.mark.parametrize(
        "method,path,payload",
        [
            ("POST", "/orgs/org-rahul-001/websites", {"domain": "hack.example", "subscriptionId": 5001}),
            ("POST", "/orgs/org-rahul-001/websites/site-rahul-001/domains", {"domain": "hack.example"}),
            ("POST", "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/emails", {"username": "x"}),
            (
                "POST",
                "/orgs/org-rahul-001/websites/clone",
                {
                    "sourceWebsiteId": "site-rahul-001",
                    "excludePaths": [],
                    "deleteFilesFromDestination": False,
                    "syncPhpVersion": True,
                },
            ),
            ("DELETE", "/orgs/org-rahul-001/members/login-vikram-001", None),
        ],
    )
    def test_cross_organization_access_returns_404(self, client, method, path, payload):
        kwargs = {"headers": headers("test-token-amit")}
        if payload is not None:
            kwargs["json"] = payload
        assert client.request(method, path, **kwargs).status_code == 404

    @pytest.mark.parametrize(
        "method,path,payload",
        [
            ("GET", "/servers", None),
            ("GET", "/settings", None),
            ("POST", "/orgs/org-rahul-001/members", {"loginId": "login-new-001", "roles": ["SiteAccess"]}),
            ("DELETE", "/orgs/org-rahul-001/members/login-vikram-001", None),
            ("POST", "/orgs/org-rahul-001/websites", {"domain": "blocked.example", "subscriptionId": 5001}),
        ],
    )
    def test_non_admin_member_gets_403_on_admin_routes(self, client, method, path, payload):
        kwargs = {"headers": headers("test-token-vikram")}
        if payload is not None:
            kwargs["json"] = payload
        assert client.request(method, path, **kwargs).status_code == 403

    def test_invalid_inputs_return_400_or_422(self, client):
        # Invalid JSON body -> 400
        bad_json = client.post(
            "/orgs/org-rahul-001/websites",
            headers={**headers(), "Content-Type": "application/json"},
            content="{not-json",
        )
        assert bad_json.status_code == 400

        # Missing required body fields -> 422
        missing_fields = client.post("/orgs/org-rahul-001/websites", headers=headers(), json={})
        assert missing_fields.status_code == 422

        # Invalid integer query param -> 400
        bad_query = client.get("/servers?limit=notanint", headers=headers())
        assert bad_query.status_code == 400

        # Missing resource -> 404
        missing_res = client.delete(
            "/orgs/org-rahul-001/websites/site-rahul-001/mysql-dbs/nonexistent_db",
            headers=headers(),
        )
        assert missing_res.status_code == 404


class TestStatefulCrudAndAsyncFlows:
    def test_website_create_read_update_delete_flow(self, client):
        # Create
        created = client.post(
            "/orgs/org-rahul-001/websites",
            headers=headers(),
            json={"domain": "newblog.example", "subscriptionId": 5001},
        )
        assert created.status_code == 201
        new_id = created.json()["id"]

        # Read list & detail
        listed = client.get("/orgs/org-rahul-001/websites", headers=headers()).json()
        assert any(w["id"] == new_id and w["domain"] == "newblog.example" for w in listed["items"])
        detail = client.get(f"/orgs/org-rahul-001/websites/{new_id}", headers=headers())
        assert detail.status_code == 200
        assert detail.json()["domain"] == "newblog.example"

        # Update
        updated = client.patch(
            f"/orgs/org-rahul-001/websites/{new_id}",
            headers=headers(),
            json={"status": "suspended"},
        )
        assert updated.status_code == 204
        assert client.get(f"/orgs/org-rahul-001/websites/{new_id}", headers=headers()).json()["status"] == "suspended"

        # Delete
        deleted = client.request(
            "DELETE",
            "/orgs/org-rahul-001/websites",
            headers=headers(),
            json={"ids": [new_id]},
        )
        assert deleted.status_code == 204
        assert client.get(f"/orgs/org-rahul-001/websites/{new_id}", headers=headers()).status_code == 404

    def test_email_and_autoresponder_crud_flow(self, client):
        base = "/orgs/org-rahul-001/websites/site-rahul-001/emails"
        created = client.post(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/emails",
            headers=headers(),
            json={"username": "billing"},
        )
        assert created.status_code == 201

        assert any(m["address"] == "billing@rahulcloud.example" for m in client.get(base, headers=headers()).json()["items"])

        # Update mailbox
        upd = client.patch(
            f"{base}/billing@rahulcloud.example",
            headers=headers(),
            json={"aliases": ["accounts@rahulcloud.example"]},
        )
        assert upd.status_code == 200
        assert client.get(f"{base}/billing@rahulcloud.example", headers=headers()).json()["aliases"] == ["accounts@rahulcloud.example"]

        # Create/Update/Delete autoresponder
        ar_post = client.post(
            f"{base}/billing@rahulcloud.example/autoresponder",
            headers=headers(),
            json={"startDate": "2026-12-01", "enabled": True, "subject": "Billing OOO", "body": "Back soon"},
        )
        assert ar_post.status_code == 201
        assert client.get(f"{base}/billing@rahulcloud.example/autoresponder", headers=headers()).json()["enabled"] is True

        assert client.delete(f"{base}/billing@rahulcloud.example/autoresponder", headers=headers()).status_code == 204
        assert client.get(f"{base}/billing@rahulcloud.example/autoresponder", headers=headers()).json()["enabled"] is False

        # Delete mailbox
        assert client.delete(f"{base}/billing@rahulcloud.example", headers=headers()).status_code == 204
        assert client.get(f"{base}/billing@rahulcloud.example", headers=headers()).status_code == 404

    def test_dns_record_and_mysql_crud_flow(self, client):
        zone_url = "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-zone"
        rec_created = client.post(
            f"{zone_url}/records",
            headers=headers(),
            json={"kind": "TXT", "name": "_dmarc", "value": "v=DMARC1; p=none", "ttl": 300},
        )
        assert rec_created.status_code == 201
        rec_id = rec_created.json()["id"]
        assert any(r["id"] == rec_id for r in client.get(zone_url, headers=headers()).json()["records"])

        assert client.patch(
            f"{zone_url}/records/{rec_id}",
            headers=headers(),
            json={"kind": "TXT", "name": "_dmarc", "value": "v=DMARC1; p=quarantine", "ttl": 600},
        ).status_code == 204
        assert client.delete(f"{zone_url}/records/{rec_id}", headers=headers()).status_code == 204
        assert not any(r["id"] == rec_id for r in client.get(zone_url, headers=headers()).json()["records"])

        # MySQL DB create -> list -> delete
        db_url = "/orgs/org-rahul-001/websites/site-rahul-001/mysql-dbs"
        assert client.post(db_url, headers=headers(), json={"name": "app_analytics"}).status_code == 201
        assert any(d["name"] == "app_analytics" for d in client.get(db_url, headers=headers()).json()["items"])
        assert client.delete(f"{db_url}/app_analytics", headers=headers()).status_code == 204
        assert not any(d["name"] == "app_analytics" for d in client.get(db_url, headers=headers()).json()["items"])

    def test_async_clone_and_git_deploy_flows(self, client):
        clone_resp = client.post(
            "/orgs/org-rahul-001/websites/clone",
            headers=headers(),
            json={
                "sourceWebsiteId": "site-rahul-001",
                "excludePaths": [],
                "deleteFilesFromDestination": False,
                "syncPhpVersion": True,
            },
        )
        assert clone_resp.status_code == 201
        clone_id = clone_resp.json()["id"]

        clone_detail = client.get(f"/orgs/org-rahul-001/websites/clone/{clone_id}", headers=headers()).json()
        assert clone_detail["status"] == "queued"
        clone_log = client.get(f"/orgs/org-rahul-001/websites/clone/{clone_id}/log", headers=headers()).json()
        assert len(clone_log) == 3

        clone_list = client.get("/orgs/org-rahul-001/websites/clone", headers=headers()).json()
        assert any(c["id"] == clone_id for c in clone_list["items"])
        assert client.delete(f"/orgs/org-rahul-001/websites/clone/{clone_id}", headers=headers()).status_code == 405

        deploy_resp = client.post(
            "/orgs/org-rahul-001/websites/site-rahul-001/git",
            headers=headers(),
            json={"branch": "release"},
        )
        assert deploy_resp.status_code == 200
        deploys = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/git/deploys",
            headers=headers(),
        ).json()["items"]
        new_deploy = next(d for d in deploys if d.get("branch") == "release")
        assert new_deploy["status"] == "queued"
        assert "Queued deployment" in client.get(
            f"/orgs/org-rahul-001/websites/site-rahul-001/git/deploys/{new_deploy['id']}",
            headers=headers(),
        ).json()
