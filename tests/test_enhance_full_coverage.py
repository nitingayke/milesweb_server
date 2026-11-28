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
    return {"Authorization": f"Bearer {token}"}


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
    "repo_owner": "rahul-studio",
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
    if op.path == "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}" and op.method == "DELETE":
        url = url.replace("domain-rahul-001", "domain-rahul-002")

    raw_spec = load_raw_spec()
    req_kwargs: dict = {"headers": headers("test-token-rahul"), "follow_redirects": False}
    if op.request_body_schema is not None or op.request_body_required:
        body = synthesize_from_schema(raw_spec, op.request_body_schema)
        if isinstance(body, dict) and op.required_body_fields:
            for req_field in op.required_body_fields:
                body.setdefault(req_field, "mock-value")
        if op.path == "/orgs/{org_id}/websites" and op.method == "DELETE":
            body = {"ids": ["site-rahul-001"]}
        if op.path == "/orgs/{org_id}/websites/{website_id}/git" and op.method == "PUT":
            body = {
                "repoOwner": "rahul-studio",
                "repoName": "cloud-site",
                "branchOrTagName": "main",
                "refKind": "branch",
                "autoDeploy": False,
            }
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
        assert client.get(f"{base}/billing@rahulcloud.example/autoresponder", headers=headers()).status_code == 404

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
        assert clone_detail["status"] == "complete"
        clone_log = client.get(f"/orgs/org-rahul-001/websites/clone/{clone_id}/log", headers=headers()).json()
        assert len(clone_log) == 3

        clone_list = client.get("/orgs/org-rahul-001/websites/clone", headers=headers()).json()
        assert any(c["id"] == clone_id for c in clone_list["items"])
        websites = client.get("/orgs/org-rahul-001/websites", headers=headers()).json()["items"]
        assert any(w["id"] == clone_detail["destWebsiteId"] for w in websites)
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


class TestTranscriptWorkflowRegressions:
    def test_git_repos_refs_connect_readback_and_disconnect(self, client):
        repos = client.get("/orgs/org-rahul-001/github/repos", headers=headers()).json()
        assert len(repos) == 1
        assert repos[0]["full_name"] == "rahul-studio/cloud-site"

        refs = client.get("/orgs/org-rahul-001/github/repositories/rahul-studio/cloud-site/refs", headers=headers()).json()
        assert "main" in refs["branches"]
        assert "v1.0.0" in refs["tags"]

        # New site starts disconnected
        new_site = client.post(
            "/orgs/org-rahul-001/websites",
            headers=headers(),
            json={"domain": "git-test.example", "subscriptionId": 5001},
        ).json()["id"]
        assert client.get(f"/orgs/org-rahul-001/websites/{new_site}/git", headers=headers()).json()["connected"] is False

        # Connect -> read back -> disconnect
        conn = client.put(
            f"/orgs/org-rahul-001/websites/{new_site}/git",
            headers=headers(),
            json={
                "repoOwner": "rahul-studio",
                "repoName": "cloud-site",
                "branchOrTagName": "v1.0.0",
                "refKind": "tag",
                "autoDeploy": False,
            },
        )
        assert conn.status_code == 200
        git_info = client.get(f"/orgs/org-rahul-001/websites/{new_site}/git", headers=headers()).json()
        assert git_info["connected"] is True
        assert git_info["branchOrTagName"] == "v1.0.0"

        assert client.delete(f"/orgs/org-rahul-001/websites/{new_site}/git", headers=headers()).status_code == 200
        assert client.get(f"/orgs/org-rahul-001/websites/{new_site}/git", headers=headers()).json()["connected"] is False

    def test_domain_alias_create_list_detail_primary_switch_and_delete(self, client):
        base = "/orgs/org-rahul-001/websites/site-rahul-001/domains"
        alias_resp = client.post(base, headers=headers(), json={"domain": "alias-test.example", "kind": "alias"})
        assert alias_resp.status_code == 201
        alias_id = alias_resp.json()["id"]

        listed = client.get(base, headers=headers()).json()["items"]
        assert any(d["id"] == alias_id and d["domain"] == "alias-test.example" and d["mappingKind"] == "alias" for d in listed)

        detail = client.get(f"{base}/{alias_id}", headers=headers()).json()
        assert detail["domain"] == "alias-test.example"
        assert detail["mappingKind"] == "alias"

        # Primary cannot be deleted
        assert client.delete(f"{base}/domain-rahul-001", headers=headers()).status_code == 400

        # Delete alias -> gone, primary intact
        assert client.delete(f"{base}/{alias_id}", headers=headers()).status_code == 204
        listed_after = client.get(base, headers=headers()).json()["items"]
        assert not any(d["id"] == alias_id for d in listed_after)
        assert any(d["id"] == "domain-rahul-001" and d["mappingKind"] == "primary" for d in listed_after)

    def test_website_reads_wp_node_preview_validate_and_backup_tree(self, client):
        # WordPress app shape & v2 endpoints
        apps = client.get("/orgs/org-rahul-001/websites/site-rahul-001/apps", headers=headers()).json()["items"]
        wp = next(a for a in apps if a["id"] == "app-rahul-wp-001")
        assert wp["app"] == "wordpress"
        assert wp["type"] == "wordpress"

        assert client.get("/v2/apps/app-rahul-wp-001/wordpress/url", headers=headers()).json() == "https://rahulcloud.example"
        assert client.get("/v2/apps/app-rahul-wp-001/wordpress/maintenance-mode", headers=headers()).json() == "deactivated"
        assert client.put("/v2/apps/app-rahul-wp-001/wordpress/maintenance-mode", headers=headers(), json="activate").status_code == 200
        assert client.get("/v2/apps/app-rahul-wp-001/wordpress/maintenance-mode", headers=headers()).json() == "active"

        # Node versions (seeded vs empty on new site)
        assert client.get("/websites/site-rahul-001/apps/node/versions", headers=headers()).json() == ["20.18.0", "22.11.0"]
        new_site = client.post(
            "/orgs/org-rahul-001/websites",
            headers=headers(),
            json={"domain": "node-empty.example", "subscriptionId": 5001},
        ).json()["id"]
        assert client.get(f"/websites/{new_site}/apps/node/versions", headers=headers()).json() == []

        # Preview domain is realistic (not "string")
        preview = client.post(f"/orgs/org-rahul-001/websites/{new_site}/preview", headers=headers())
        assert preview.status_code == 201
        assert preview.json().endswith(".preview.milesweb.example")

        # validateWebsiteOperation accepts 'params'
        val = client.post(
            f"/orgs/org-rahul-001/websites/{new_site}/validate-operation",
            headers=headers(),
            json={"operation": "changeSubscription", "params": {"subscriptionId": 5001}},
        )
        assert val.status_code == 200
        assert val.json()["result"] is True

        # Backup directory tree is internally consistent
        tree = client.get("/orgs/org-rahul-001/websites/site-rahul-001/backups/9001/directory_tree", headers=headers()).json()
        root_node = next(n for n in tree if n["rel_path"] == "public_html")
        assert root_node["node_type"] == "directory"
        file_node = next(n for n in tree if n["rel_path"] == "public_html/wordpress/index.php")
        assert file_node["node_type"] == "file"
        assert file_node["size"] == 405
        assert file_node["permissions"] == "0644"

    def test_ssl_per_domain_and_backup_restore_and_profile_persistence(self, client):
        # domain-rahul-001 has cert, domain-rahul-002 has none until issued
        c1 = client.get("/v2/domains/domain-rahul-001/ssl", headers=headers())
        assert c1.status_code == 200
        assert c1.json()["cn"] == "rahulcloud.example"

        assert client.get("/v2/domains/domain-rahul-002/ssl", headers=headers()).status_code == 404
        assert client.post("/v2/domains/domain-rahul-002/letsencrypt", headers=headers()).status_code == 201
        c2 = client.get("/v2/domains/domain-rahul-002/ssl", headers=headers()).json()
        assert c2["cn"] == "extra.rahulcloud.example"
        assert c2["forceHttps"] is False

        assert client.put("/v2/domains/domain-rahul-002/ssl/force_ssl", headers=headers(), json=True).status_code == 200
        assert client.get("/v2/domains/domain-rahul-002/ssl", headers=headers()).json()["forceHttps"] is True

        # Backup excluding emails -> restore excluding emails -> emailsStatus != successful
        bak = client.post(
            "/orgs/org-rahul-001/websites/site-rahul-001/backups?includeEmails=false",
            headers=headers(),
        ).json()
        assert bak["emailsStatus"] == "skipped"
        assert client.get("/orgs/org-rahul-001/websites/site-rahul-001/status/backup", headers=headers()).json()["id"] == bak["id"]

        assert client.put(
            f"/orgs/org-rahul-001/websites/site-rahul-001/backups/{bak['id']}",
            headers=headers(),
            json={"restoreFiles": True, "restoreDatabases": [], "restoreEmails": []},
        ).status_code == 200
        rst = client.get(
            f"/orgs/org-rahul-001/websites/site-rahul-001/backups/{bak['id']}/restore_status",
            headers=headers(),
        ).json()
        assert rst["homeDirStatus"] == "successful"
        assert rst["emailsStatus"] == "skipped"

        # Profile update persists on /login and /members
        upd = client.patch("/login", headers=headers(), json={"name": "Rahul Updated"})
        assert upd.status_code == 200
        assert upd.json()["verifyPin"] is False
        assert client.get("/login", headers=headers()).json()["name"] == "Rahul Updated"
        members = client.get("/orgs/org-rahul-001/members", headers=headers()).json()["items"]
        assert any(m["id"] == "login-rahul-001" and m["name"] == "Rahul Updated" for m in members)


class TestNehaEndToEndWorkflows:
    def test_neha_fixtures_subs_sites_wp_node_github_and_backups(self, client):
        h = headers("test-token-neha")

        # 2 subscriptions (5003, 5004) & 2 websites (site-neha-001 suspended, site-neha-002 active)
        subs = client.get("/orgs/org-neha-001/subscriptions", headers=h).json()["items"]
        assert {s["id"] for s in subs} == {5003, 5004}

        sites = client.get("/orgs/org-neha-001/websites", headers=h).json()["items"]
        assert {s["id"]: s["status"] for s in sites} == {
            "site-neha-001": "suspended",
            "site-neha-002": "active",
        }

        # WordPress consistency on site-neha-001 & site-neha-002
        for sid, aid, expected_url in [
            ("site-neha-001", "app-neha-wp-001", "https://nehastore.example"),
            ("site-neha-002", "app-neha-wp-002", "https://neha-mcp-disposable.example"),
        ]:
            apps = client.get(f"/orgs/org-neha-001/websites/{sid}/apps", headers=h).json()["items"]
            wp = next(a for a in apps if a["id"] == aid)
            assert wp["kind"] == "wordpress" and wp["app"] == "wordpress" and wp["type"] == "wordpress"
            assert client.get(f"/v2/apps/{aid}/wordpress/url", headers=h).json() == expected_url
            assert client.get(f"/v2/apps/{aid}/wordpress/maintenance-mode", headers=h).json() == "deactivated"

        # Toggle maintenance mode on disposable site-neha-002
        assert client.put("/v2/apps/app-neha-wp-002/wordpress/maintenance-mode", headers=h, json="activate").status_code == 200
        assert client.get("/v2/apps/app-neha-wp-002/wordpress/maintenance-mode", headers=h).json() == "active"

        # Node versions: populated on site-neha-001, explicit empty on site-neha-002
        assert client.get("/websites/site-neha-001/apps/node/versions", headers=h).json() == ["18.20.4", "20.18.0"]
        assert client.get("/websites/site-neha-002/apps/node/versions", headers=h).json() == []

        # GitHub repo & refs for org-neha-001
        repos = client.get("/orgs/org-neha-001/github/repos", headers=h).json()
        assert len(repos) == 1
        assert repos[0]["full_name"] == "neha-demo/bakery-site"
        assert repos[0]["private"] is False
        refs = client.get("/orgs/org-neha-001/github/repositories/neha-demo/bakery-site/refs", headers=h).json()
        assert refs == {"branches": ["main", "staging"], "tags": ["v1.0.0"]}

        # Backup tree on site-neha-001 backup 9001
        tree = client.get("/orgs/org-neha-001/websites/site-neha-001/backups/9001/directory_tree", headers=h).json()
        assert tree[0]["name"] == "public_html" and tree[0]["node_type"] == "directory"
        assert tree[2]["rel_path"] == "public_html/wordpress/index.php" and tree[2]["node_type"] == "file"

    def test_neha_disposable_site_git_domains_ssl_mail_backup_clone_and_profile(self, client):
        h = headers("test-token-neha")

        # Git disconnected -> connect -> deploy -> disconnect
        assert client.get("/orgs/org-neha-001/websites/site-neha-002/git", headers=h).json()["connected"] is False
        assert client.put(
            "/orgs/org-neha-001/websites/site-neha-002/git",
            headers=h,
            json={"repoOwner": "neha-demo", "repoName": "bakery-site", "branchOrTagName": "main", "refKind": "branch", "autoDeploy": False},
        ).status_code == 200
        assert client.post("/orgs/org-neha-001/websites/site-neha-002/git", headers=h, json={}).status_code == 200
        deploys = client.get("/orgs/org-neha-001/websites/site-neha-002/git/deploys", headers=h).json()["items"]
        assert len(deploys) == 1
        deploy_id = deploys[0]["id"]
        assert deploy_id in client.get(f"/orgs/org-neha-001/websites/site-neha-002/git/deploys/{deploy_id}", headers=h).json()

        # validateWebsiteOperation changeSubscription to 5004
        val = client.post(
            "/orgs/org-neha-001/websites/site-neha-002/validate-operation",
            headers=h,
            json={"operation": "changeSubscription", "params": {"subscriptionId": 5004}},
        )
        assert val.status_code == 200 and val.json()["result"] is True

        # Preview domain
        prev = client.post("/orgs/org-neha-001/websites/site-neha-002/preview", headers=h)
        assert prev.status_code == 201 and prev.json() == "site-neha-002.preview.milesweb.example"

        # SSL: store site has cert, disposable site has NO cert (cannot inherit store cert) until issued
        assert client.get("/v2/domains/domain-neha-001/ssl", headers=h).json()["cn"] == "nehastore.example"
        assert client.get("/v2/domains/domain-neha-002/ssl", headers=h).status_code == 404
        assert client.post("/v2/domains/domain-neha-002/letsencrypt", headers=h).status_code == 201
        cert2 = client.get("/v2/domains/domain-neha-002/ssl", headers=h).json()
        assert cert2["cn"] == "neha-mcp-disposable.example" and cert2["forceHttps"] is False
        assert client.put("/v2/domains/domain-neha-002/ssl/force_ssl", headers=h, json=True).status_code == 200
        assert client.get("/v2/domains/domain-neha-002/ssl", headers=h).json()["forceHttps"] is True

        # Mailbox: no autoresponder (404), nonzero spam thresholds preserved on partial update
        assert client.get("/orgs/org-neha-001/websites/site-neha-002/emails/test@neha-mcp-disposable.example/autoresponder", headers=h).status_code == 404
        assert client.get("/websites/site-neha-002/emails/test@neha-mcp-disposable.example/spam_thresholds", headers=h).json() == {
            "reject": 10, "spambox": 5, "greylist": 3
        }
        assert client.put("/websites/site-neha-002/emails/test@neha-mcp-disposable.example/spam_thresholds", headers=h, json={"reject": 10, "spambox": 7}).status_code == 200
        assert client.get("/websites/site-neha-002/emails/test@neha-mcp-disposable.example/spam_thresholds", headers=h).json() == {
            "reject": 10, "spambox": 7, "greylist": 3
        }

        # Rewrite rule has synthetic credential-like token
        rewrites = client.get("/orgs/org-neha-001/websites/site-neha-002/htaccess", headers=h).json()["items"]
        assert "token=EXAMPLE_FAKE_SECRET" in rewrites[0]["rule"]["substitution"]

        # Profile update persists on /login and /members
        assert client.patch("/login", headers=h, json={"name": "Neha Kulkarni (MCP Test)"}).json()["verifyPin"] is False
        assert client.get("/login", headers=h).json()["name"] == "Neha Kulkarni (MCP Test)"
