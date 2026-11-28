"""Tests for edge cases discovered in the Nov 2026 audit.

Covers:
- Karan: registered user with domains but no hosting (no org/website).
- Neha: active org with a suspended website.
- Cross-customer domain_id rejection (primary and additional domain IDs).
- Cross-customer backup_id isolation (blocked by org+website ownership).
- getOrgActivities endpoint response shape.
- getWebsiteMetrics granularity query parameter passthrough.
- Phase2Catalog.customer() fallback when clientId exists only in CustomerRepository.
- Multi-domain ownership: primary domain access, additional domain access, foreign domain rejection.
"""

import pytest
from pathlib import Path
from app.services.phase2_catalog import Phase2Catalog
from app.customer_repository import CustomerRepository


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def phase2_headers(token: str = "test-token-rahul") -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Karan — registered user with domains but no hosting
# ---------------------------------------------------------------------------

class TestKaranNoHosting:
    def test_karan_login_profile_accessible(self, client):
        response = client.get("/login", headers=phase2_headers("test-token-karan"))
        assert response.status_code == 200
        assert response.json()["email"] == "karan@example.com"
        assert response.json()["name"] == "Karan Deshmukh"

    def test_karan_gets_empty_memberships_not_404(self, client):
        """Karan has no org, so memberships list is empty — not an error."""
        response = client.get("/login/memberships", headers=phase2_headers("test-token-karan"))
        assert response.status_code == 200
        assert response.json() == {"memberships": []}

    def test_karan_cannot_access_any_organization(self, client):
        assert client.get("/orgs/org-rahul-001", headers=phase2_headers("test-token-karan")).status_code == 404
        assert client.get("/orgs/org-amit-001", headers=phase2_headers("test-token-karan")).status_code == 404

    def test_karan_cannot_access_any_website(self, client):
        assert client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001",
            headers=phase2_headers("test-token-karan"),
        ).status_code == 404

    def test_karan_connector_domains_returned(self, client):
        """Karan has domain registrations even without hosting."""
        response = client.get(
            "/api/v1/connector/customer/domains?clientId=12349",
            headers=phase2_headers("test-token-karan"),
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 2

    def test_karan_connector_hosting_services_empty(self, client):
        response = client.get(
            "/api/v1/connector/customer/hosting-services?clientId=12349",
            headers=phase2_headers("test-token-karan"),
        )
        assert response.status_code == 200
        assert response.json()["data"] == []


# ---------------------------------------------------------------------------
# 2. Neha — active org with a suspended website
# ---------------------------------------------------------------------------

class TestNehaSuspendedWebsite:
    def test_neha_org_accessible(self, client):
        response = client.get("/orgs/org-neha-001", headers=phase2_headers("test-token-neha"))
        assert response.status_code == 200
        assert response.json()["name"] == "Neha Digital Store"

    def test_neha_suspended_website_returns_200(self, client):
        """Phase 2 endpoints still serve data for suspended websites."""
        response = client.get(
            "/orgs/org-neha-001/websites/site-neha-001",
            headers=phase2_headers("test-token-neha"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "suspended"

    def test_neha_backups_accessible_despite_suspension(self, client):
        response = client.get(
            "/orgs/org-neha-001/websites/site-neha-001/backups",
            headers=phase2_headers("test-token-neha"),
        )
        assert response.status_code == 200
        assert response.json()["total"] >= 1

    def test_neha_metrics_accessible_despite_suspension(self, client):
        response = client.get(
            "/orgs/org-neha-001/websites/site-neha-001/metrics",
            headers=phase2_headers("test-token-neha"),
        )
        assert response.status_code == 200
        assert "items" in response.json()

    def test_neha_ssl_accessible_despite_suspension(self, client):
        response = client.get(
            "/v2/domains/domain-neha-001/ssl",
            headers=phase2_headers("test-token-neha"),
        )
        assert response.status_code == 200
        assert "expires" in response.json()

    def test_neha_memberships_returned(self, client):
        response = client.get("/login/memberships", headers=phase2_headers("test-token-neha"))
        assert response.status_code == 200
        memberships = response.json()["memberships"]
        assert len(memberships) == 1
        assert memberships[0]["orgId"] == "org-neha-001"

    def test_neha_cannot_access_rahuls_website(self, client):
        assert client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001",
            headers=phase2_headers("test-token-neha"),
        ).status_code == 404


# ---------------------------------------------------------------------------
# 3. Cross-customer domain_id isolation
# ---------------------------------------------------------------------------

class TestDomainIdIsolation:
    def test_customer_can_access_own_primary_domain(self, client):
        """Rahul can call DNS status for his own primary domain-rahul-001."""
        response = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-status",
            headers=phase2_headers("test-token-rahul"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Connected"

    def test_customer_can_access_own_additional_domain(self, client):
        """Rahul can call DNS zone for his additional domain domain-rahul-002."""
        response = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-002/dns-zone",
            headers=phase2_headers("test-token-rahul"),
        )
        assert response.status_code == 200
        assert "records" in response.json()

    def test_customer_cannot_access_another_customers_primary_domain(self, client):
        """Amit cannot use Rahul's domain-rahul-001 — blocked at domain_id check."""
        response = client.get(
            "/orgs/org-amit-001/websites/site-amit-001/domains/domain-rahul-001/dns-status",
            headers=phase2_headers("test-token-amit"),
        )
        assert response.status_code == 404

    def test_customer_cannot_access_another_customers_additional_domain(self, client):
        """Amit cannot use Rahul's domain-rahul-002 either."""
        response = client.get(
            "/orgs/org-amit-001/websites/site-amit-001/domains/domain-rahul-002/dns-zone",
            headers=phase2_headers("test-token-amit"),
        )
        assert response.status_code == 404

    def test_ssl_cert_blocked_for_foreign_domain(self, client):
        """Amit cannot retrieve SSL info for Rahul's domain-rahul-001."""
        response = client.get(
            "/v2/domains/domain-rahul-001/ssl",
            headers=phase2_headers("test-token-amit"),
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. Cross-customer backup_id isolation
# ---------------------------------------------------------------------------

class TestBackupIsolation:
    def test_customer_can_access_own_backup(self, client):
        response = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/backups/9001",
            headers=phase2_headers("test-token-rahul"),
        )
        assert response.status_code == 200
        assert response.json()["id"] == 9001

    def test_customer_cannot_access_another_customers_backup(self, client):
        """Amit uses Rahul's org+website path with a backup_id — blocked by org_id isolation."""
        response = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/backups/9001",
            headers=phase2_headers("test-token-amit"),
        )
        assert response.status_code == 404

    def test_customer_cannot_access_backup_via_own_org_wrong_website(self, client):
        """Amit uses his own org but Rahul's website_id — blocked by website_id isolation."""
        response = client.get(
            "/orgs/org-amit-001/websites/site-rahul-001/backups/9001",
            headers=phase2_headers("test-token-amit"),
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 5. getOrgActivities endpoint
# ---------------------------------------------------------------------------

class TestOrgActivities:
    def test_get_org_activities_returns_200_for_owner(self, client):
        response = client.get(
            "/v2/orgs/org-rahul-001/activities",
            headers=phase2_headers("test-token-rahul"),
        )
        assert response.status_code == 200
        body = response.json()
        assert "total" in body
        assert isinstance(body["items"], list)
        assert body["total"] >= 1

    def test_get_org_activities_contains_expected_fields(self, client):
        response = client.get(
            "/v2/orgs/org-amit-001/activities",
            headers=phase2_headers("test-token-amit"),
        )
        assert response.status_code == 200
        activity = response.json()["items"][0]
        assert "id" in activity
        assert "orgId" in activity
        assert "kind" in activity
        assert "createdAt" in activity

    def test_get_org_activities_blocked_for_wrong_customer(self, client):
        assert client.get(
            "/v2/orgs/org-rahul-001/activities",
            headers=phase2_headers("test-token-amit"),
        ).status_code == 404


# ---------------------------------------------------------------------------
# 6. getWebsiteMetrics granularity passthrough
# ---------------------------------------------------------------------------

class TestWebsiteMetricsGranularity:
    @pytest.mark.parametrize("granularity", ["hour", "day", "week", "month"])
    def test_metrics_granularity_param_is_returned(self, client, granularity):
        response = client.get(
            f"/orgs/org-rahul-001/websites/site-rahul-001/metrics?granularity={granularity}",
            headers=phase2_headers("test-token-rahul"),
        )
        assert response.status_code == 200
        assert response.json()["granularity"] == granularity

    def test_metrics_default_granularity_is_day(self, client):
        response = client.get(
            "/orgs/org-rahul-001/websites/site-rahul-001/metrics",
            headers=phase2_headers("test-token-rahul"),
        )
        assert response.status_code == 200
        assert response.json()["granularity"] == "day"


# ---------------------------------------------------------------------------
# 7. Phase2Catalog.customer() fallback path
# ---------------------------------------------------------------------------

class TestPhase2CatalogFallback:
    def test_fallback_returns_basic_identity_for_repo_only_customer(self, tmp_path):
        """When a clientId exists in CustomerRepository but not in the Phase 2 fixture,
        Phase2Catalog.customer() synthesises a minimal identity record."""
        # Minimal Phase 2 fixture with no customers matching clientId 12345
        fixture = tmp_path / "customers.json"
        fixture.write_text('{"customers": []}', encoding="utf-8")

        catalog = Phase2Catalog(path=fixture)

        # Patch the repository to return Rahul's basic profile
        from unittest.mock import patch, MagicMock
        fake_repo = MagicMock()
        fake_repo.get_customer.return_value = {
            "clientId": 12345,
            "email": "rahul@example.com",
            "name": "Rahul Sharma",
        }
        with patch("app.customer_repository.repository", fake_repo):
            result = catalog.customer(12345)

        assert result is not None
        assert result["clientId"] == 12345
        assert result["login"]["email"] == "rahul@example.com"
        assert result["organization"] is None
        assert result["website"] is None

    def test_fallback_returns_none_for_completely_unknown_customer(self, tmp_path):
        """Unknown clientId returns None from both fixture and repository."""
        fixture = tmp_path / "customers.json"
        fixture.write_text('{"customers": []}', encoding="utf-8")
        catalog = Phase2Catalog(path=fixture)

        from unittest.mock import patch, MagicMock
        fake_repo = MagicMock()
        fake_repo.get_customer.return_value = None
        with patch("app.customer_repository.repository", fake_repo):
            result = catalog.customer(99999)

        assert result is None
