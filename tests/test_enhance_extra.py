"""Tests for the 16 additional Enhance read-only GET endpoints."""

import pytest


def headers(token: str = "test-token-rahul") -> dict[str, str]:
    return {"X-Connector-Key": "test-connector-key", "Authorization": f"Bearer {token}"}


ALL_16_RAHUL_PATHS = [
    "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example",
    "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example/client-conf",
    "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example/autoresponder",
    "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-query",
    "/orgs/org-rahul-001/domains/domain-rahul-001/cloudflare/nameservers",
    "/orgs/org-rahul-001/websites/site-rahul-001/server_domains",
    "/orgs/org-rahul-001/websites/site-rahul-001/git/deploys/deploy-rahul-001",
    "/orgs/org-rahul-001/websites/site-rahul-001/htaccess",
    "/orgs/org-rahul-001/websites/site-rahul-001/htaccess/ips",
    "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/screenshot/timestamp",
    "/orgs/org-rahul-001/websites/site-rahul-001/apps/app-rahul-joomla-001/joomla/info",
    "/orgs/org-rahul-001/websites/clone",
    "/orgs/org-rahul-001/websites/clone/clone-rahul-001",
    "/orgs/org-rahul-001/websites/clone/clone-rahul-001/log",
    "/orgs/org-rahul-001/members",
    "/orgs/org-rahul-001/members/login-rahul-001",
]


@pytest.mark.parametrize("path", ALL_16_RAHUL_PATHS)
def test_all_16_endpoints_authorized_read(client, path):
    response = client.get(path, headers=headers("test-token-rahul"))
    assert response.status_code == 200


@pytest.mark.parametrize("path", ALL_16_RAHUL_PATHS)
def test_all_16_endpoints_cross_customer_returns_404(client, path):
    response = client.get(path, headers=headers("test-token-amit"))
    assert response.status_code == 404


@pytest.mark.parametrize("path", ALL_16_RAHUL_PATHS)
def test_all_16_endpoints_missing_headers_returns_401(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Connector-Key": "test-connector-key"}).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer test-token-rahul"}).status_code == 401


@pytest.mark.parametrize("path", ALL_16_RAHUL_PATHS)
def test_all_16_endpoints_are_get_only(client, path):
    assert client.post(path, headers=headers("test-token-rahul")).status_code == 405


class TestEnhanceMailAndDns:
    def test_mailbox_details_and_extra_fields(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example",
            headers=headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mailboxName"] == "hello"
        assert data["address"] == "hello@rahulcloud.example"
        assert data["hasMailbox"] is True
        assert data["status"] == "active"
        assert data["quota"] == {"usage": 5242880, "total": 1073741824}
        assert data["isCatchAll"] is False
        assert "passwordHash" in data  # internal field for MCP allow-list to drop

    def test_mailbox_must_belong_to_website(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails/info@amitworkspace.example",
            headers=headers(),
        )
        assert resp.status_code == 404

    def test_client_conf_returns_server_details(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example/client-conf",
            headers=headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imap"]["port"] == 993
        assert data["smtp"]["port"] == 465
        assert data["incomingServer"] == "mail.rahulcloud.example"
        assert data["outgoingServer"] == "mail.rahulcloud.example"
        assert data["imapPort"] == 993
        assert data["pop3Port"] == 995
        assert data["smtpPort"] == 465
        assert data["sslEnabled"] is True
        assert data["protocol"] == "IMAP/POP3/SMTP"
        assert data["authMethod"] == "normal_password"
        assert data["encryption"] == "SSL/TLS"
        assert "authToken" in data

    def test_emails_list_includes_address_and_aliases(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails",
            headers=headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        assert items[0]["address"] == "hello@rahulcloud.example"
        assert items[0]["email"] == "hello@rahulcloud.example"
        assert items[0]["aliases"] == ["contact@rahulcloud.example"]

        filtered = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails?search=contact",
            headers=headers(),
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["address"] == "hello@rahulcloud.example"

    def test_mcp_aligned_fields_on_databases_ssh_backups_and_logs(self, client):
        mysql_dbs = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/mysql-dbs",
            headers=headers(),
        ).json()["items"][0]
        assert {"name", "size", "createdAt", "userCount"}.issubset(mysql_dbs.keys())

        mysql_users = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/mysql-users",
            headers=headers(),
        ).json()["items"][0]
        assert mysql_users["username"] == "site_user"
        assert isinstance(mysql_users["accessHosts"], list)
        assert "createdAt" in mysql_users

        pg_users = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/postgresql-users",
            headers=headers(),
        ).json()["items"][0]
        assert pg_users["username"] == "site_pg_user"
        assert isinstance(pg_users["accessHosts"], list)
        assert "createdAt" in pg_users

        ssh_key = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/ssh/keys",
            headers=headers(),
        ).json()["items"][0]
        assert "createdAt" in ssh_key

        backup_status = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/status/backup",
            headers=headers(),
        ).json()
        assert backup_status["status"] == "completed"
        assert backup_status["isRunning"] is False
        assert backup_status["progress"] == 100
        assert backup_status["step"] == "completed"

        restore_status = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/backups/9001/restore_status",
            headers=headers(),
        ).json()
        assert restore_status["status"] == "completed"
        assert restore_status["progress"] == 100
        assert restore_status["message"]

        php_err = client.get(
            "/websites/site-rahul-001/php_error_log",
            headers=headers(),
        ).json()
        assert "Optional theme configuration is missing." in php_err["log"]

        dns_rec = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-zone",
            headers=headers(),
        ).json()["records"][0]
        assert dns_rec["proxy"] is False

    def test_autoresponder_configured_and_unconfigured(self, client):
        configured = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails/hello@rahulcloud.example/autoresponder",
            headers=headers(),
        )
        assert configured.status_code == 200
        assert configured.json()["enabled"] is True
        assert configured.json()["startDate"] == "2026-11-20"
        assert configured.json()["endDate"] == "2026-12-05"
        assert "subject" in configured.json()

        unconfigured = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/emails/support@rahulcloud.example/autoresponder",
            headers=headers(),
        )
        assert unconfigured.status_code == 200
        assert unconfigured.json()["enabled"] is False

    @pytest.mark.parametrize("depth", ["short", "detailed", "queryAllTldNs"])
    def test_dns_query_accepts_resolve_depth(self, client, depth):
        resp = client.get(
            f"/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-query?resolveDepth={depth}",
            headers=headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqdn"] == "rahulcloud.example"
        assert "root" in data
        assert "tldNsMap" in data
        assert data["resolveDepth"] == depth

    def test_dns_query_rejects_invalid_resolve_depth(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-query?resolveDepth=invalid",
            headers=headers(),
        )
        assert resp.status_code == 400

    def test_cloudflare_nameservers_configured_and_unconfigured(self, client):
        ok = client.get(
            "/orgs/org-rahul-001/domains/domain-rahul-001/cloudflare/nameservers",
            headers=headers(),
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "active"
        assert len(ok.json()["nameServers"]) == 2
        assert "cloudflareTokenId" in ok.json()

        unconfigured = client.get(
            "/orgs/org-rahul-001/domains/domain-rahul-002/cloudflare/nameservers",
            headers=headers(),
        )
        assert unconfigured.status_code == 400

    def test_server_domains_returns_customer_hostnames_and_internal_fields(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/server_domains",
            headers=headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["appServerDomains"]
        assert data["emailServerDomains"]
        assert data["dbServerDomains"]
        assert "controlPanelToken" in data


class TestEnhanceDiagnosticsAndClones:
    def test_git_deployment_log_contains_fake_secrets_and_validates_id(self, client):
        resp1 = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/git/deploys/deploy-rahul-001",
            headers=headers(),
        )
        assert resp1.status_code == 200
        log1 = resp1.json()
        assert isinstance(log1, str)
        assert "https://deployuser:fakePass123@" in log1
        assert "API_KEY=abc123" in log1
        assert "-----BEGIN" in log1

        resp2 = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/git/deploys/deploy-rahul-002",
            headers=headers(),
        )
        assert resp2.status_code == 200
        assert isinstance(resp2.json(), str)
        assert "API_KEY=abc123" in resp2.json()

        missing = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/git/deploys/deploy-nonexistent",
            headers=headers(),
        )
        assert missing.status_code == 404

    def test_htaccess_rewrites_and_ip_rules(self, client):
        rewrites = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/htaccess",
            headers=headers(),
        )
        assert rewrites.status_code == 200
        items = rewrites.json()["items"]
        assert len(items) == 2
        assert items[0]["lineNumber"] == 1
        assert "rule" in items[0]
        assert "conds" in items[0]

        ips = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/htaccess/ips",
            headers=headers(),
        )
        assert ips.status_code == 200
        assert ips.json()["kind"] == "block"
        assert len(ips.json()["ips"]) >= 1

    def test_screenshot_timestamp(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/screenshot/timestamp",
            headers=headers(),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["seconds"], int)
        assert "internalStorageKey" in resp.json()

    def test_joomla_info_and_app_kind_validation(self, client):
        joomla = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/apps/app-rahul-joomla-001/joomla/info",
            headers=headers(),
        )
        assert joomla.status_code == 200
        data = joomla.json()
        assert data["version"] == "5.2.0"
        assert data["site_url"] == "https://rahulcloud.example/portal"
        assert data["plugin_count"] == 14
        assert data["user_count"] == 6
        assert "secretKey" in data

        # WordPress app ID on Joomla endpoint -> 400
        wrong_kind = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/apps/app-rahul-wp-001/joomla/info",
            headers=headers(),
        )
        assert wrong_kind.status_code == 400

        # Joomla app ID on WordPress endpoint -> 400
        wp_wrong = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/apps/app-rahul-joomla-001/wordpress/info",
            headers=headers(),
        )
        assert wp_wrong.status_code == 400

    def test_website_clones_and_long_log(self, client):
        clones = client.get("/orgs/org-rahul-001/websites/clone", headers=headers())
        assert clones.status_code == 200
        assert len(clones.json()["items"]) == 2

        detail = client.get("/orgs/org-rahul-001/websites/clone/clone-rahul-001", headers=headers())
        assert detail.status_code == 200
        assert detail.json()["status"] == "complete"
        assert "rsyncToken" in detail.json()

        log = client.get("/orgs/org-rahul-001/websites/clone/clone-rahul-001/log", headers=headers())
        assert log.status_code == 200
        entries = log.json()
        assert isinstance(entries, list)
        assert len(entries) >= 200
        assert {"createdAt", "message", "percentageComplete"}.issubset(entries[0].keys())

        # Amit has 0 clone jobs and cannot access Rahul's clone_id
        amit_clones = client.get("/orgs/org-amit-001/websites/clone", headers=headers("test-token-amit"))
        assert amit_clones.status_code == 200
        assert amit_clones.json()["items"] == []
        assert client.get("/orgs/org-amit-001/websites/clone/clone-rahul-001", headers=headers("test-token-amit")).status_code == 404


class TestEnhanceMembersAndRoles:
    def test_non_admin_member_can_login_and_gets_403_on_members_list(self, client):
        login_res = client.post(
            "/auth/login",
            json={"email": "vikram@example.com", "password": "password123"},
        )
        assert login_res.status_code == 200
        vikram_jwt = login_res.json()["token"]

        resp = client.get("/orgs/org-rahul-001/members", headers=headers(vikram_jwt))
        assert resp.status_code == 403

        # Non-admin also gets 403 when querying another member's details
        other_member = client.get(
            "/orgs/org-rahul-001/members/login-rahul-001",
            headers=headers("test-token-vikram"),
        )
        assert other_member.status_code == 403

        # Non-admin can view own member record
        self_member = client.get(
            "/orgs/org-rahul-001/members/login-vikram-001",
            headers=headers("test-token-vikram"),
        )
        assert self_member.status_code == 200
        assert self_member.json()["id"] == "login-vikram-001"

    def test_owner_can_list_and_filter_members(self, client):
        resp = client.get("/orgs/org-rahul-001/members", headers=headers("test-token-rahul"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert any(m["id"] == "login-rahul-001" and "Owner" in m["roles"] for m in body["items"])

        # Role filter
        by_role = client.get(
            "/orgs/org-rahul-001/members?role=SiteAccess",
            headers=headers("test-token-rahul"),
        )
        assert by_role.status_code == 200
        assert by_role.json()["total"] == 1
        assert by_role.json()["items"][0]["id"] == "login-vikram-001"

        # siteAccess filter
        by_site = client.get(
            "/orgs/org-rahul-001/members?siteAccess=site-rahul-001",
            headers=headers("test-token-rahul"),
        )
        assert by_site.status_code == 200
        assert by_site.json()["total"] == 2

        # siteAccess out of scope -> 404
        bad_site = client.get(
            "/orgs/org-rahul-001/members?siteAccess=site-amit-001",
            headers=headers("test-token-rahul"),
        )
        assert bad_site.status_code == 404

        # Sorting & pagination
        sorted_desc = client.get(
            "/orgs/org-rahul-001/members?sortBy=joinedAt&sortOrder=desc&offset=0&limit=1",
            headers=headers("test-token-rahul"),
        )
        assert sorted_desc.status_code == 200
        assert sorted_desc.json()["total"] == 2
        assert len(sorted_desc.json()["items"]) == 1
        assert sorted_desc.json()["items"][0]["id"] == "login-vikram-001"

        paged = client.get(
            "/orgs/org-rahul-001/members?sortBy=joinedAt&sortOrder=asc&offset=1&limit=1",
            headers=headers("test-token-rahul"),
        )
        assert paged.status_code == 200
        assert paged.json()["items"][0]["id"] == "login-vikram-001"

    def test_owner_can_get_member_details_and_unknown_member_404(self, client):
        ok = client.get("/orgs/org-rahul-001/members/login-vikram-001", headers=headers("test-token-rahul"))
        assert ok.status_code == 200
        assert ok.json()["roles"] == ["SiteAccess"]
        assert "inviteToken" in ok.json()

        missing = client.get("/orgs/org-rahul-001/members/login-nonexistent", headers=headers("test-token-rahul"))
        assert missing.status_code == 404
