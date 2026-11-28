"""Tests for the 7 newly added Enhance customer read API endpoints."""

import pytest


def phase2_headers(token: str = "test-token-rahul") -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestNewBatchEndpoints:
    # 1. getDomains: GET /orgs/{org_id}/domains
    def test_get_domains_authorized(self, client):
        resp = client.get("/orgs/org-rahul-001/domains", headers=phase2_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] >= 1
        item = data["items"][0]
        assert item["id"] == "domain-rahul-001"
        assert item["orgId"] == "org-rahul-001"
        assert item["domain"] == "rahulcloud.example"
        assert item["dkim"] is True
        assert item["spf"] is True
        assert item["cloudflareStatus"] == "Connected"

    def test_get_domains_cross_customer_rejected(self, client):
        resp = client.get("/orgs/org-rahul-001/domains", headers=phase2_headers("test-token-amit"))
        assert resp.status_code == 404

    # 2. getDomainAuthNs: GET /orgs/{org_id}/domains/{domain_id}/auth-ns
    def test_get_domain_auth_ns_authorized(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/domains/domain-rahul-001/auth-ns",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matchesPlatform"] is True
        assert isinstance(data["authNs"], list)
        assert len(data["authNs"]) >= 1
        assert "name" in data["authNs"][0]
        assert "ips" in data["authNs"][0]

    def test_get_domain_auth_ns_cross_customer_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/domains/domain-rahul-001/auth-ns",
            headers=phase2_headers("test-token-amit"),
        )
        assert resp.status_code == 404

    def test_get_domain_auth_ns_unowned_domain_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/domains/domain-amit-001/auth-ns",
            headers=phase2_headers("test-token-rahul"),
        )
        assert resp.status_code == 404

    # 3. getWebsiteDomainMapping: GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}
    def test_get_website_domain_mapping_primary(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["domainId"] == "domain-rahul-001"
        assert data["websiteId"] == "site-rahul-001"
        assert data["domain"] == "rahulcloud.example"
        assert data["mappingKind"] == "primary"
        assert data["documentRoot"] == "/public_html"
        assert "cert" in data
        assert data["cloudflareStatus"] == "Connected"

    def test_get_website_domain_mapping_additional(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-002",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["domainId"] == "domain-rahul-002"
        assert data["mappingKind"] == "addon"

    def test_get_website_domain_mapping_cross_customer_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001",
            headers=phase2_headers("test-token-amit"),
        )
        assert resp.status_code == 404

    # 4. getInstallableApps: GET /orgs/{org_id}/subscriptions/{subscription_id}/installable-apps
    def test_get_installable_apps_authorized(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/subscriptions/5001/installable-apps",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        apps = [item["app"] for item in data["items"]]
        assert "wordpress" in apps
        wp = next(item for item in data["items"] if item["app"] == "wordpress")
        assert "version" in wp
        assert wp["isLatest"] is True
        assert "size" in wp

    def test_get_installable_apps_cross_customer_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/subscriptions/5001/installable-apps",
            headers=phase2_headers("test-token-amit"),
        )
        assert resp.status_code == 404

    # 5. getWebsiteBackupStatus: GET /orgs/{org_id}/websites/{website_id}/status/backup
    def test_get_website_backup_status_authorized(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/status/backup",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 9001
        assert data["websiteId"] == "site-rahul-001"
        assert data["action"] == "backup"
        assert data["homeDirStatus"] == "successful"

    def test_get_website_backup_status_cross_customer_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/status/backup",
            headers=phase2_headers("test-token-amit"),
        )
        assert resp.status_code == 404

    # 6. getWebsiteRestoreStatus: GET /orgs/{org_id}/websites/{website_id}/backups/{backup_id}/restore_status
    def test_get_website_restore_status_authorized(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/backups/9001/restore_status",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["backupId"] == 9001
        assert "startedAt" in data
        assert "finishedAt" in data
        assert data["homeDirStatus"] == "successful"
        assert data["mysqlDbsStatus"] == "successful"

    def test_get_website_restore_status_cross_customer_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/backups/9001/restore_status",
            headers=phase2_headers("test-token-amit"),
        )
        assert resp.status_code == 404

    # 7. getDomainLocalRemote: GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}/local_remote
    def test_get_domain_local_remote_authorized(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/local_remote",
            headers=phase2_headers(),
        )
        assert resp.status_code == 200
        assert resp.json() == {"localRemote": "local"}

    def test_get_domain_local_remote_cross_customer_rejected(self, client):
        resp = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/local_remote",
            headers=phase2_headers("test-token-amit"),
        )
        assert resp.status_code == 404
