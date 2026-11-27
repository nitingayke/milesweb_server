"""In-memory stateful Enhance API store seeded from data/customers.json.

Supports deterministic CRUD, async job state transitions, tenant/org isolation,
and role-based access control without mutating fixture files on disk.
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

from app.services.enhance_spec import EnhanceOpSpec, load_raw_spec, synthesize_from_schema
from app.services.phase2_catalog import ADMIN_ROLES, CatalogBadRequest, CatalogForbidden, CatalogNotFound, catalog

_SEQ = itertools.count(1000)


def _next_id(prefix: str) -> str:
    return f"{prefix}-{next(_SEQ)}"


class EnhanceStateStore:
    """Mutable per-process state layered on top of Phase2Catalog fixtures."""

    def __init__(self) -> None:
        self._seeded = False
        self._orgs: dict[str, dict[str, Any]] = {}
        self._websites: dict[str, dict[str, Any]] = {}
        self._org_websites: dict[str, list[str]] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._org_subscriptions: dict[str, list[str]] = {}
        self._domains: dict[str, dict[str, Any]] = {}
        self._org_domains: dict[str, list[str]] = {}
        self._dns_zones: dict[str, list[dict[str, Any]]] = {}
        self._mysql_dbs: dict[str, list[dict[str, Any]]] = {}
        self._mysql_users: dict[str, list[dict[str, Any]]] = {}
        self._pg_dbs: dict[str, list[dict[str, Any]]] = {}
        self._pg_users: dict[str, list[dict[str, Any]]] = {}
        self._ftp_users: dict[str, list[dict[str, Any]]] = {}
        self._ssh_keys: dict[str, list[dict[str, Any]]] = {}
        self._backups: dict[str, list[dict[str, Any]]] = {}
        self._members: dict[str, list[dict[str, Any]]] = {}
        self._clones: dict[str, list[dict[str, Any]]] = {}
        # Generic collection store keyed by (scope_id, resource_group) -> {item_id: dict}
        self._collections: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        # Key-value singleton store keyed by (scope_id, op_or_resource_key) -> Any
        self._singletons: dict[tuple[str, str], Any] = {}

    def reset(self) -> None:
        """Reset all in-memory state (used by tests for isolation)."""
        self._seeded = False
        self.__init__()

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        self._seeded = True
        for cust in catalog._customers():
            org = cust.get("organization")
            if org and org.get("id"):
                oid = org["id"]
                if oid not in self._orgs:
                    self._orgs[oid] = copy.deepcopy(org)
                    self._org_websites.setdefault(oid, [])
                    self._org_subscriptions.setdefault(oid, [])
                    self._org_domains.setdefault(oid, [])
                    self._clones[oid] = copy.deepcopy(org.get("websiteClones", []))
                    self._members[oid] = copy.deepcopy(catalog._org_members(oid, cust))
                elif "members" in org:
                    self._orgs[oid] = copy.deepcopy(org)
                    self._clones[oid] = copy.deepcopy(org.get("websiteClones", []))
                    self._members[oid] = copy.deepcopy(org.get("members", []))

            sub = cust.get("subscription")
            if sub and sub.get("id") is not None and org and org.get("id"):
                sid = str(sub["id"])
                self._subscriptions[sid] = copy.deepcopy(sub)
                if sid not in self._org_subscriptions[org["id"]]:
                    self._org_subscriptions[org["id"]].append(sid)

            site = cust.get("website")
            if site and site.get("id") and org and org.get("id"):
                wid = site["id"]
                oid = org["id"]
                site_copy = copy.deepcopy(site)
                site_copy.setdefault("orgId", oid)
                if sub:
                    site_copy.setdefault("subscriptionId", sub["id"])
                self._websites[wid] = site_copy
                if wid not in self._org_websites[oid]:
                    self._org_websites[oid].append(wid)

                did = site.get("domainId")
                if did:
                    self._domains[did] = {
                        "id": did,
                        "orgId": oid,
                        "websiteId": wid,
                        "domain": site.get("domain", "example.com"),
                        "dkim": True,
                        "spf": True,
                        "cloudflareStatus": "Connected",
                        "cloudflareTokenFriendlyName": "MilesWeb Cloudflare",
                    }
                    self._org_domains[oid].append(did)
                    self._dns_zones[did] = [
                        {
                            "id": "dns-001",
                            "kind": "A",
                            "name": "@",
                            "value": "198.51.100.42",
                            "ttl": 3600,
                            "proxy": False,
                        }
                    ]
                for add_did in site.get("additionalDomainIds", []):
                    self._domains[add_did] = {
                        "id": add_did,
                        "orgId": oid,
                        "websiteId": wid,
                        "domain": f"extra.{site.get('domain', 'example.com')}",
                        "dkim": True,
                        "spf": True,
                        "cloudflareStatus": "Connected",
                        "cloudflareTokenFriendlyName": "MilesWeb Cloudflare",
                    }
                    self._org_domains[oid].append(add_did)
                    self._dns_zones[add_did] = [
                        {
                            "id": "dns-001",
                            "kind": "A",
                            "name": "@",
                            "value": "198.51.100.42",
                            "ttl": 3600,
                            "proxy": False,
                        }
                    ]

                self._mysql_dbs[wid] = [
                    {"name": "site_db", "size": 12582912, "createdAt": "2025-04-01T10:00:00Z", "userCount": 1}
                ]
                self._mysql_users[wid] = [
                    {
                        "name": "site_user",
                        "username": "site_user",
                        "host": "localhost",
                        "accessHosts": ["localhost", "127.0.0.1"],
                        "createdAt": "2025-04-01T10:05:00Z",
                    }
                ]
                self._pg_dbs[wid] = [
                    {"name": "site_postgres", "size": 0, "createdAt": "2025-04-01T10:00:00Z", "userCount": 1}
                ]
                self._pg_users[wid] = [
                    {
                        "name": "site_pg_user",
                        "username": "site_pg_user",
                        "accessHosts": ["localhost"],
                        "createdAt": "2025-04-01T10:05:00Z",
                    }
                ]
                self._ftp_users[wid] = [
                    {"account": "siteuser", "username": "siteuser", "homeDir": f"/home/siteuser/{site['domain']}"}
                ]
                self._ssh_keys[wid] = [
                    {
                        "id": "ssh-001",
                        "name": "deployment-key",
                        "fingerprint": "SHA256:mockfingerprint",
                        "createdAt": "2025-06-15T12:00:00Z",
                    }
                ]
                self._backups[wid] = [
                    {"id": 9001, "createdAt": "2026-11-20T01:00:00Z", "size": 10485760, "status": "completed"}
                ]

        # Seed default platform servers & plans under global scope
        self._collections[("global", "servers")] = {
            "srv-mock-01": {
                "id": "srv-mock-01",
                "hostname": "in-mock-01.milesweb.example",
                "friendlyName": "Mumbai App Node 01",
                "ipv4": "198.51.100.42",
                "groupId": "grp-default",
                "roles": {"application": {"state": "enabled"}, "database": {"state": "enabled"}, "email": {"state": "enabled"}},
            }
        }
        self._collections[("global", "plans")] = {
            "1": {"id": 1, "name": "Business Hosting", "planType": "shared", "allowServerGroupSelection": False},
            "2": {"id": 2, "name": "Shared Hosting", "planType": "shared", "allowServerGroupSelection": False},
        }

    def authorize_and_check(
        self,
        op: EnhanceOpSpec,
        client_id: int,
        path_params: dict[str, str],
    ) -> tuple[dict[str, Any], str | None]:
        """Validate tenant ownership and role permissions. Returns (customer, org_id)."""
        self._ensure_seeded()
        customer = catalog.customer(client_id)
        if customer is None:
            raise CatalogNotFound("Customer not found")

        org = customer.get("organization")
        caller_org_id = org.get("id") if org else None

        if "org_id" in path_params:
            if not caller_org_id or path_params["org_id"] != caller_org_id:
                raise CatalogNotFound("Organization not found")
        if "customer_org_id" in path_params:
            if path_params["customer_org_id"] != caller_org_id:
                raise CatalogNotFound("Customer organization not found")

        website_id = path_params.get("website_id") or path_params.get("websiteId")
        if website_id is not None:
            if not caller_org_id or website_id not in self._org_websites.get(caller_org_id, []):
                raise CatalogNotFound("Website not found")
            # SiteAccess members can only access their assigned sites
            roles = catalog._caller_roles_in_org(customer, org) if org else []
            if not any(r in ADMIN_ROLES for r in roles):
                allowed_sites = customer.get("memberSiteAccess")
                if allowed_sites is not None and website_id not in allowed_sites:
                    raise CatalogForbidden("Insufficient permissions for this website")

        if "subscription_id" in path_params:
            sub_id = str(path_params["subscription_id"])
            if not caller_org_id or sub_id not in self._org_subscriptions.get(caller_org_id, []):
                raise CatalogNotFound("Subscription not found")

        if "domain_id" in path_params:
            dom_id = str(path_params["domain_id"])
            org_doms = set(self._org_domains.get(caller_org_id or "", []))
            allowed_doms = catalog._allowed_domain_ids(customer) | org_doms
            if dom_id not in allowed_doms:
                raise CatalogNotFound("Domain not found")

        if "clone_id" in path_params:
            cid = path_params["clone_id"]
            if not caller_org_id or not any(c.get("id") == cid for c in self._clones.get(caller_org_id, [])):
                raise CatalogNotFound("Clone job not found")

        if "member_id" in path_params:
            mid = path_params["member_id"]
            if not caller_org_id or not any(m.get("id") == mid for m in self._members.get(caller_org_id, [])):
                raise CatalogNotFound("Member not found")

        if "login_id" in path_params:
            login_id = (customer.get("login") or {}).get("id")
            if path_params["login_id"] != login_id:
                raise CatalogNotFound("Login not found")

        # Role-based permission checks (Owner/Admin required for admin/platform/member-write endpoints)
        roles = catalog._caller_roles_in_org(customer, org) if org else ["Owner"]
        is_admin = any(r in ADMIN_ROLES for r in roles)
        if not is_admin:
            p = op.path
            if (
                p.startswith("/servers")
                or p.startswith("/settings")
                or p.startswith("/plans")
                or "/members" in p
                or "/invites" in p
                or "/plans" in p
                or "/branding" in p
                or "/customers" in p
                or (p == "/orgs/{org_id}" and op.method in {"PATCH", "PUT", "DELETE"})
                or (p == "/orgs/{org_id}/websites" and op.method in {"POST", "DELETE"})
                or (p == "/orgs/{org_id}/subscriptions" and op.method in {"POST", "DELETE"})
            ):
                raise CatalogForbidden("Owner or Admin role required for this operation")

        return customer, caller_org_id

    def handle(
        self,
        op: EnhanceOpSpec,
        client_id: int,
        path_params: dict[str, str],
        query_params: dict[str, str],
        body: Any,
    ) -> Any:
        """Execute an Enhance operation against mutable state or schema synthesis."""
        customer, org_id = self.authorize_and_check(op, client_id, path_params)
        scope_id = org_id or f"client-{client_id}"
        website_id = path_params.get("website_id") or path_params.get("websiteId")

        # 1. Stateful website CRUD
        if op.path == "/orgs/{org_id}/websites" and op.method == "POST":
            return self._create_website(org_id or scope_id, body)
        if op.path == "/orgs/{org_id}/websites" and op.method == "DELETE":
            return self._delete_websites(org_id or scope_id, body)
        if op.path in {"/orgs/{org_id}/websites/{website_id}", "/websites/{website_id}"} and op.method in {"PATCH", "PUT"}:
            return self._update_website(website_id or "", body, op)
        if op.path == "/websites/{website_id}" and op.method == "GET":
            return self._websites.get(website_id or "", {})
        if op.path == "/websites/{website_id}" and op.method == "DELETE":
            return self._delete_websites(org_id or scope_id, {"websiteIds": [website_id]})

        # 2. Stateful domain & DNS CRUD
        if op.path == "/orgs/{org_id}/domains" and op.method == "POST":
            return self._create_org_domain(org_id or scope_id, body)
        if op.path == "/orgs/{org_id}/domains/{domain_id}" and op.method == "DELETE":
            return self._delete_org_domain(org_id or scope_id, path_params["domain_id"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/domains" and op.method == "POST":
            return self._create_website_domain(org_id or scope_id, website_id or "", body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}" and op.method == "DELETE":
            return self._delete_org_domain(org_id or scope_id, path_params["domain_id"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-zone" and op.method == "PATCH":
            return self._patch_dns_zone(path_params["domain_id"], body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-zone/records" and op.method == "POST":
            return self._create_dns_record(path_params["domain_id"], body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-zone/records/{record_id}":
            return self._dns_record_item(op.method, path_params["domain_id"], path_params["record_id"], body)

        # 3. Stateful email & autoresponder CRUD
        if op.path == "/orgs/{org_id}/websites/{website_id}/domains/{domain_id}/emails" and op.method == "POST":
            return self._create_email(website_id or "", body, domain_id=path_params["domain_id"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/emails/{email_address}" and op.method in {"PUT", "PATCH"}:
            return self._update_email(website_id or "", path_params["email_address"], body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/emails/{email_address}" and op.method == "DELETE":
            return self._delete_email(website_id or "", path_params["email_address"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/emails/{email_address}/autoresponder":
            return self._handle_autoresponder(op.method, website_id or "", path_params["email_address"], body)

        # 4. Stateful MySQL / PostgreSQL CRUD
        if op.path == "/orgs/{org_id}/websites/{website_id}/mysql-dbs" and op.method == "POST":
            return self._create_db(self._mysql_dbs, website_id or "", body, "mysql")
        if op.path == "/orgs/{org_id}/websites/{website_id}/mysql-dbs/{db_name}" and op.method == "DELETE":
            return self._delete_by_key(self._mysql_dbs, website_id or "", "name", path_params["db_name"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/mysql-users" and op.method == "POST":
            return self._create_db_user(self._mysql_users, website_id or "", body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/mysql-users/{username}" and op.method == "DELETE":
            return self._delete_by_key(self._mysql_users, website_id or "", "username", path_params["username"])

        if op.path == "/orgs/{org_id}/websites/{website_id}/postgresql-dbs" and op.method == "POST":
            return self._create_db(self._pg_dbs, website_id or "", body, "postgresql")
        if op.path == "/orgs/{org_id}/websites/{website_id}/postgresql-dbs/{db_name}" and op.method == "DELETE":
            return self._delete_by_key(self._pg_dbs, website_id or "", "name", path_params["db_name"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/postgresql-users" and op.method == "POST":
            return self._create_db_user(self._pg_users, website_id or "", body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/postgresql-users/{username}" and op.method == "DELETE":
            return self._delete_by_key(self._pg_users, website_id or "", "username", path_params["username"])

        # 5. Stateful FTP / SSH / Apps
        if op.path == "/orgs/{org_id}/websites/{website_id}/ftp/users" and op.method == "POST":
            return self._create_ftp_user(website_id or "", body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/ftp/users/{username}" and op.method == "DELETE":
            return self._delete_by_key(self._ftp_users, website_id or "", "account", path_params["username"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/ssh/keys" and op.method == "POST":
            return self._create_ssh_key(website_id or "", body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/ssh/keys/{key_id}" and op.method == "DELETE":
            return self._delete_by_key(self._ssh_keys, website_id or "", "id", path_params["key_id"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/apps" and op.method == "POST":
            return self._create_app(website_id or "", body)
        if op.path == "/orgs/{org_id}/websites/{website_id}/apps/{app_id}" and op.method == "DELETE":
            return self._delete_app(website_id or "", path_params["app_id"])

        # 6. Deterministic Async Jobs: Backups, Clones, Git Deploys
        if op.path == "/orgs/{org_id}/websites/{website_id}/backups" and op.method == "POST":
            return self._create_backup(website_id or "")
        if op.path == "/orgs/{org_id}/websites/{website_id}/backups/{backup_id}" and op.method == "DELETE":
            return self._delete_backup(website_id or "", path_params["backup_id"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/backups/{backup_id}/restore" and op.method == "POST":
            return self._restore_backup(website_id or "", path_params["backup_id"])
        if op.path == "/orgs/{org_id}/websites/clone" and op.method == "POST":
            return self._create_clone(org_id or scope_id, body)
        if op.path == "/orgs/{org_id}/websites/clone/{clone_id}" and op.method == "DELETE":
            return self._delete_clone(org_id or scope_id, path_params["clone_id"])
        if op.path == "/orgs/{org_id}/websites/{website_id}/git" and op.method == "POST":
            return self._create_git_deploy(website_id or "", body)

        # 7. Stateful Members & Subscriptions
        if op.path == "/orgs/{org_id}/members" and op.method == "POST":
            return self._create_member(org_id or scope_id, body)
        if op.path == "/orgs/{org_id}/members/{member_id}" and op.method in {"PUT", "PATCH"}:
            return self._update_member(org_id or scope_id, path_params["member_id"], body)
        if op.path == "/orgs/{org_id}/members/{member_id}" and op.method == "DELETE":
            return self._delete_member(org_id or scope_id, path_params["member_id"])
        if op.path == "/orgs/{org_id}/subscriptions" and op.method == "POST":
            return self._create_subscription(org_id or scope_id, body)
        if op.path == "/orgs/{org_id}/subscriptions/{subscription_id}" and op.method in {"PATCH", "PUT"}:
            return self._update_subscription(path_params["subscription_id"], body)
        if op.path == "/orgs/{org_id}/subscriptions/{subscription_id}" and op.method == "DELETE":
            return self._delete_subscription(org_id or scope_id, path_params["subscription_id"])

        # 8. Generic collection/singleton state + OpenAPI schema synthesis for all remaining routes
        return self._handle_generic(op, scope_id, path_params, body)

    # ---- Stateful helpers ----

    def _create_website(self, org_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        wid = _next_id("site")
        did = _next_id("domain")
        domain = payload.get("domain") or f"{wid}.example"
        sub_ids = self._org_subscriptions.get(org_id, [])
        sub_id = payload.get("subscriptionId") or (int(sub_ids[0]) if sub_ids and sub_ids[0].isdigit() else 5001)
        site = {
            "id": wid,
            "orgId": org_id,
            "subscriptionId": sub_id,
            "domain": domain,
            "domainId": did,
            "status": "active",
            "server": "in-mock-01",
            "appId": _next_id("app"),
            "additionalDomainIds": [],
            "emails": [],
            "apps": [],
            "gitDeployments": [],
        }
        self._websites[wid] = site
        self._org_websites.setdefault(org_id, []).append(wid)
        self._domains[did] = {
            "id": did,
            "orgId": org_id,
            "websiteId": wid,
            "domain": domain,
            "dkim": True,
            "spf": True,
            "cloudflareStatus": "Disconnected",
            "cloudflareTokenFriendlyName": None,
        }
        self._org_domains.setdefault(org_id, []).append(did)
        self._dns_zones[did] = [{"id": "dns-001", "kind": "A", "name": "@", "value": "198.51.100.42", "ttl": 3600, "proxy": False}]
        self._mysql_dbs[wid] = []
        self._mysql_users[wid] = []
        self._pg_dbs[wid] = []
        self._pg_users[wid] = []
        self._ftp_users[wid] = []
        self._ssh_keys[wid] = []
        self._backups[wid] = []
        return {"id": wid}

    def _delete_websites(self, org_id: str, body: Any) -> None:
        ids = []
        if isinstance(body, dict):
            ids = body.get("websiteIds") or body.get("ids") or []
        elif isinstance(body, list):
            ids = body
        for wid in ids:
            self._websites.pop(wid, None)
            if org_id in self._org_websites and wid in self._org_websites[org_id]:
                self._org_websites[org_id].remove(wid)
        return None

    def _update_website(self, website_id: str, body: Any, op: EnhanceOpSpec) -> Any:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        if isinstance(body, dict):
            for k in ("status", "phpVersion", "subscriptionId", "tags", "kind"):
                if k in body:
                    site[k] = body[k]
        if op.success_status == 204:
            return None
        return site

    def _create_org_domain(self, org_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        did = _next_id("domain")
        domain_name = payload.get("domain") or payload.get("domainName") or f"{did}.example"
        self._domains[did] = {
            "id": did,
            "orgId": org_id,
            "domain": domain_name,
            "dkim": True,
            "spf": True,
            "cloudflareStatus": "Disconnected",
            "cloudflareTokenFriendlyName": None,
        }
        self._org_domains.setdefault(org_id, []).append(did)
        self._dns_zones[did] = [{"id": "dns-001", "kind": "A", "name": "@", "value": "198.51.100.42", "ttl": 3600, "proxy": False}]
        return {"id": did}

    def _create_website_domain(self, org_id: str, website_id: str, body: Any) -> dict[str, Any]:
        res = self._create_org_domain(org_id, body)
        did = res["id"]
        self._domains[did]["websiteId"] = website_id
        site = self._websites.get(website_id)
        if site is not None:
            site.setdefault("additionalDomainIds", []).append(did)
        return res

    def _delete_org_domain(self, org_id: str, domain_id: str) -> None:
        if domain_id not in self._domains:
            raise CatalogNotFound("Domain not found")
        self._domains.pop(domain_id, None)
        self._dns_zones.pop(domain_id, None)
        if org_id in self._org_domains and domain_id in self._org_domains[org_id]:
            self._org_domains[org_id].remove(domain_id)
        return None

    def _patch_dns_zone(self, domain_id: str, body: Any) -> None:
        records = self._dns_zones.setdefault(domain_id, [])
        if isinstance(body, dict):
            if isinstance(body.get("records"), list):
                self._dns_zones[domain_id] = list(body["records"])
            elif body.get("kind") and body.get("name"):
                records.append({
                    "id": _next_id("dns"),
                    "kind": body["kind"],
                    "name": body["name"],
                    "value": body.get("value", "198.51.100.42"),
                    "ttl": body.get("ttl", 3600),
                    "proxy": body.get("proxy", False),
                })
        return None

    def _create_dns_record(self, domain_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        rid = _next_id("dns")
        rec = {
            "id": rid,
            "kind": payload.get("kind", "A"),
            "name": payload.get("name", "@"),
            "value": payload.get("value", "198.51.100.42"),
            "ttl": payload.get("ttl", 3600),
            "proxy": payload.get("proxy", False),
        }
        self._dns_zones.setdefault(domain_id, []).append(rec)
        return {"id": rid}

    def _dns_record_item(self, method: str, domain_id: str, record_id: str, body: Any) -> Any:
        records = self._dns_zones.setdefault(domain_id, [])
        idx = next((i for i, r in enumerate(records) if str(r.get("id")) == str(record_id)), None)
        if idx is None:
            raise CatalogNotFound("DNS record not found")
        if method == "DELETE":
            records.pop(idx)
            return None
        if isinstance(body, dict):
            records[idx].update({k: v for k, v in body.items() if k != "id"})
        return records[idx]

    def _create_email(self, website_id: str, body: Any, domain_id: str | None = None) -> dict[str, Any]:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        payload = body if isinstance(body, dict) else {}
        mid = _next_id("mbx")
        domain_name = (self._domains.get(domain_id or "") or {}).get("domain") or site["domain"]
        uname = payload.get("username") or payload.get("mailboxName") or "user"
        address = payload.get("address") or (uname if "@" in str(uname) else f"{uname}@{domain_name}")
        mbx = {
            "id": mid,
            "mailboxName": payload.get("mailboxName") or address.split("@")[0],
            "address": address,
            "aliases": payload.get("aliases", []),
            "hasMailbox": payload.get("hasMailbox", True),
            "status": "active",
            "quota": payload.get("quota") or {"usage": 0, "total": 1073741824},
            "isCatchAll": payload.get("isCatchAll", False),
            "clientConf": {
                "incomingServer": f"mail.{site['domain']}",
                "outgoingServer": f"mail.{site['domain']}",
                "imapPort": 993,
                "pop3Port": 995,
                "smtpPort": 465,
                "sslEnabled": True,
                "protocol": "IMAP/POP3/SMTP",
                "authMethod": "normal_password",
                "encryption": "SSL/TLS",
                "imap": {"host": f"mail.{site['domain']}", "port": 993, "security": "SSL/TLS"},
                "pop3": {"host": f"mail.{site['domain']}", "port": 995, "security": "SSL/TLS"},
                "smtp": {"host": f"mail.{site['domain']}", "port": 465, "security": "SSL/TLS"},
                "username": address,
            },
            "autoresponder": {"enabled": False, "startDate": None, "endDate": None},
        }
        site.setdefault("emails", []).append(mbx)
        return {"id": mid}

    def _update_email(self, website_id: str, email_address: str, body: Any) -> None:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        mbx = catalog._find_mailbox(site, email_address)
        if not mbx:
            raise CatalogNotFound("Mailbox not found")
        if isinstance(body, dict):
            for k in ("aliases", "quota", "status", "isCatchAll", "hasMailbox", "mailboxName"):
                if k in body:
                    mbx[k] = body[k]
        return None

    def _delete_email(self, website_id: str, email_address: str) -> None:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        target = email_address.strip().lower()
        emails = site.get("emails", [])
        idx = next((i for i, m in enumerate(emails) if m.get("address", "").strip().lower() == target), None)
        if idx is None:
            raise CatalogNotFound("Mailbox not found")
        emails.pop(idx)
        return None

    def _handle_autoresponder(self, method: str, website_id: str, email_address: str, body: Any) -> Any:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        mbx = catalog._find_mailbox(site, email_address)
        if not mbx:
            raise CatalogNotFound("Mailbox not found")
        if method == "DELETE":
            mbx["autoresponder"] = {"enabled": False, "startDate": None, "endDate": None}
            return None
        payload = body if isinstance(body, dict) else {}
        ar = mbx.setdefault("autoresponder", {})
        ar.update({
            "id": ar.get("id") or _next_id("ar"),
            "enabled": payload.get("enabled", True),
            "startDate": payload.get("startDate", "2026-11-27"),
            "endDate": payload.get("endDate", "2026-12-05"),
            "subject": payload.get("subject", "Auto-reply"),
            "body": payload.get("body", "Out of office"),
        })
        if method == "POST":
            return {"id": ar["id"]}
        return None

    def _create_db(self, store: dict[str, list[dict[str, Any]]], website_id: str, body: Any, engine: str) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        did = _next_id("db")
        name = payload.get("name") or f"{engine}_{next(_SEQ)}"
        store.setdefault(website_id, []).append({
            "id": did,
            "name": name,
            "size": 0,
            "createdAt": "2026-11-27T10:00:00Z",
            "userCount": 0,
        })
        return {"id": did}

    def _create_db_user(self, store: dict[str, list[dict[str, Any]]], website_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        uid = _next_id("dbu")
        uname = payload.get("username") or payload.get("name") or f"user_{next(_SEQ)}"
        store.setdefault(website_id, []).append({
            "id": uid,
            "name": uname,
            "username": uname,
            "host": "localhost",
            "accessHosts": payload.get("accessHosts") or ["localhost"],
            "createdAt": "2026-11-27T10:00:00Z",
        })
        return {"id": uid}

    def _create_ftp_user(self, website_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        fid = _next_id("ftp")
        account = payload.get("account") or payload.get("username") or f"ftp_{next(_SEQ)}"
        self._ftp_users.setdefault(website_id, []).append({
            "id": fid,
            "account": account,
            "username": account,
            "homeDir": payload.get("homeDir", "/public_html"),
        })
        return {"id": fid}

    def _create_ssh_key(self, website_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        kid = _next_id("ssh")
        self._ssh_keys.setdefault(website_id, []).append({
            "id": kid,
            "name": payload.get("name", "new-ssh-key"),
            "fingerprint": "SHA256:mockgeneratedfingerprint",
            "createdAt": "2026-11-27T10:00:00Z",
        })
        return {"id": kid}

    def _create_app(self, website_id: str, body: Any) -> dict[str, Any]:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        payload = body if isinstance(body, dict) else {}
        aid = _next_id("app")
        kind = payload.get("app") or payload.get("kind") or "wordpress"
        site.setdefault("apps", []).append({
            "id": aid,
            "name": kind.capitalize(),
            "kind": kind,
            "status": "active",
        })
        return {"id": aid}

    def _delete_app(self, website_id: str, app_id: str) -> None:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        apps = site.get("apps", [])
        idx = next((i for i, a in enumerate(apps) if a.get("id") == app_id), None)
        if idx is None:
            raise CatalogNotFound("App not found")
        apps.pop(idx)
        return None

    def _delete_by_key(self, store: dict[str, list[dict[str, Any]]], website_id: str, key: str, value: str) -> None:
        items = store.get(website_id, [])
        idx = next((i for i, item in enumerate(items) if str(item.get(key)) == str(value)), None)
        if idx is None:
            raise CatalogNotFound("Resource not found")
        items.pop(idx)
        return None

    def _create_backup(self, website_id: str) -> dict[str, Any]:
        bid = 9000 + next(_SEQ)
        self._backups.setdefault(website_id, []).append({
            "id": bid,
            "createdAt": "2026-11-27T10:00:00Z",
            "size": 10485760,
            "status": "completed",
        })
        site = self._websites.get(website_id)
        if site is not None:
            site["backupStatus"] = {"status": "completed", "backupId": bid, "completedAt": "2026-11-27T10:00:00Z"}
        return {"id": bid}

    def _delete_backup(self, website_id: str, backup_id: str) -> None:
        items = self._backups.get(website_id, [])
        idx = next((i for i, b in enumerate(items) if str(b.get("id")) == str(backup_id)), None)
        if idx is None:
            raise CatalogNotFound("Backup not found")
        items.pop(idx)
        return None

    def _restore_backup(self, website_id: str, backup_id: str) -> None:
        site = self._websites.get(website_id)
        if site is not None:
            site["restoreStatus"] = {"status": "completed", "backupId": backup_id, "completedAt": "2026-11-27T10:05:00Z"}
        return None

    def _create_clone(self, org_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        cid = _next_id("clone")
        dest_id = _next_id("site-staging")
        job = {
            "id": cid,
            "sourceWebsiteId": payload.get("sourceWebsiteId") or (self._org_websites.get(org_id) or ["site-001"])[0],
            "destWebsiteId": dest_id,
            "status": "queued",
            "log": [
                {"createdAt": "2026-11-27T10:00:00Z", "message": f"Clone job {cid} queued", "percentageComplete": 0},
                {"createdAt": "2026-11-27T10:00:10Z", "message": "Syncing website files", "percentageComplete": 50},
                {"createdAt": "2026-11-27T10:00:20Z", "message": "Clone completed", "percentageComplete": 100},
            ],
        }
        self._clones.setdefault(org_id, []).append(job)
        return {"id": cid}

    def _delete_clone(self, org_id: str, clone_id: str) -> None:
        clones = self._clones.get(org_id, [])
        idx = next((i for i, c in enumerate(clones) if c.get("id") == clone_id), None)
        if idx is None:
            raise CatalogNotFound("Clone job not found")
        clones.pop(idx)
        return None

    def _create_git_deploy(self, website_id: str, body: Any) -> dict[str, Any]:
        site = self._websites.get(website_id)
        if not site:
            raise CatalogNotFound("Website not found")
        payload = body if isinstance(body, dict) else {}
        did = _next_id("deploy")
        site.setdefault("gitDeployments", []).append({
            "id": did,
            "repositoryUrl": payload.get("repositoryUrl", "https://git.example/mock/site.git"),
            "branch": payload.get("branch", "main"),
            "status": "queued",
            "completedAt": "2026-11-27T10:01:00Z",
            "log": f"[2026-11-27T10:00:00Z] Queued deployment {did}\n[2026-11-27T10:01:00Z] Deployment succeeded.",
        })
        return {"id": did}

    def _create_member(self, org_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        mid = _next_id("login")
        member = {
            "id": mid,
            "name": payload.get("name", "New Member"),
            "email": payload.get("email", f"{mid}@example.com"),
            "roles": payload.get("roles") or ["SiteAccess"],
            "isActive": True,
            "joinedAt": "2026-11-27",
            "siteAccess": payload.get("siteAccess") or [],
        }
        self._members.setdefault(org_id, []).append(member)
        return {"id": mid}

    def _update_member(self, org_id: str, member_id: str, body: Any) -> None:
        members = self._members.get(org_id, [])
        member = next((m for m in members if m.get("id") == member_id), None)
        if not member:
            raise CatalogNotFound("Member not found")
        if isinstance(body, dict):
            for k in ("roles", "isActive", "siteAccess", "name"):
                if k in body:
                    member[k] = body[k]
        return None

    def _delete_member(self, org_id: str, member_id: str) -> None:
        members = self._members.get(org_id, [])
        idx = next((i for i, m in enumerate(members) if m.get("id") == member_id), None)
        if idx is None:
            raise CatalogNotFound("Member not found")
        members.pop(idx)
        return None

    def _create_subscription(self, org_id: str, body: Any) -> dict[str, Any]:
        payload = body if isinstance(body, dict) else {}
        sid = str(5000 + next(_SEQ))
        sub = {
            "id": int(sid),
            "name": payload.get("friendlyName") or "Custom Plan",
            "status": "active",
            "plan": payload.get("planId", 1),
            "bandwidthUsage": {"usage": 0, "total": 10737418240},
        }
        self._subscriptions[sid] = sub
        self._org_subscriptions.setdefault(org_id, []).append(sid)
        return {"id": int(sid)}

    def _update_subscription(self, sub_id: str, body: Any) -> None:
        sub = self._subscriptions.get(str(sub_id))
        if not sub:
            raise CatalogNotFound("Subscription not found")
        if isinstance(body, dict):
            sub.update(body)
        return None

    def _delete_subscription(self, org_id: str, sub_id: str) -> None:
        if str(sub_id) not in self._subscriptions:
            raise CatalogNotFound("Subscription not found")
        self._subscriptions.pop(str(sub_id), None)
        if org_id in self._org_subscriptions and str(sub_id) in self._org_subscriptions[org_id]:
            self._org_subscriptions[org_id].remove(str(sub_id))
        return None

    def _handle_generic(
        self,
        op: EnhanceOpSpec,
        scope_id: str,
        path_params: dict[str, str],
        body: Any,
    ) -> Any:
        """Handle remaining Enhance endpoints using per-scope collection/singleton state + OpenAPI synthesis."""
        if op.success_status in (204, 302, 303) or op.response_media_type is None:
            # Persist singleton state if PUT/PATCH/POST writes settings/key-values
            if op.method in {"PUT", "PATCH"} and isinstance(body, dict):
                self._singletons[(scope_id, op.path)] = copy.deepcopy(body)
            elif op.method == "DELETE" and op.path_params:
                last_param = path_params.get(op.path_params[-1])
                parent_path = op.path.rsplit("/", 1)[0]
                col = self._collections.get((scope_id, parent_path))
                if col is not None and last_param in col:
                    col.pop(last_param)
            return None

        if op.response_media_type == "text/html":
            return "<html><body><h1>Enhance Installation Complete</h1></body></html>"
        if op.response_media_type == "application/gzip":
            return b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00"

        spec = load_raw_spec()

        # Collection-aware POST/GET/PUT/DELETE for parameterized sub-resources (crons, plans, servers, tokens, etc.)
        if op.method == "POST" and not op.path.endswith("}"):
            col = self._collections.setdefault((scope_id, op.path), {})
            new_id = _next_id(op.path.strip("/").split("/")[-1][:6] or "res")
            created = synthesize_from_schema(spec, op.response_schema, op.response_example, {"id": new_id} if isinstance(op.response_example, dict) and "id" in op.response_example else None)
            record = copy.deepcopy(body) if isinstance(body, dict) else {}
            if isinstance(created, dict):
                merged_record = {**created, **record}
                if "id" in created or (op.response_schema and "id" in (op.response_schema.get("properties") or {})):
                    merged_record["id"] = created.get("id", new_id)
                col[str(merged_record.get("id", new_id))] = merged_record
                return created
            col[new_id] = record
            return created

        if op.method == "GET" and (scope_id, op.path) in self._collections:
            items = list(self._collections[(scope_id, op.path)].values())
            if op.response_schema and op.response_schema.get("type") == "array":
                return items
            return {"total": len(items), "items": items}

        if op.method == "GET" and (scope_id, op.path) in self._singletons:
            return self._singletons[(scope_id, op.path)]

        return synthesize_from_schema(spec, op.response_schema, op.response_example)


enhance_state = EnhanceStateStore()
