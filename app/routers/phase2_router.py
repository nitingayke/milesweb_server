"""Mock implementation of the Phase 2 Enhance read-only GET API catalog."""

import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.security import get_current_client_id
from app.services.phase2_catalog import (
    CatalogBadRequest,
    CatalogForbidden,
    CatalogNotFound,
    Phase2Catalog,
    catalog,
)

router = APIRouter(tags=["Phase 2 Enhance mock"])


def authenticated_client(
    client_id: int | str = Depends(get_current_client_id),
) -> int:
    """Require a verified Bearer JWT (or configured dev test token); ignore X-Connector-Key."""
    return int(client_id)


def get_catalog() -> Phase2Catalog:
    return catalog


def phase2_handler(operation: str) -> Callable:
    async def handler(
        request: Request,
        client_id: int = Depends(authenticated_client),
        data: Phase2Catalog = Depends(get_catalog),
    ) -> Any:
        customer = data.authorize(client_id, dict(request.path_params))
        if customer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
        try:
            return data.response(operation, customer, dict(request.query_params), dict(request.path_params))
        except CatalogForbidden as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except CatalogBadRequest as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except CatalogNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    handler.__name__ = operation
    handler.__doc__ = f"Mock read-only response for Enhance operation {operation}."
    return handler


# 16 additional Enhance read-only GET operations (mail, DNS, diagnostics, clones, members).
# Registered before OPERATIONS so static routes like /websites/clone take precedence over /websites/{website_id}.
EXTRA_OPERATIONS = [
    ("getWebsiteEmail", "/orgs/{org_id}/websites/{website_id}/emails/{email_address}"),
    ("getWebsiteEmailClientConf", "/orgs/{org_id}/websites/{website_id}/emails/{email_address}/client-conf"),
    ("getWebsiteEmailAutoresponder", "/orgs/{org_id}/websites/{website_id}/emails/{email_address}/autoresponder"),
    ("getWebsiteDomainDnsQuery", "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-query"),
    ("getCloudflareNameServers", "/orgs/{org_id}/domains/{domain_id}/cloudflare/nameservers"),
    ("getWebsiteServerDomains", "/orgs/{org_id}/websites/{website_id}/server_domains"),
    ("getWebsiteGitDeploymentLog", "/orgs/{org_id}/websites/{website_id}/git/deploys/{deployment_id}"),
    ("getWebsiteHtaccessRewrites", "/orgs/{org_id}/websites/{website_id}/htaccess"),
    ("getWebsiteHtaccessIpsRule", "/orgs/{org_id}/websites/{website_id}/htaccess/ips"),
    ("getScreenshotTimestamp", "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/screenshot/timestamp"),
    ("getJoomlaInfo", "/orgs/{org_id}/websites/{website_id}/apps/{app_id}/joomla/info"),
    ("getWebsiteClones", "/orgs/{org_id}/websites/clone"),
    ("getWebsiteClone", "/orgs/{org_id}/websites/clone/{clone_id}"),
    ("getWebsiteCloneLog", "/orgs/{org_id}/websites/clone/{clone_id}/log"),
    ("getMembers", "/orgs/{org_id}/members"),
    ("getMember", "/orgs/{org_id}/members/{member_id}"),
]

# Every GET operation in the original 42-route Phase 2 Enhance read API catalog.
OPERATIONS = [
    ("getDomains", "/orgs/{org_id}/domains"),
    ("getDomainAuthNs", "/orgs/{org_id}/domains/{domain_id}/auth-ns"),
    ("getDomainLocalRemote", "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/local_remote"),
    ("getFtpUsers", "/orgs/{org_id}/websites/{website_id}/ftp/users"),
    ("getInstallableApps", "/orgs/{org_id}/subscriptions/{subscription_id}/installable-apps"),
    ("getLogin", "/login"),
    ("getLoginMemberships", "/login/memberships"),
    ("getOrg", "/orgs/{org_id}"),
    ("getOrgActivities", "/v2/orgs/{org_id}/activities"),
    ("getSubscription", "/orgs/{org_id}/subscriptions/{subscription_id}"),
    ("getSubscriptionBandwidthUsage", "/orgs/{org_id}/subscriptions/{subscription_id}/bandwidth"),
    ("getSubscriptionsToParent", "/orgs/{org_id}/subscriptions"),
    ("getWebsite", "/orgs/{org_id}/websites/{website_id}"),
    ("getWebsiteApps", "/orgs/{org_id}/websites/{website_id}/apps"),
    ("getWebsiteBackup", "/orgs/{org_id}/websites/{website_id}/backups/{backup_id}"),
    ("getWebsiteBackups", "/orgs/{org_id}/websites/{website_id}/backups"),
    ("getWebsiteBackupStatus", "/orgs/{org_id}/websites/{website_id}/status/backup"),
    ("getWebsiteCgroupLimits", "/orgs/{org_id}/websites/{website_id}/cgroup_limits"),
    ("getWebsiteDomainDnsZone", "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-zone"),
    ("getWebsiteDomainMapping", "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}"),
    ("getWebsiteDomainMappingDnsStatus", "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-status"),
    ("getWebsiteDomainMappings", "/orgs/{org_id}/websites/{website_id}/domains"),
    ("getWebsiteDomainSslCert", "/v2/domains/{domain_id}/ssl"),
    ("getWebsiteEmails", "/orgs/{org_id}/websites/{website_id}/emails"),
    ("getWebsiteEnabledPhpExtensions", "/websites/{website_id}/php_extensions"),
    ("getWebsiteFsQuotaLimits", "/orgs/{org_id}/websites/{website_id}/fs_quota_limits"),
    ("getWebsiteGitDeploys", "/orgs/{org_id}/websites/{website_id}/git/deploys"),
    ("getWebsiteGitInfo", "/orgs/{org_id}/websites/{website_id}/git"),
    ("getWebsiteLsphpSettings", "/websites/{website_id}/lsphp_settings"),
    ("getWebsiteMetrics", "/orgs/{org_id}/websites/{website_id}/metrics"),
    ("getWebsiteMySQLDBs", "/orgs/{org_id}/websites/{website_id}/mysql-dbs"),
    ("getWebsiteMySQLUsers", "/orgs/{org_id}/websites/{website_id}/mysql-users"),
    ("getWebsitePhpErrorLog", "/websites/{website_id}/php_error_log"),
    ("getWebsitePostgresqlDbs", "/orgs/{org_id}/websites/{website_id}/postgresql-dbs"),
    ("getWebsitePostgresqlUsers", "/orgs/{org_id}/websites/{website_id}/postgresql-users"),
    ("getWebsiteRestoreStatus", "/orgs/{org_id}/websites/{website_id}/backups/{backup_id}/restore_status"),
    ("getWebsiteSshKeys", "/orgs/{org_id}/websites/{website_id}/ssh/keys"),
    ("getWebsites", "/orgs/{org_id}/websites"),
    ("getWordpressAppVersion", "/orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/version"),
    ("getWordpressInfo", "/orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/info"),
    ("getWordpressPlugins", "/orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/plugins"),
    ("getWordpressThemes", "/orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/themes"),
]

QUERY_PARAMS_BY_OPERATION: dict[str, list[dict[str, Any]]] = {
    "getWebsiteDomainDnsQuery": [
        {"name": "resolveDepth", "in": "query", "required": False, "schema": {"type": "string", "enum": ["short", "detailed", "queryAllTldNs"]}},
    ],
    "getMembers": [
        {"name": "offset", "in": "query", "required": False, "schema": {"type": "integer"}},
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
        {"name": "sortBy", "in": "query", "required": False, "schema": {"type": "string", "enum": ["status", "joinedAt"]}},
        {"name": "sortOrder", "in": "query", "required": False, "schema": {"type": "string", "enum": ["asc", "desc"]}},
        {"name": "role", "in": "query", "required": False, "schema": {"type": "string", "enum": ["Owner", "SuperAdmin", "Business", "SiteAccess", "Support", "Sysadmin"]}},
        {"name": "siteAccess", "in": "query", "required": False, "schema": {"type": "string"}},
    ],
}

for operation_name, operation_path in [*EXTRA_OPERATIONS, *OPERATIONS]:
    # Dynamic handlers read path values from Request.path_params, so declare
    # them explicitly for OpenAPI/Swagger even though they are not Python
    # function parameters.
    parameters: list[dict[str, Any]] = [
        {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
        for name in re.findall(r"{([^}]+)}", operation_path)
    ]
    parameters.extend(QUERY_PARAMS_BY_OPERATION.get(operation_name, []))
    router.add_api_route(
        operation_path,
        phase2_handler(operation_name),
        methods=["GET"],
        name=operation_name,
        openapi_extra={"parameters": parameters} if parameters else None,
    )
