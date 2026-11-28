# MilesWeb Enhance Mock API

A **read-only FastAPI mock backend** that simulates the MilesWeb customer API and Enhance hosting panel API. It is the development and testing backend for the **MilesWeb MCP server** (`milesweb_mcp`), which connects Claude / ChatGPT to MilesWeb hosting accounts.

---

## Architecture

```
Claude / ChatGPT
      │
      ▼  MCP protocol
MCP Server  (milesweb_mcp — deployed on Render)
      │
      ├──► HTTP  (Authorization: Bearer <token>) ──► Enhance & Connector endpoints
      │
      └──► POST /includes/api.php (form-encoded username/password) ──► WHMCS mock
      │
      ▼  reads
data/customers.json & data/whmcs.json  (fixture data — never written)
```

The MCP server never trusts a raw `clientId` argument from the AI. All customer-scoped Enhance and Connector routes authenticate via the verified Bearer JWT (`Authorization: Bearer <token>`) and enforce tenant isolation from the token identity.

---

## Project layout

```
app/
  config.py                  environment + settings (pydantic-settings)
  customer_repository.py     read-only fixture data access layer
  main.py                    FastAPI application entry point
  openapi.py                 OpenAPI / Swagger UI customization
  security.py                shared HTTPBearer authentication dependency
  routers/
    auth_router.py           /auth login and token verification endpoints
    customer_router.py       /api/v1/connector/customer endpoints
    enhance_router.py        440 remaining Enhance mock operations (GET/POST/PUT/PATCH/DELETE)
    phase2_router.py         58 Enhance mock GET operations (42 base + 16 extra)
    whmcs_router.py          POST /includes/api.php WHMCS mock endpoint
  services/
    enhance_spec.py          OpenAPI spec loader, validator & schema synthesizer
    enhance_state.py         in-memory stateful CRUD, async jobs & role/tenant isolation
    phase2_catalog.py        Enhance mock data provider + tenant/role isolation
    token_service.py         JWT creation and verification (HS256, PBKDF2)
    whmcs_service.py         WHMCS mock billing & support data provider
data/
  customers.json             users, hosting, and Enhance fixture data
  mpanel_customers.json      11 mPanel customer fixture records (non-loginable)
  whmcs.json                 WHMCS clients, invoices, products, and tickets
enhance-api-reference-updated.json  Enhance v12.26.3 OpenAPI reference (500 operations)
tests/
  conftest.py                shared fixtures, state reset, and test client setup
  test_auth.py               authentication, JWT, login tests
  test_customer_connector.py connector API and tenant isolation tests
  test_phase2_catalog.py     Phase 2 operations and authorization tests
  test_new_batch_endpoints.py 7 batch Enhance operations tests
  test_enhance_extra.py      16 additional Enhance GET operations & role tests
  test_enhance_full_coverage.py 440 Enhance ops, CRUD flows, 401/403/404/422 tests
  test_whmcs.py              WHMCS mock API & fixture integrity tests
  test_audit_gaps.py         edge-case and regression tests
requirements.txt
.env.example
```

---

## Quick start

Python 3.11+ recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env as needed (DUMMY_LOGIN_PASSWORD, JWT_SECRET_KEY, WHMCS mock creds)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Browse the full interactive API docs at **http://127.0.0.1:8000/docs**.

### Environment variables (`.env`)

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET_KEY` | HS256 signing key for dynamic access tokens |
| `DUMMY_LOGIN_PASSWORD` | Password required for `POST /auth/login` (`manish.kulkarni@milesweb.com`) |
| `PHASE2_TEST_TOKENS` | Comma-separated `token:clientId` pairs for local mock testing without login |
| `MOCK_WHMCS_IDENTIFIER` | WHMCS API `username` form field accepted by `POST /includes/api.php` |
| `MOCK_WHMCS_SECRET` | WHMCS API `password` form field accepted by `POST /includes/api.php` |

---

## Authentication rules

| Route group | Required headers |
| --- | --- |
| `GET /health` | None |
| `POST /auth/login` | `Content-Type: application/json` (`X-Connector-Key` not required; ignored if sent) |
| `GET /auth/me`, `/auth/verify` | `Authorization: Bearer <token>` |
| `/api/v1/connector/*` | `Authorization: Bearer <token>` (extra `X-Connector-Key` ignored if sent) |
| `/orgs/…`, `/login`, `/v2/…`, `/websites/…` (Phase 2) | `Authorization: Bearer <token>` (extra `X-Connector-Key` ignored if sent) |
| `POST /includes/api.php` (WHMCS mock) | Form fields `username` (`MOCK_WHMCS_IDENTIFIER`) + `password` (`MOCK_WHMCS_SECRET`); no Bearer token |

---

## Implemented APIs

### 1. System

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | None | Service health check |

---

### 2. Authentication & Token Verification

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/auth/login` | None | Validate credentials → return signed JWT |
| GET | `/auth/me` | Bearer | Decode token → return customer profile |
| POST | `/auth/verify` | None | Verify token from request body `{"token": "…"}` |
| GET | `/auth/verify` | Bearer or `?token=` | Verify token from header or query param |

#### Enabled login account (`POST /auth/login`)

Only one account is enabled for `POST /auth/login` (password read from `DUMMY_LOGIN_PASSWORD` in `.env`):

| Email | Name | Client ID | Customer `org_id` |
| --- | --- | --- | --- |
| `manish.kulkarni@milesweb.com` | `MilesWeb` | `"123"` | `3849700e-95b0-4656-be7b-0d1268598bb1` |

- `data/mpanel_customers.json` stores 11 mPanel customer fixture records (non-loginable).
- `data/customers.json` still provides Enhance/connector fixture accounts for `PHASE2_TEST_TOKENS` (`mock-token-*`) and WHMCS mock scenarios (`12345`–`12350`), but those emails cannot sign in via `POST /auth/login`.

```powershell
# 1. Login and capture the token (replace <DUMMY_LOGIN_PASSWORD> with the value in .env)
$resp = curl.exe -s -X POST "http://127.0.0.1:8000/auth/login" `
  -H "Content-Type: application/json" `
  -d '{"email": "manish.kulkarni@milesweb.com", "password": "<DUMMY_LOGIN_PASSWORD>"}' | ConvertFrom-Json
$token = $resp.token

# 2. Use the token
curl.exe -H "Authorization: Bearer $token" "http://127.0.0.1:8000/auth/me"
```

---

### 3. Customer Connector API

These endpoints authenticate via the verified Bearer JWT (`Authorization: Bearer <token>`), derive the caller's `clientId` from the token (and reject any `clientId` query param for a different customer with `403`). All endpoints are `GET`-only; `POST`/`PUT`/`DELETE` return `405`.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/connector/customer` | Customer profile (name, email, status) |
| GET | `/api/v1/connector/customer/hosting-services` | Active hosting services |
| GET | `/api/v1/connector/customer/domains` | Registered domains |

**Errors:** missing/invalid token → `401`; mismatched `clientId` query param → `403`; unknown `clientId` → `404`; non-numeric or `<= 0` `clientId` → `422`; customer with no hosting/domains → `200` with `{"success": true, "data": []}`.

```powershell
curl.exe -H "Authorization: Bearer $token" `
  "http://127.0.0.1:8000/api/v1/connector/customer"
```

---

### 4. Phase 2 — Enhance Mock Operations (42 endpoints)

All 42 Enhance read-only GET operations from the supplied API catalog are implemented. Each request requires `Authorization: Bearer <token>` (any extra `X-Connector-Key` header is ignored). Every `org_id`, `website_id`, `subscription_id`, `domain_id`, `backup_id`, and `app_id` in the path is validated against the authenticated customer — another customer's resource returns `404`.

Websites may have multiple domain mapping IDs (primary + additional); **all** are checked during `domain_id` authorization.

| Operation name | Path | Proposed MCP tool |
| --- | --- | --- |
| `getDomains` | `GET /orgs/{org_id}/domains` | `list_organization_domains` |
| `getDomainAuthNs` | `GET /orgs/{org_id}/domains/{domain_id}/auth-ns` | `get_domain_nameservers` |
| `getDomainLocalRemote` | `GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}/local_remote` | `get_domain_mail_routing` |
| `getFtpUsers` | `GET /orgs/{org_id}/websites/{website_id}/ftp/users` | `get_ftp_users` |
| `getInstallableApps` | `GET /orgs/{org_id}/subscriptions/{subscription_id}/installable-apps` | `list_subscription_installable_apps` |
| `getLogin` | `GET /login` | `get_login` |
| `getLoginMemberships` | `GET /login/memberships` | `get_login_memberships` |
| `getOrg` | `GET /orgs/{org_id}` | `get_org` |
| `getOrgActivities` | `GET /v2/orgs/{org_id}/activities` | `get_org_activities` |
| `getSubscription` | `GET /orgs/{org_id}/subscriptions/{subscription_id}` | `get_subscription` |
| `getSubscriptionBandwidthUsage` | `GET /orgs/{org_id}/subscriptions/{subscription_id}/bandwidth` | `get_bandwidth_usage` |
| `getSubscriptionsToParent` | `GET /orgs/{org_id}/subscriptions` | `get_subscriptions` |
| `getWebsite` | `GET /orgs/{org_id}/websites/{website_id}` | `get_website` |
| `getWebsiteApps` | `GET /orgs/{org_id}/websites/{website_id}/apps` | `list_website_apps` |
| `getWebsiteBackup` | `GET /orgs/{org_id}/websites/{website_id}/backups/{backup_id}` | `get_backup` |
| `getWebsiteBackups` | `GET /orgs/{org_id}/websites/{website_id}/backups` | `list_backups` |
| `getWebsiteBackupStatus` | `GET /orgs/{org_id}/websites/{website_id}/status/backup` | `get_website_backup_status` |
| `getWebsiteCgroupLimits` | `GET /orgs/{org_id}/websites/{website_id}/cgroup_limits` | `get_cgroup_limits` |
| `getWebsiteDomainDnsZone` | `GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-zone` | `get_dns_zone` |
| `getWebsiteDomainMapping` | `GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}` | `get_website_domain_mapping` |
| `getWebsiteDomainMappingDnsStatus` | `GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-status` | `get_dns_status` |
| `getWebsiteDomainMappings` | `GET /orgs/{org_id}/websites/{website_id}/domains` | `list_website_domains` |
| `getWebsiteDomainSslCert` | `GET /v2/domains/{domain_id}/ssl` | `get_ssl_cert` |
| `getWebsiteEmails` | `GET /orgs/{org_id}/websites/{website_id}/emails` | `list_emails` |
| `getWebsiteEnabledPhpExtensions` | `GET /websites/{website_id}/php_extensions` | `get_php_extensions` |
| `getWebsiteFsQuotaLimits` | `GET /orgs/{org_id}/websites/{website_id}/fs_quota_limits` | `get_quota_limits` |
| `getWebsiteGitDeploys` | `GET /orgs/{org_id}/websites/{website_id}/git/deploys` | `get_git_deploys` |
| `getWebsiteGitInfo` | `GET /orgs/{org_id}/websites/{website_id}/git` | `get_git_info` |
| `getWebsiteLsphpSettings` | `GET /websites/{website_id}/lsphp_settings` | `get_php_settings` |
| `getWebsiteMetrics` | `GET /orgs/{org_id}/websites/{website_id}/metrics` | `get_metrics` |
| `getWebsiteMySQLDBs` | `GET /orgs/{org_id}/websites/{website_id}/mysql-dbs` | `get_mysql_dbs` |
| `getWebsiteMySQLUsers` | `GET /orgs/{org_id}/websites/{website_id}/mysql-users` | `get_mysql_users` |
| `getWebsitePhpErrorLog` | `GET /websites/{website_id}/php_error_log` | `get_php_errors` |
| `getWebsitePostgresqlDbs` | `GET /orgs/{org_id}/websites/{website_id}/postgresql-dbs` | `get_postgres_dbs` |
| `getWebsitePostgresqlUsers` | `GET /orgs/{org_id}/websites/{website_id}/postgresql-users` | `get_postgres_users` |
| `getWebsiteRestoreStatus` | `GET /orgs/{org_id}/websites/{website_id}/backups/{backup_id}/restore_status` | `get_website_restore_status` |
| `getWebsiteSshKeys` | `GET /orgs/{org_id}/websites/{website_id}/ssh/keys` | `get_ssh_keys` |
| `getWebsites` | `GET /orgs/{org_id}/websites` | `list_websites` |
| `getWordpressAppVersion` | `GET /orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/version` | `get_wp_version` |
| `getWordpressInfo` | `GET /orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/info` | `get_wp_info` |
| `getWordpressPlugins` | `GET /orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/plugins` | `get_wp_plugins` |
| `getWordpressThemes` | `GET /orgs/{org_id}/websites/{website_id}/apps/{app_id}/wordpress/themes` | `get_wp_themes` |

```powershell
# Using a dynamic JWT token
curl.exe `
  -H "Authorization: Bearer $token" `
  "http://127.0.0.1:8000/orgs/3849700e-95b0-4656-be7b-0d1268598bb1"

# Or using a static test token (local dev only)
curl.exe `
  -H "Authorization: Bearer mock-token-rahul" `
  "http://127.0.0.1:8000/orgs/org-rahul-001/websites/site-rahul-001"
```

> [!NOTE]
> The `granularity` query parameter on `getWebsiteMetrics` is passed through to the fixture response so the MCP server can request `daily` or `hourly` data.

#### Additional Enhance GET Operations (16 endpoints)

These 16 endpoints follow the same `Authorization: Bearer <token>` authentication and tenant isolation rules (another customer's resource returns `404`), plus resource-specific rules: `email_address` must belong to the website, `deployment_id` must belong to the website, `clone_id` must belong to the org, `getMembers` returns `403` unless the caller's role is `Owner` or `Admin`/`SuperAdmin` (while `getMember` allows `Owner`/`Admin` or the member themself), and `getJoomlaInfo` returns `400` if the `app_id` is not Joomla.

| Operation name | Path | Proposed MCP tool |
| --- | --- | --- |
| `getWebsiteEmail` | `GET /orgs/{org_id}/websites/{website_id}/emails/{email_address}` | `get_website_email_details` |
| `getWebsiteEmailClientConf` | `GET /orgs/{org_id}/websites/{website_id}/emails/{email_address}/client-conf` | `get_website_email_client_config` |
| `getWebsiteEmailAutoresponder` | `GET /orgs/{org_id}/websites/{website_id}/emails/{email_address}/autoresponder` | `get_website_email_autoresponder` |
| `getWebsiteDomainDnsQuery` | `GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}/dns-query` | `query_website_domain_dns` |
| `getCloudflareNameServers` | `GET /orgs/{org_id}/domains/{domain_id}/cloudflare/nameservers` | `get_cloudflare_nameservers` |
| `getWebsiteServerDomains` | `GET /orgs/{org_id}/websites/{website_id}/server_domains` | `get_website_server_domains` |
| `getWebsiteGitDeploymentLog` | `GET /orgs/{org_id}/websites/{website_id}/git/deploys/{deployment_id}` | `get_website_git_deployment_log` |
| `getWebsiteHtaccessRewrites` | `GET /orgs/{org_id}/websites/{website_id}/htaccess` | `get_website_rewrite_rules` |
| `getWebsiteHtaccessIpsRule` | `GET /orgs/{org_id}/websites/{website_id}/htaccess/ips` | `get_website_ip_access_rules` |
| `getScreenshotTimestamp` | `GET /orgs/{org_id}/websites/{website_id}/domains/{domain_id}/screenshot/timestamp` | `get_website_screenshot_timestamp` |
| `getJoomlaInfo` | `GET /orgs/{org_id}/websites/{website_id}/apps/{app_id}/joomla/info` | `get_joomla_details` |
| `getWebsiteClones` | `GET /orgs/{org_id}/websites/clone` | `list_website_clone_jobs` |
| `getWebsiteClone` | `GET /orgs/{org_id}/websites/clone/{clone_id}` | `get_website_clone_job` |
| `getWebsiteCloneLog` | `GET /orgs/{org_id}/websites/clone/{clone_id}/log` | `get_website_clone_log` |
| `getMembers` | `GET /orgs/{org_id}/members` | `list_organization_members` |
| `getMember` | `GET /orgs/{org_id}/members/{member_id}` | `get_organization_member` |

---

### 4b. Full Enhance API Mock Coverage (440 Additional Operations)

`enhance_router.py` + `enhance_state.py` + `enhance_spec.py` register the remaining **440** Enhance operations from [enhance-api-reference-updated.json](enhance-api-reference-updated.json) (`152 GET`, `97 POST`, `84 PUT`, `76 DELETE`, `31 PATCH`), bringing total Enhance coverage to **498 / 500** spec operations (excluding `POST /auth/login` and `POST /mpanel/token`, which are intentionally omitted; `POST /auth/login` remains the mock JWT login endpoint).

- **Stateful in-memory CRUD:** Writes (`POST` / `PUT` / `PATCH` / `DELETE`) on websites, domains, DNS zone records, mailboxes, autoresponders, MySQL/PostgreSQL DBs & users, FTP users, SSH keys, apps, backups/restores, website clones, git deploys, members, and subscriptions are reflected in subsequent `GET` reads without mutating `data/customers.json` on disk.
- **Deterministic async jobs:** `POST /orgs/{org_id}/websites/clone` and `POST /orgs/{org_id}/websites/{website_id}/git` create deterministic `"queued"` job records with inspectable logs.
- **Exact status codes & media types:** Returns `200`, `201`, `202`, empty `204`, `302`/`303` redirects (SSO/callback endpoints), raw JSON strings, `text/html` (`installComplete`), and `application/gzip` (`downloadWebsiteBackup`).
- **Tenant & permission enforcement:** Foreign `org_id` / `website_id` / `domain_id` returns `404`; non-admin `SiteAccess` members (`vikram@example.com`) receive `403` on admin/org-write/server/settings/plan/member-write routes; invalid JSON returns `400`; missing required fields return `422`.

```powershell
# Create a website, then list websites to see it
curl.exe -X POST "http://127.0.0.1:8000/orgs/org-rahul-001/websites" `
  -H "Authorization: Bearer mock-token-rahul" `
  -H "Content-Type: application/json" `
  -d '{"domain":"newsite.example","subscriptionId":5001}'

# Add a DNS record (201), then read the DNS zone
curl.exe -X POST "http://127.0.0.1:8000/orgs/org-rahul-001/websites/site-rahul-001/domains/domain-rahul-001/dns-zone/records" `
  -H "Authorization: Bearer mock-token-rahul" `
  -H "Content-Type: application/json" `
  -d '{"kind":"TXT","name":"_dmarc","value":"v=DMARC1; p=none","ttl":300}'
```

---

### 5. WHMCS Mock API (`POST /includes/api.php`)

Simulates the WHMCS external API using `application/x-www-form-urlencoded` `POST` requests (other HTTP methods return `405`). Authenticates via form fields `username` and `password` against `MOCK_WHMCS_IDENTIFIER` and `MOCK_WHMCS_SECRET` (no connector key or Bearer header). Accepts `responsetype=json` and ignores `accesskey`. Wrong credentials return `{"result":"error","message":"Authentication Failed"}`.

> [!WARNING]
> **Ownership is intentionally NOT enforced by the WHMCS mock on `GetInvoice` or `GetTicket`.** Just like real WHMCS admin API credentials, querying any valid `invoiceid` or `ticketid` returns the record with its true `userid`. The MCP server is responsible for verifying that `userid` matches the authenticated billing client.

| Action | Key parameters | Proposed MCP tool | Notes |
| --- | --- | --- | --- |
| `GetClientsDetails` | `email` or `clientid` | — (client resolution) | Returns `result`, `client.id`, `email`; error when unmatched |
| `GetInvoices` | `userid`, `limitstart`, `limitnum`, `status`, `orderby`, `order` | `list_invoices` | Includes `userid` on each row; returns `""` when empty, single object when 1 row |
| `GetInvoice` | `invoiceid` | `get_invoice_details` | Returns `userid`, `items.item`, `transactions`, `notes` (for MCP to strip) |
| `GetClientsProducts` | `clientid`, `limitstart`, `limitnum`, `serviceid` | `list_purchased_products` | Includes `username`, `password`, `dedicatedip`, `customfields` (for MCP to strip) |
| `GetTickets` | `clientid`, `limitstart`, `limitnum`, `status` | `list_support_tickets` | Includes `userid` on each row; returns `""` when empty, single object when 1 row |
| `GetTicket` | `ticketid`, `repliessort` | `get_ticket_details` | Returns `userid`, `c`, `attachments`, `replies.reply` with `admin` & `note` flags |
| `GetProducts` | `pid`, `gid`, `module` | — | Returns `products.product` catalog list |

Any other or missing `action` returns `{"result":"error","message":"Invalid or missing action"}`.

---

## Security highlights

| Concern | Implementation |
| --- | --- |
| Password storage | PBKDF2-SHA256, 260 000 iterations, per-user salt (stdlib `hashlib`) |
| Connector key comparison | `hmac.compare_digest` — constant-time, no timing oracle |
| Bearer token | HS256-signed JWT, verified on every Phase 2 and `/auth/me` request |
| Tenant isolation | Every path parameter validated against the authenticated `clientId` |
| Multi-domain ownership | Primary **and** additional domain IDs are all checked per website |
| Connector response filtering | Only whitelisted fields returned — no raw dict leaks |
| Write method blocking | Original Phase 2 & connector routes are `GET`-only unless a spec write method exists; unsupported methods → `405` |
| CORS | `allow_origins=["*"]` — intentional for local dev; **lock this down before any production use** |

---

## Running tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

**682 tests** covering:
- Single-user login (`manish.kulkarni@milesweb.com`), rejection of invalid/other accounts and old Chinmay JWTs, and 11 mPanel customer fixtures
- Dynamic JWT creation, verification, and expiry
- `/auth/me` and both `/auth/verify` variants
- Connector key authentication on all three connector endpoints
- Field filtering on connector responses
- All customer scenarios (active, suspended, no hosting, domains-only, non-admin org member)
- Phase 2 authorization: own resources accepted, another customer's resources rejected
- Cross-customer `org_id`, `website_id`, `subscription_id`, `domain_id`, `backup_id`, `app_id`, `email_address`, `deployment_id`, `clone_id` rejection
- Multi-domain ownership (primary + additional)
- All 7 batch operations (`getDomains`, `getDomainAuthNs`, `getWebsiteDomainMapping`, `getInstallableApps`, `getWebsiteBackupStatus`, `getWebsiteRestoreStatus`, `getDomainLocalRemote`)
- All 16 additional Enhance GET operations (mailboxes/autoresponder/client-conf, DNS query `resolveDepth`, Cloudflare nameservers, server domains, git deployment logs with fake secrets, htaccess rewrites & IP rules, screenshot timestamp, Joomla app info, clone jobs & 215-line clone log, org members `403`/`200`/filters)
- WHMCS mock API (`POST /includes/api.php`): credential validation, `405` on `GET`, action dispatch, `GetClientsDetails`, `GetInvoices`, `GetInvoice`, `GetClientsProducts`, `GetTickets`, `GetTicket`, empty `""` & single-object quirks, cross-client `GetInvoice`/`GetTicket` returning true `userid`, and fixture integrity checks
- `getOrgActivities` endpoint and `getWebsiteMetrics` with `granularity` query param
- `Phase2Catalog.customer()` fallback path
- Edge cases: missing headers, wrong key, malformed tokens

---

## Current status — what is done

| Area | Status |
| --- | --- |
| Auth routes (login, me, verify ×2) | ✅ Complete |
| `GET /health` | ✅ Complete |
| Customer connector API (3 endpoints) | ✅ Complete |
| All 58 Phase 2 Enhance mock operations (42 base + 16 extra) | ✅ Complete |
| All 440 remaining Enhance operations (`enhance_router.py`, 498 / 500 spec total; auth endpoints excluded) | ✅ Complete |
| WHMCS mock API (`POST /includes/api.php`, 7 actions) | ✅ Complete |
| Tenant isolation & org role enforcement (`403` for non-admin members) | ✅ Complete |
| Multi-domain ownership enforcement | ✅ Complete |
| PBKDF2 password hashing | ✅ Complete |
| 682 tests — all passing | ✅ Complete |
| OpenAPI docs at `/docs` | ✅ Complete |
| Static test token fallback for local dev | ✅ Complete |

---

## Next step — AI-Powered Hosting Account Health Report

The planned next feature is a new MCP tool (`get_hosting_health_report`) in the **MCP server** (`milesweb_mcp`) that answers:

> *"Analyze my MilesWeb hosting account and tell me if anything needs attention."*

The tool will combine multiple existing read-only Phase 2 operations to summarize:
- Website and subscription status
- Bandwidth and resource usage
- SSL certificate validity
- DNS status
- WordPress plugin / theme versions
- Backup availability
- Suspended or degraded services

**This mock backend requires zero changes to support the Health Report.** All data sources it needs (including the 7 newly added operations) are already implemented and tested here.

The Health Report implementation is entirely in `milesweb_mcp/app/mcp_server.py` on Nitin's machine (deployed at `https://milesweb-mcp-b2vu.onrender.com/mcp`).

---

## MCP server integration reference

```python
import os
import httpx

def get_customer_profile(backend_jwt: str) -> dict:
    """Example: how the MCP server calls this backend."""
    response = httpx.get(
        "http://127.0.0.1:8000/api/v1/connector/customer",
        headers={"Authorization": f"Bearer {backend_jwt}"},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()["data"]
```

> [!WARNING]
> Never accept `clientId` as a free-form argument from the AI model. Always derive it from the already-verified authentication context. Never log the connector key or raw request headers.
