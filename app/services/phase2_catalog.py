"""Static, tenant-aware data provider for the Phase 2 Enhance GET catalog."""

import json
from pathlib import Path
from typing import Any


class CatalogError(Exception):
    """Base error raised by Phase2Catalog for HTTP mapping in the router."""


class CatalogBadRequest(CatalogError):
    """Raised for invalid query parameters or mismatched resource types (400)."""


class CatalogForbidden(CatalogError):
    """Raised when the authenticated user lacks required org/member role (403)."""


class CatalogNotFound(CatalogError):
    """Raised when a nested resource is missing or out of scope (404)."""


ADMIN_ROLES = {"Owner", "SuperAdmin", "Admin"}
VALID_MEMBER_ROLES = {"Owner", "SuperAdmin", "Business", "SiteAccess", "Support", "Sysadmin"}
VALID_RESOLVE_DEPTHS = {"short", "detailed", "queryAllTldNs"}


DEFAULT_CUSTOMERS_PATH = Path(__file__).resolve().parents[2] / "data" / "customers.json"


class Phase2Catalog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_CUSTOMERS_PATH

    def _state(self):
        if self.path != DEFAULT_CUSTOMERS_PATH:
            return None
        from app.services.enhance_state import enhance_state

        enhance_state._ensure_seeded()
        return enhance_state

    def _customers(self) -> list[dict[str, Any]]:
        with self.path.open(encoding="utf-8") as source:
            return json.load(source)["customers"]

    def customer(self, client_id: int) -> dict[str, Any] | None:
        item = next((entry for entry in self._customers() if entry["clientId"] == client_id), None)
        if item is not None:
            return item

        # Fallback to general customer repository so any registered customer has an account identity
        try:
            from app.customer_repository import repository

            cust = repository.get_customer(client_id)
            if cust is not None:
                return {
                    "clientId": cust["clientId"],
                    "login": {
                        "id": f"login-{cust['clientId']}-001",
                        "email": cust["email"],
                        "name": cust["name"],
                        "colorCode": "#6b7280",
                        "registeredAt": "2025-01-01T00:00:00Z",
                        "authMethod": "basic",
                        "locale": "en-IN",
                    },
                    "organization": None,
                    "subscription": None,
                    "website": None,
                }
        except Exception:
            pass

        return None

    def _org_record(self, org_id: str, fallback_org: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return the canonical org object (one that carries members/clones/cloudflareDomains)."""
        for entry in self._customers():
            org = entry.get("organization")
            if org and org.get("id") == org_id and ("members" in org or "websiteClones" in org):
                return org
        return fallback_org

    def _org_websites(self, org_id: str) -> set[str]:
        """Collect all website IDs belonging to an organization across fixture entries."""
        site_ids: set[str] = set()
        for entry in self._customers():
            org = entry.get("organization")
            site = entry.get("website")
            if org and org.get("id") == org_id and site and site.get("id"):
                site_ids.add(site["id"])
        return site_ids

    def _org_members(self, org_id: str, customer: dict[str, Any]) -> list[dict[str, Any]]:
        """Return members of the organization, synthesizing the owner if not explicitly listed."""
        state = self._state()
        if state and org_id in state._members:
            return list(state._members[org_id])
        org = self._org_record(org_id, customer.get("organization"))
        if org and org.get("members"):
            return list(org["members"])
        login = customer.get("login") or {}
        website = customer.get("website")
        return [
            {
                "id": login.get("id", f"login-{customer.get('clientId', '0')}-001"),
                "name": login.get("name", customer.get("name", "")),
                "roles": ["Owner"],
                "isActive": True,
                "joinedAt": (org or {}).get("createdAt", "2025-01-01")[:10],
                "email": login.get("email", customer.get("email", "")),
                "siteAccess": [website["id"]] if website else [],
                "internalNotes": "Synthesized org owner",
            }
        ]

    def _caller_roles_in_org(self, customer: dict[str, Any], org: dict[str, Any]) -> list[str]:
        if customer.get("memberRoles"):
            return list(customer["memberRoles"])
        login_id = (customer.get("login") or {}).get("id")
        for member in self._org_members(org["id"], customer):
            if member.get("id") == login_id:
                return list(member.get("roles", []))
        return ["Owner"]

    def _allowed_domain_ids(self, customer: dict[str, Any]) -> set[str]:
        allowed: set[str] = set()
        for website in [customer.get("website"), *(customer.get("websites") or [])]:
            if isinstance(website, dict):
                allowed.add(website.get("domainId"))
                allowed.update(website.get("additionalDomainIds", []))
        for domain in customer.get("domains", []):
            if "domainId" in domain:
                allowed.add(str(domain["domainId"]))
                allowed.add(f"domain-{domain['domainId']}")
        allowed.discard(None)
        return allowed

    def _resolve_domain_name(self, customer: dict[str, Any], domain_id: str) -> str:
        website = customer.get("website")
        if website:
            if domain_id == website.get("domainId"):
                return website.get("domain", "example.com")
            if domain_id in website.get("additionalDomainIds", []):
                return f"extra.{website.get('domain', 'example.com')}"
        for domain in customer.get("domains", []):
            if domain_id in (str(domain.get("domainId")), f"domain-{domain.get('domainId')}"):
                return domain.get("domainName", "example.com")
        return (website or {}).get("domain", "example.com")

    def _find_mailbox(self, website: dict[str, Any], email_address: str) -> dict[str, Any] | None:
        target = email_address.strip().lower()
        for mailbox in website.get("emails", []):
            if mailbox.get("address", "").strip().lower() == target:
                return mailbox
        return None

    def _find_app(self, website: dict[str, Any], app_id: str) -> dict[str, Any] | None:
        for app in website.get("apps", []):
            if app.get("id") == app_id:
                return app
        if app_id == website.get("appId"):
            return {"id": app_id, "name": "WordPress", "kind": "wordpress", "status": "active"}
        return None

    def authorize(self, client_id: int, path: dict[str, str]) -> dict[str, Any] | None:
        """Return a record only when all supplied resource IDs belong to caller."""
        customer = self.customer(client_id)
        if customer is None:
            return None

        org = customer.get("organization")
        website = customer.get("website")
        subscription = customer.get("subscription")
        state = self._state()

        if "org_id" in path:
            if not org or path["org_id"] != org.get("id"):
                return None
        if "website_id" in path:
            wid = path["website_id"]
            if state and org and wid in state._org_websites.get(org["id"], []):
                website = state._websites.get(wid, website)
            elif not website or wid != website.get("id"):
                return None
        if "subscription_id" in path:
            sid = str(path["subscription_id"])
            if state and org and sid in state._org_subscriptions.get(org["id"], []):
                subscription = state._subscriptions.get(sid, subscription)
            elif not subscription or sid != str(subscription.get("id")):
                return None
        if "app_id" in path:
            if not website or self._find_app(website, path["app_id"]) is None:
                return None
        if "domain_id" in path:
            allowed = self._allowed_domain_ids(customer)
            if state and org:
                allowed |= set(state._org_domains.get(org["id"], []))
            if not allowed or path["domain_id"] not in allowed:
                return None
        if "email_address" in path:
            if not website or self._find_mailbox(website, path["email_address"]) is None:
                return None
        if "deployment_id" in path:
            if not website:
                return None
            deploys = website.get("gitDeployments", [])
            if not any(d.get("id") == path["deployment_id"] for d in deploys):
                return None
        if "clone_id" in path:
            if not org:
                return None
            clones = state._clones.get(org["id"], []) if state else org.get("websiteClones", [])
            if not any(c.get("id") == path["clone_id"] for c in clones):
                return None

        return customer

    def response(
        self,
        operation: str,
        customer: dict[str, Any],
        query: dict[str, str],
        path: dict[str, str] | None = None,
    ) -> Any:
        path = path or {}
        login = customer.get("login") or {
            "id": f"login-{customer.get('clientId', 'unknown')}-001",
            "email": customer.get("email", ""),
            "name": customer.get("name", ""),
            "colorCode": "#6b7280",
            "registeredAt": "2025-01-01T00:00:00Z",
            "authMethod": "basic",
            "locale": "en-IN",
        }
        state = self._state()
        org = customer.get("organization")
        subscription = customer.get("subscription")
        website = customer.get("website")
        if state and org:
            if "website_id" in path and path["website_id"] in state._websites:
                website = state._websites[path["website_id"]]
            elif website and website.get("id") in state._websites:
                website = state._websites[website["id"]]
            elif state._org_websites.get(org["id"]):
                website = state._websites.get(state._org_websites[org["id"]][0], website)
            if "subscription_id" in path and str(path["subscription_id"]) in state._subscriptions:
                subscription = state._subscriptions[str(path["subscription_id"])]
            elif subscription and str(subscription.get("id")) in state._subscriptions:
                subscription = state._subscriptions[str(subscription["id"])]

        # Identity operations (work for all users, with or without hosting)
        if operation == "getLogin":
            if state and customer.get("clientId") in state._logins:
                return state._logins[customer["clientId"]]
            return login

        if operation == "getLoginMemberships":
            if org:
                roles = self._caller_roles_in_org(customer, org)
                site_count = 1 if website else len(customer.get("memberSiteAccess", []))
                return {
                    "memberships": [
                        {
                            "memberId": login["id"],
                            "orgId": org["id"],
                            "orgName": org["name"],
                            "isMasterOrg": True,
                            "roles": roles,
                            "siteAccessCount": site_count,
                        }
                    ]
                }
            return {"memberships": []}

        if operation == "getOrg":
            return org or {}

        if operation == "getOrgActivities":
            return {
                "total": 1,
                "items": [
                    {
                        "id": "activity-001",
                        "orgId": org["id"] if org else "",
                        "kind": "added",
                        "createdAt": "2026-11-20T10:00:00Z",
                        "message": "Mock website created",
                    }
                ],
            }

        if operation == "getMembers":
            return self._members_response(customer, org, query)

        if operation == "getMember":
            return self._member_response(customer, org, login, path["member_id"])

        if operation == "getWebsiteClones":
            clones = state._clones.get(org["id"], []) if (state and org) else (org or {}).get("websiteClones", [])
            items = [{k: v for k, v in clone.items() if k != "log"} for clone in clones]
            return {"total": len(items), "items": items}

        if operation == "getWebsiteClone":
            clones = state._clones.get(org["id"], []) if (state and org) else (org or {}).get("websiteClones", [])
            clone = next((c for c in clones if c.get("id") == path.get("clone_id")), None)
            if clone is None:
                raise CatalogNotFound("Clone job not found")
            return {k: v for k, v in clone.items() if k != "log"}

        if operation == "getWebsiteCloneLog":
            clones = state._clones.get(org["id"], []) if (state and org) else (org or {}).get("websiteClones", [])
            clone = next((c for c in clones if c.get("id") == path.get("clone_id")), None)
            if clone is None:
                raise CatalogNotFound("Clone job not found")
            return clone.get("log", [])

        if operation == "getCloudflareNameServers":
            cf_map = (org or {}).get("cloudflareDomains", {})
            entry = cf_map.get(path.get("domain_id", ""))
            if not entry or not entry.get("configured", False):
                raise CatalogBadRequest("Cloudflare integration is not configured for this domain")
            return {
                "nameServers": entry["nameServers"],
                "status": entry["status"],
                "cloudflareZoneId": entry.get("cloudflareZoneId"),
                "cloudflareTokenId": entry.get("cloudflareTokenId"),
                "internalNote": entry.get("internalNote"),
            }

        if operation == "getDomains":
            if not org:
                return {"total": 0, "items": []}
            return self._domains_response(customer, org, website)

        if operation == "getDomainAuthNs":
            return {
                "matchesPlatform": True,
                "authNs": [
                    {"name": "ns1.milesweb.com", "ips": ["198.51.100.1"]},
                    {"name": "ns2.milesweb.com", "ips": ["198.51.100.2"]},
                ],
            }

        if operation == "getSubscriptionsToParent":
            if state and org and org["id"] in state._org_subscriptions:
                subs = [state._subscriptions[sid] for sid in state._org_subscriptions[org["id"]] if sid in state._subscriptions]
                return {"total": len(subs), "items": subs}
            if subscription:
                return {"total": 1, "items": [subscription]}
            return {"total": 0, "items": []}

        if operation == "getSubscription":
            return subscription or {}

        if operation == "getSubscriptionBandwidthUsage":
            return subscription.get("bandwidthUsage", {}) if subscription else {}

        if operation == "getInstallableApps":
            return {
                "items": [
                    {
                        "app": "wordpress",
                        "version": "6.7.1",
                        "isLatest": True,
                        "description": "WordPress is web software you can use to create a beautiful website, blog, or app.",
                        "size": 65000000,
                        "createdAt": "2026-11-19T10:56:39.768Z",
                    },
                    {
                        "app": "joomla",
                        "version": "5.2.0",
                        "isLatest": True,
                        "description": "Joomla is a free and open-source content management system.",
                        "size": 45000000,
                        "createdAt": "2026-11-19T10:56:39.768Z",
                    },
                ]
            }

        if operation == "getWebsites":
            if state and org and org["id"] in state._org_websites:
                site_items = [
                    {
                        "id": state._websites[wid]["id"],
                        "orgId": org["id"],
                        "subscriptionId": state._websites[wid].get("subscriptionId", subscription["id"] if subscription else 0),
                        "domain": state._websites[wid]["domain"],
                        "status": state._websites[wid]["status"],
                        "server": state._websites[wid]["server"],
                    }
                    for wid in state._org_websites[org["id"]]
                    if wid in state._websites
                ]
                return {"total": len(site_items), "items": site_items}
            if website and org and subscription:
                website_item = {
                    "id": website["id"],
                    "orgId": org["id"],
                    "subscriptionId": subscription["id"],
                    "domain": website["domain"],
                    "status": website["status"],
                    "server": website["server"],
                }
                return {"total": 1, "items": [website_item]}
            return {"total": 0, "items": []}

        if not website:
            return {"total": 0, "items": []}

        return self._website_response(operation, customer, org, subscription, website, query, path)

    def _members_response(
        self,
        customer: dict[str, Any],
        org: dict[str, Any] | None,
        query: dict[str, str],
    ) -> dict[str, Any]:
        if not org:
            raise CatalogNotFound("Organization not found")
        caller_roles = self._caller_roles_in_org(customer, org)
        if not any(role in ADMIN_ROLES for role in caller_roles):
            raise CatalogForbidden("Owner or Admin role is required to list organization members")

        members = self._org_members(org["id"], customer)

        role_filter = query.get("role")
        if role_filter is not None:
            if role_filter not in VALID_MEMBER_ROLES:
                raise CatalogBadRequest(f"Invalid role filter: {role_filter}")
            members = [m for m in members if role_filter in m.get("roles", [])]

        site_access = query.get("siteAccess")
        if site_access is not None:
            org_sites = self._org_websites(org["id"])
            if site_access not in org_sites:
                raise CatalogNotFound("Website in siteAccess is not in caller's scope")
            members = [
                m
                for m in members
                if any(r in {"Owner", "SuperAdmin"} for r in m.get("roles", []))
                or site_access in m.get("siteAccess", [])
            ]

        sort_by = query.get("sortBy")
        sort_order = query.get("sortOrder", "asc")
        if sort_order not in {"asc", "desc"}:
            raise CatalogBadRequest(f"Invalid sortOrder: {sort_order}")
        reverse = sort_order == "desc"

        if sort_by is not None:
            if sort_by not in {"status", "joinedAt"}:
                raise CatalogBadRequest(f"Invalid sortBy: {sort_by}")
            if sort_by == "status":
                members.sort(key=lambda m: bool(m.get("isActive", False)), reverse=reverse)
            else:
                members.sort(key=lambda m: str(m.get("joinedAt", "")), reverse=reverse)

        try:
            offset = int(query.get("offset", "0"))
            limit = int(query.get("limit", "25"))
        except ValueError as exc:
            raise CatalogBadRequest("offset and limit must be integers") from exc
        if offset < 0 or limit < 1:
            raise CatalogBadRequest("offset must be >= 0 and limit must be >= 1")

        total = len(members)
        return {"total": total, "items": members[offset : offset + limit]}

    def _member_response(
        self,
        customer: dict[str, Any],
        org: dict[str, Any] | None,
        login: dict[str, Any],
        member_id: str,
    ) -> dict[str, Any]:
        if not org:
            raise CatalogNotFound("Organization not found")
        caller_roles = self._caller_roles_in_org(customer, org)
        is_admin = any(role in ADMIN_ROLES for role in caller_roles)
        is_self = member_id == login.get("id")
        if not (is_admin or is_self):
            raise CatalogForbidden("Owner, Admin, or self access is required to view member details")

        for member in self._org_members(org["id"], customer):
            if member.get("id") == member_id:
                return member
        raise CatalogNotFound("Organization member not found")

    def _domains_response(
        self,
        customer: dict[str, Any],
        org: dict[str, Any],
        website: dict[str, Any] | None,
    ) -> dict[str, Any]:
        items = []
        if website:
            items.append({
                "id": website.get("domainId", f"domain-{org['id']}-001"),
                "orgId": org["id"],
                "domain": website.get("domain", "example.com"),
                "dkim": True,
                "spf": True,
                "cloudflareStatus": "Connected",
                "cloudflareTokenFriendlyName": "MilesWeb Cloudflare",
            })
            for idx, add_id in enumerate(website.get("additionalDomainIds", []), 2):
                items.append({
                    "id": add_id,
                    "orgId": org["id"],
                    "domain": f"extra{idx}.{website.get('domain', 'example.com')}",
                    "dkim": True,
                    "spf": True,
                    "cloudflareStatus": "Connected",
                    "cloudflareTokenFriendlyName": "MilesWeb Cloudflare",
                })
        for domain in customer.get("domains", []):
            d_id = f"domain-{domain['domainId']}"
            if not any(item["id"] in (str(domain["domainId"]), d_id) for item in items):
                items.append({
                    "id": d_id,
                    "orgId": org["id"],
                    "domain": domain.get("domainName", "domain.example"),
                    "dkim": True,
                    "spf": True,
                    "cloudflareStatus": "Connected" if domain.get("status") == "Active" else "Disconnected",
                    "cloudflareTokenFriendlyName": "MilesWeb Cloudflare",
                })
        return {"total": len(items), "items": items}

    def _website_response(
        self,
        operation: str,
        customer: dict[str, Any],
        org: dict[str, Any] | None,
        subscription: dict[str, Any] | None,
        website: dict[str, Any],
        query: dict[str, str],
        path: dict[str, str],
    ) -> Any:
        state = self._state()
        website_item = {
            "id": website["id"],
            "orgId": org["id"] if org else "",
            "subscriptionId": subscription["id"] if subscription else 0,
            "domain": website["domain"],
            "status": website["status"],
            "server": website["server"],
        }
        domain = {
            "id": website["domainId"],
            "domain": website["domain"],
            "isPrimary": True,
            "mappingKind": "primary",
        }

        if operation == "getWebsite":
            return website_item
        if operation == "getWebsiteDomainMappings":
            if state:
                site_domains = [
                    {
                        "id": d["id"],
                        "domainId": d["id"],
                        "websiteId": website["id"],
                        "domain": d["domain"],
                        "isPrimary": d.get("mappingKind", "primary") == "primary",
                        "mappingKind": d.get("mappingKind", "primary"),
                        "documentRoot": d.get("documentRoot", "/public_html"),
                    }
                    for d in state._domains.values()
                    if d.get("websiteId") == website["id"]
                ]
                if site_domains:
                    return {"total": len(site_domains), "items": site_domains}
            return {"total": 1, "items": [domain]}
        if operation == "getWebsiteDomainMapping":
            target_domain_id = path.get("domain_id", website["domainId"])
            dom_rec = state._domains.get(target_domain_id) if state else None
            if dom_rec is not None:
                target_domain = dom_rec.get("domain", website["domain"])
                mapping_kind = dom_rec.get("mappingKind", "primary")
                doc_root = dom_rec.get("documentRoot", "/public_html")
            else:
                target_domain = website["domain"]
                mapping_kind = "primary"
                doc_root = "/public_html"
                if target_domain_id != website.get("domainId"):
                    target_domain = f"extra.{website['domain']}"
                    mapping_kind = "addon"
            return {
                "domainId": target_domain_id,
                "websiteId": website["id"],
                "domain": target_domain,
                "mappingKind": mapping_kind,
                "documentRoot": doc_root,
                "cert": {
                    "cn": target_domain,
                    "expires": "2027-11-23T00:00:00Z",
                    "issued": "2026-11-23T00:00:00Z",
                    "issuer": "Mock Let's Encrypt",
                    "sans": [target_domain],
                    "forceHttps": True,
                },
                "cloudflareStatus": (dom_rec or {}).get("cloudflareStatus", "Connected"),
                "cloudflareFriendlyName": "MilesWeb Cloudflare",
                "cloudflareTokenId": "cf-token-001",
            }
        if operation == "getWebsiteDomainMappingDnsStatus":
            return {"status": "Connected", "lastCheckedAt": "2026-11-23T07:30:00Z"}
        if operation == "getWebsiteDomainDnsZone":
            dom_id = path.get("domain_id", website["domainId"])
            records = state._dns_zones.get(dom_id) if state else None
            if records is None:
                records = [
                    {
                        "id": "dns-001",
                        "kind": "A",
                        "name": "@",
                        "value": "198.51.100.42",
                        "ttl": 3600,
                        "proxy": False,
                    }
                ]
            return {
                "domain": website["domain"],
                "records": records,
            }
        if operation == "getWebsiteDomainDnsQuery":
            return self._dns_query_response(customer, website, path["domain_id"], query)
        if operation == "getWebsiteDomainSslCert":
            dom_id = path.get("domain_id", website["domainId"])
            if state and dom_id in state._ssl_certs:
                cert = state._ssl_certs[dom_id]
                if cert is None:
                    raise CatalogNotFound("No SSL certificate found for this domain")
                return cert
            return {
                "cn": website["domain"],
                "expires": "2027-11-23T00:00:00Z",
                "issued": "2026-11-23T00:00:00Z",
                "issuer": "Mock Let's Encrypt",
                "sans": [website["domain"]],
                "forceHttps": True,
            }
        if operation == "getDomainLocalRemote":
            return {"localRemote": "local"}
        if operation == "getWebsiteServerDomains":
            return website.get("serverDomains") or {
                "appServerDomains": [f"app01.{website['server']}.milesweb.example"],
                "emailServerDomains": [f"mail01.{website['server']}.milesweb.example"],
                "dbServerDomains": [f"db01.{website['server']}.milesweb.example"],
                "internalIps": ["10.20.30.99"],
                "controlPanelToken": "internal-cp-token-default",
            }
        if operation == "getScreenshotTimestamp":
            domain_id = path["domain_id"]
            shots = website.get("screenshotTimestamps", {})
            return shots.get(domain_id) or {
                "seconds": 1764000000,
                "internalStorageKey": f"screenshots/{website['id']}/{domain_id}.png",
                "workerNode": "shot-worker-01",
            }
        if operation == "getWebsiteApps":
            apps = website.get("apps") or [
                {"id": website["appId"], "name": "WordPress", "kind": "wordpress", "status": "active"}
            ]
            return {
                "total": len(apps),
                "items": [
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "kind": a["kind"],
                        "app": a.get("app", a["kind"]),
                        "type": a.get("type", a["kind"]),
                        "status": a["status"],
                    }
                    for a in apps
                ],
            }
        if operation in {"getWordpressInfo", "getWordpressAppVersion", "getWordpressPlugins", "getWordpressThemes"}:
            app_id = path.get("app_id")
            if app_id:
                app = self._find_app(website, app_id)
                if app and app.get("kind") != "wordpress":
                    raise CatalogBadRequest("App is not a WordPress installation")
            wp_details = website.get("wordpressDetails") or {}
            wp_version = wp_details.get("version", "6.7.1")
            if operation == "getWordpressInfo":
                return {
                    "id": website["appId"],
                    "name": wp_details.get("siteTitle", "WordPress"),
                    "url": wp_details.get("siteUrl", f"https://{website['domain']}"),
                    "version": wp_version,
                    "status": wp_details.get("status", "active"),
                }
            if operation == "getWordpressAppVersion":
                return {"version": wp_version}
            if operation == "getWordpressPlugins":
                return {"total": 1, "items": [{"name": "akismet", "status": "active", "version": "5.3", "updateAvailable": "none"}]}
            return {"total": 1, "items": [{"name": "twentytwentyfour", "status": "active", "version": "1.3", "autoUpdate": "on"}]}
        if operation == "getJoomlaInfo":
            app = self._find_app(website, path.get("app_id", ""))
            if not app or app.get("kind") != "joomla":
                raise CatalogBadRequest("App is not a Joomla installation")
            return app.get("joomlaInfo", {})
        if operation == "getWebsiteBackups":
            items = state._backups.get(website["id"]) if state else None
            if items is None:
                items = [{"id": 9001, "createdAt": "2026-11-20T01:00:00Z", "size": 10485760, "status": "completed"}]
            return {"total": len(items), "items": items}
        if operation == "getWebsiteBackup":
            items = state._backups.get(website["id"]) if state else None
            if items is not None:
                b_id = path.get("backup_id")
                match = next((b for b in items if str(b.get("id")) == str(b_id)), None)
                if match is None:
                    raise CatalogNotFound("Backup not found")
                return match
            return {"id": 9001, "createdAt": "2026-11-20T01:00:00Z", "size": 10485760, "status": "completed"}
        if operation == "getWebsiteBackupStatus":
            backup_status = website.get("backupStatus") or {}
            status_val = backup_status.get("status", "completed")
            if status_val == "none":
                status_val = "idle"
            return {
                "id": backup_status.get("backupId", 9001),
                "websiteId": website["id"],
                "status": status_val,
                "isRunning": status_val in {"running", "started", "in_progress"},
                "progress": 100 if status_val == "completed" else 0,
                "startedAt": backup_status.get("startedAt", "2026-11-20T01:00:00Z"),
                "step": status_val,
                "action": "backup",
                "homeDirStatus": backup_status.get("homeDirStatus", "successful"),
                "mysqlDbsStatus": backup_status.get("mysqlDbsStatus", "successful"),
                "emailsStatus": backup_status.get("emailsStatus", "successful"),
            }
        if operation == "getWebsiteRestoreStatus":
            b_id = int(path.get("backup_id", 9001))
            restore_status = website.get("restoreStatus") or {}
            status_val = restore_status.get("status", "completed")
            if status_val == "none":
                status_val = "idle"
            return {
                "backupId": restore_status.get("backupId", b_id),
                "status": status_val,
                "progress": 100 if status_val == "completed" else 0,
                "startedAt": restore_status.get("startedAt", "2026-11-20T01:00:00Z"),
                "finishedAt": restore_status.get("finishedAt", "2026-11-20T01:05:00Z"),
                "message": "Backup restoration completed successfully." if status_val == "completed" else "No active restore job.",
                "homeDirStatus": restore_status.get("homeDirStatus", "successful"),
                "mysqlDbsStatus": restore_status.get("mysqlDbsStatus", "successful"),
                "emailsStatus": restore_status.get("emailsStatus", "successful"),
            }
        if operation == "getWebsiteEmails":
            emails = website.get("emails")
            if emails is not None:
                items = [
                    {
                        "address": m["address"],
                        "email": m["address"],
                        "aliases": m.get("aliases", []),
                        "status": m["status"],
                        "quota": m["quota"],
                    }
                    for m in emails
                ]
            else:
                items = [
                    {
                        "address": f"hello@{website['domain']}",
                        "email": f"hello@{website['domain']}",
                        "aliases": [],
                        "status": "active",
                        "quota": {"usage": 5242880, "total": 1073741824},
                    }
                ]
            search = (query.get("search") or "").strip().lower()
            if search:
                items = [
                    it
                    for it in items
                    if search in it["address"].lower()
                    or any(search in a.lower() for a in it.get("aliases", []))
                ]
            try:
                offset = max(0, int(query.get("offset", "0")))
                limit = max(1, int(query.get("limit", "25")))
            except ValueError:
                offset = 0
                limit = 25
            return {"total": len(items), "items": items[offset : offset + limit]}
        if operation == "getWebsiteEmail":
            mailbox = self._find_mailbox(website, path["email_address"])
            if not mailbox:
                raise CatalogNotFound("Mailbox not found")
            return {k: v for k, v in mailbox.items() if k not in {"clientConf", "autoresponder"}}
        if operation == "getWebsiteEmailClientConf":
            mailbox = self._find_mailbox(website, path["email_address"])
            if not mailbox:
                raise CatalogNotFound("Mailbox not found")
            conf = dict(mailbox.get("clientConf", {}))
            imap_host = (conf.get("imap") or {}).get("host") or f"mail.{website['domain']}"
            smtp_host = (conf.get("smtp") or {}).get("host") or imap_host
            conf.setdefault("incomingServer", imap_host)
            conf.setdefault("outgoingServer", smtp_host)
            conf.setdefault("imapPort", (conf.get("imap") or {}).get("port", 993))
            conf.setdefault("pop3Port", (conf.get("pop3") or {}).get("port", 995))
            conf.setdefault("smtpPort", (conf.get("smtp") or {}).get("port", 465))
            conf.setdefault("sslEnabled", True)
            conf.setdefault("protocol", "IMAP/POP3/SMTP")
            conf.setdefault("authMethod", "normal_password")
            conf.setdefault("encryption", "SSL/TLS")
            return conf
        if operation == "getWebsiteEmailAutoresponder":
            mailbox = self._find_mailbox(website, path["email_address"])
            if not mailbox:
                raise CatalogNotFound("Mailbox not found")
            ar = mailbox.get("autoresponder")
            if not ar or (not ar.get("enabled") and not ar.get("id") and not ar.get("subject")):
                raise CatalogNotFound("Autoresponder not configured for this mailbox")
            return ar
        if operation == "getFtpUsers":
            items = state._ftp_users.get(website["id"]) if state else None
            if items is None:
                items = [{"account": "siteuser", "homeDir": f"/home/siteuser/{website['domain']}"}]
            return {"items": items}
        if operation == "getWebsiteMySQLDBs":
            items = state._mysql_dbs.get(website["id"]) if state else None
            if items is None:
                items = [{"name": "site_db", "size": 12582912, "createdAt": "2025-04-01T10:00:00Z", "userCount": 1}]
            return {"total": len(items), "items": items}
        if operation == "getWebsiteMySQLUsers":
            items = state._mysql_users.get(website["id"]) if state else None
            if items is None:
                items = [{"name": "site_user", "username": "site_user", "host": "localhost", "accessHosts": ["localhost", "127.0.0.1"], "createdAt": "2025-04-01T10:05:00Z"}]
            return {"total": len(items), "items": items}
        if operation == "getWebsitePostgresqlDbs":
            items = state._pg_dbs.get(website["id"]) if state else None
            if items is None:
                items = [{"name": "site_postgres", "size": 0, "createdAt": "2025-04-01T10:00:00Z", "userCount": 1}]
            return {"total": len(items), "items": items}
        if operation == "getWebsitePostgresqlUsers":
            items = state._pg_users.get(website["id"]) if state else None
            if items is None:
                items = [{"name": "site_pg_user", "username": "site_pg_user", "accessHosts": ["localhost"], "createdAt": "2025-04-01T10:05:00Z"}]
            return {"total": len(items), "items": items}
        if operation == "getWebsiteSshKeys":
            items = state._ssh_keys.get(website["id"]) if state else None
            if items is None:
                items = [{"id": "ssh-001", "name": "deployment-key", "fingerprint": "SHA256:mockfingerprint", "createdAt": "2025-06-15T12:00:00Z"}]
            return {"items": items}
        if operation == "getWebsiteGitInfo":
            if state and website["id"] in state._git_info:
                return state._git_info[website["id"]]
            return {
                "connected": False,
                "repo": None,
                "repository": None,
                "repoOwner": None,
                "repoName": None,
                "branch": None,
            }
        if operation == "getWebsiteGitDeploys":
            deploys = website.get("gitDeployments")
            if deploys is not None:
                return {
                    "total": len(deploys),
                    "items": [{k: v for k, v in d.items() if k != "log"} for d in deploys],
                }
            return {"total": 1, "items": [{"id": "deploy-001", "status": "success", "createdAt": "2026-11-22T10:00:00Z"}]}
        if operation == "getWebsiteGitDeploymentLog":
            deploy = next((d for d in website.get("gitDeployments", []) if d.get("id") == path.get("deployment_id")), None)
            if not deploy:
                raise CatalogNotFound("Git deployment not found")
            return deploy.get("log", "")
        if operation == "getWebsiteHtaccessRewrites":
            return website.get("htaccessRewrites") or {
                "items": [
                    {
                        "lineNumber": 1,
                        "rule": {"pattern": "^index\\.html$", "substitution": "/", "flags": ["R=301", "L"]},
                        "conds": [],
                        "internalRuleId": "rw-default-01",
                    }
                ],
                "internalFileHash": "default-htaccess-hash",
            }
        if operation == "getWebsiteHtaccessIpsRule":
            return website.get("htaccessIps") or {
                "kind": "allow",
                "ips": [],
                "internalRuleId": "ip-default-01",
            }
        if operation == "getWebsiteMetrics":
            return {"granularity": query.get("granularity", "day"), "items": [{"timestamp": "2026-11-23T00:00:00Z", "pageViews": 42, "transfer": 1048576}]}
        if operation == "getWebsiteFsQuotaLimits":
            return {"usage": 73400320, "total": 1073741824}
        if operation == "getWebsiteCgroupLimits":
            return {"cpu": 100, "memory": 536870912, "processes": 50}
        if operation == "getWebsiteEnabledPhpExtensions":
            return {"items": ["curl", "mbstring", "mysqli", "openssl"]}
        if operation == "getWebsiteLsphpSettings":
            return {"version": "8.3", "memoryLimit": "256M", "maxExecutionTime": 60}
        if operation == "getWebsitePhpErrorLog":
            entries = website.get("phpErrorLog") or []
            lines = [
                f"[{entry.get('timestamp', '')}] {str(entry.get('level', 'info')).upper()}: {entry.get('message', '')}"
                for entry in entries
                if isinstance(entry, dict)
            ]
            return {"items": entries, "log": "\n".join(lines)}

        return {"success": True, "data": []}

    def _dns_query_response(
        self,
        customer: dict[str, Any],
        website: dict[str, Any],
        domain_id: str,
        query: dict[str, str],
    ) -> dict[str, Any]:
        depth = query.get("resolveDepth", "short")
        if depth not in VALID_RESOLVE_DEPTHS:
            raise CatalogBadRequest(f"Invalid resolveDepth: {depth}")

        fqdn = self._resolve_domain_name(customer, domain_id)
        tld = fqdn.rsplit(".", 1)[-1] if "." in fqdn else "example"
        root: dict[str, Any] = {
            "name": ".",
            "servers": [{"name": "a.root-servers.net", "ip": "198.41.0.4"}],
            "result": "NOERROR",
            "rawPacket": "mock-base64-dns-wire-packet",
        }
        if depth in {"detailed", "queryAllTldNs"}:
            root["children"] = [
                {
                    "name": f"{tld}.",
                    "servers": [
                        {"name": "ns1.milesweb.com", "ip": "198.51.100.1"},
                        {"name": "ns2.milesweb.com", "ip": "198.51.100.2"},
                    ],
                    "result": "NOERROR",
                }
            ]

        tld_ns_map: dict[str, Any] = {
            "ns1.milesweb.com": {
                "ips": ["198.51.100.1"],
                "status": "resolved",
                "records": [{"type": "A", "value": "198.51.100.42", "ttl": 3600}],
            }
        }
        if depth == "queryAllTldNs":
            tld_ns_map["ns2.milesweb.com"] = {
                "ips": ["198.51.100.2"],
                "status": "resolved",
                "records": [{"type": "A", "value": "198.51.100.42", "ttl": 3600}],
            }

        return {
            "fqdn": fqdn,
            "resolveDepth": depth,
            "root": root,
            "tldNsMap": tld_ns_map,
            "internalResolverNode": f"resolver.{website['server']}.internal",
            "debugTrace": "internal-dns-trace-id-001",
        }


catalog = Phase2Catalog()
