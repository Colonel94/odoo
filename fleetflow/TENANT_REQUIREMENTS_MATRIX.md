# FleetFlow — TENANT_REQUIREMENTS_MATRIX (TEN-01…TEN-06)

**Date:** 21 September 2026. **Baseline reviewed:** local single-tenant build (commit `7d63cda1` core + uncommitted FleetFlow addon, running on `odoo:16.0`/`16.0-20250909`).

**Status legend:** Verified · Present but unverified · Partial · Missing · Blocked.
**Rule applied:** intra-customer authorization (company/roles) is **not** counted as tenant isolation, per `fleetflow-claude-handoff-v2.md`.

---

## TEN-01 — Separate each customer's environment and data

| Sub-requirement | Status | Evidence / code / config | Exact test to prove it | Owner | Phase |
|---|---|---|---|---|---|
| One standard codebase | **Verified** | Single addon `custom_addons/fleetflow`; no per-customer fork | Diff review | Dev | P0/P1 |
| Separate runtime per customer | **Missing** | One `fleetflow-web-1` container | 2 runtimes, distinct hostnames | Dev | P1.5 |
| Separate DB per customer | **Missing** | Single DB `fleetflow` (pg has 1 app DB) | 2 DBs; A-role cannot connect to B | Dev | P1.5 |
| Separate filestore per customer | **Missing** | One `odoo-data` volume | A runtime cannot read B filestore | Dev | P1.5 |
| Restricted per-tenant DB credentials | **Partial** | Role `fleetflow` = NOSUPERUSER/NOCREATEDB/NOCREATEROLE, but owns the only DB; no A/B split | Per-tenant role limited to own DB | Dev | P1.5 |
| Provisioning privileges outside tenant runtime | **Missing** | `manage.py`/`init-db.sh` run on host, but no tenant boundary yet | Tenant proc has no CREATE DB/ROLE | Dev | P1.5 |
| Trusted hostname → environment routing, unknown hosts fail closed | **Missing** | No reverse proxy / host allowlist | Unknown host rejected; A host → A only | Dev | P1.5 |
| Strict DB selection; block public DB management | **Present but unverified** | `dbfilter=^fleetflow$`, `list_db=False` (single tenant only) | `/web/database/*` blocked; selector bypass fails | Dev | P1.5 |
| DB off public network | **Present** | DB port not host-published (compose) | Port scan from host | Dev | P1 |
| Separate backup access/restore targets | **Missing** | No backup layer | Restore A into isolated target | Ops | P6 |

**TEN-01 overall: Missing** (single-tenant; no cross-customer boundary exists).

## TEN-02 — Customer-specific branding

| Sub-requirement | Status | Evidence | Exact test | Owner | Phase |
|---|---|---|---|---|---|
| Per-customer name/logo/theme (login, workspace, reports) | **Missing** | Stock Odoo login; fixed FleetFlow brand in `workspace.scss`/`.xml` | Each host shows only its brand | Dev | P2.6 |
| Branding resolved pre-login from trusted host | **Missing** | No host→brand mapping | Pre-login brand differs per host | Dev | P2.6 |
| Branded email templates (when enabled) | **Missing** | No email branding | Outgoing mail carries tenant identity | Dev | P2.6 |
| Edit rights restricted to authorized admin/operator | **Missing** | N/A | Non-admin cannot change branding | Dev | P2.6 |
| Upload/theme validation (no HTML/JS/unrestricted CSS) | **Missing** | N/A | Malicious logo/theme rejected | Dev | P2.6 |
| No cross-tenant cache/asset leakage | **Blocked** | Needs 2 tenants | Cached-asset leakage test | Dev | P6 |

**TEN-02 overall: Missing.**

## TEN-03 — Standard core, isolated customizations

| Sub-requirement | Status | Evidence | Exact test | Owner | Phase |
|---|---|---|---|---|---|
| Shared behavior in versioned standard addon | **Verified** | `custom_addons/fleetflow` `version 16.0.1.0.0`; no core patch | Manifest/version review | Dev | P0 |
| Customer-specific addons per-tenant only | **Missing** | No customer-only addon mechanism | A addon absent from B runtime | Dev | P3/P7 |
| Deployment manifest (core+addon versions, features) | **Missing** | No manifest | Manifest exists + drives deploy | Ops | P7 |
| Staged upgrade + tested rollback | **Missing** | No upgrade/rollback procedure | Upgrade A, rollback, B unaffected | Ops | P6 |
| No arbitrary server code via onboarding/customization | **Present (by absence)** | No onboarding UI exists to abuse | Negative test once onboarding built | Dev | P7 |

**TEN-03 overall: Partial** (clean standard core exists; customization/manifest/upgrade machinery missing).

## TEN-04 — Two onboarding paths, one provisioning process

| Sub-requirement | Status | Evidence | Exact test | Owner | Phase |
|---|---|---|---|---|---|
| Automatic signup | **Missing** | None | Self-serve creates isolated tenant | Dev | P7.2 |
| Owner-assisted onboarding | **Partial (manual, unsafe as tenant)** | `manage.py init` + `users` create a single local env only | Assisted path uses same provisioning svc | Dev/Ops | P7.3 |
| One shared provisioning service, common security defaults | **Missing** | No provisioning service | Both paths call one implementation | Dev | P7.1 |
| Provisioning states, idempotency, retry, failure cleanup | **Missing** | None | Concurrent/duplicate signups → 1 env | Dev | P7.1 |
| Subscription/access state ≠ provisioning state | **Missing** | No subscription model | State model tests | Dev | P7.4 |
| Payment integration | **Missing (honest)** | None; not stubbed | N/A until provider approved | Omar | P7.2/7.4 |
| Secrets/invites/verification kept out of logs | **Present but unverified** | `.env` git-ignored; no secret printing in scripts | Log scan during provisioning | Dev | P7 |

**TEN-04 overall: Missing.**

## TEN-05 — Per-customer operation and recovery

| Sub-requirement | Status | Evidence | Exact test | Owner | Phase |
|---|---|---|---|---|---|
| Backup schedule + DB/filestore consistency | **Missing** | Named Docker volumes only | Scheduled consistent backup | Ops | P6.1 |
| Protected backup storage | **Missing** | None | Access-control on backups | Ops | P6.1 |
| Health monitoring / deployment inventory | **Partial** | Compose healthchecks exist; no inventory | Monitoring + inventory present | Ops | P6.4 |
| Staged updates + rollback | **Missing** | None | Update+rollback drill | Ops | P6.1 |
| Restore isolation (A restore ≠ touch B) | **Blocked** | Needs 2 tenants | Restore-into-isolated-target | Ops | P6.1 |
| Operator access recorded + audited, distinct from customer-admin | **Missing** | No operator audit layer | Operator action audit trail | Ops | P6.4 |
| Export/suspend/offboard/delete procedures | **Missing** | None | Documented + authorized before use | Omar/Ops | P7.4 |

**TEN-05 overall: Missing.**

## TEN-06 — Launch-blocking acceptance evidence (two tenants)

| Sub-requirement | Status | Notes |
|---|---|---|
| Two separate synthetic tenant environments | **Blocked** | Only one environment exists (prerequisite: P1.5) |
| A cannot reach B via URL/RPC/db-selector/export/attachment/session/host spoof | **Blocked** | Requires 2 tenants + host routing |
| A DB creds cannot access B DB; A runtime cannot read B filestore/secrets/backups | **Blocked** | Requires per-tenant DB roles + volumes |
| Each hostname shows only its branding (incl. cache/mobile/reports/email) | **Blocked** | Requires TEN-02 |
| Customer-specific change to A does not affect B; upgrade/rollback intact | **Blocked** | Requires TEN-03 machinery |
| Both provisioning entry points = one implementation; retry/concurrency clean | **Blocked** | Requires TEN-04 |
| Backup/restore + staged update for A preserves B; logs leak nothing | **Blocked** | Requires TEN-05 |

**TEN-06 overall: Blocked** on TEN-01…05. **This is a launch blocker for all real-customer hosting, including a manual pilot.**

---

## Roll-up

| Requirement | Status |
|---|---|
| TEN-01 Isolated env/data | **Missing** |
| TEN-02 Branding | **Missing** |
| TEN-03 Standard core + custom addons | **Partial** |
| TEN-04 Onboarding/provisioning | **Missing** |
| TEN-05 Operation/recovery | **Missing** |
| TEN-06 Two-tenant acceptance | **Blocked** |

**Bottom line:** the single-tenant workshop app is real and verified; the hosted multi-tenant product is greenfield. No requirement may be marked Verified from visual inspection or an admin-only demo.
