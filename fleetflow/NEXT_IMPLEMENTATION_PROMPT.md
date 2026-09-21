# FleetFlow — ONE bounded next implementation prompt

**Do not execute in the review pass. This is the single next work package once Omar approves P0.4 (version baseline) and the addon is committed.**

## Work package: P1.5 — Two isolated local tenant fixtures + trusted host routing

**Why this one:** every hosted requirement (TEN-02…05) and the TEN-06 launch gate depend on a real tenant boundary existing. Today there is exactly one runtime/DB/filestore. This package builds the smallest honest version of the target architecture from `ADR-HOSTED-TENANCY.md`, **locally only**, so isolation can be tested before any customer exists.

**Dependency evidence (must hold before starting):**
- `NEXT_REVIEW.md` confirms single-tenant build, 14/14 tests pass, deploy-layer image-core fix in place.
- `ADR-HOSTED-TENANCY.md` §3 mapping is the design to implement.
- P0.4 version decision signed off by Omar; FleetFlow addon committed on a work branch.

**Applicable requirements:** TEN-01 (all sub-parts), and the local prerequisites of TEN-06.

### Scope (build)
1. A **control-plane script** (outside tenant runtimes) that provisions a tenant from one parameter set `(tenant_id, hostname)`: create a dedicated Postgres role `ff_<id>` (LOGIN, NOSUPERUSER/NOCREATEDB/NOCREATEROLE) and database `ff_<id>` owned by it; create a dedicated filestore volume and a `0600` secrets file mounted only into that tenant; install the `fleetflow` addon; health-check; activate. Idempotent and retry-safe; failure cleanup limited to what the attempt created.
2. Two tenants provisioned from that one path: `alpha` and `beta`, each its own `web` container (`proxy_mode=True`), DB, filestore, secrets. Distinct local hostnames (`alpha.fleetflow.localhost`, `beta.fleetflow.localhost`).
3. A **reverse proxy** (e.g. Traefik/nginx, local only) with a host **allowlist**: `alpha.*`→alpha upstream, `beta.*`→beta upstream, **unknown/spoofed Host or X-Forwarded-Host → fail closed (404)**. Strip client-supplied forwarded headers; set trusted ones. Block `/web/database/*` at proxy and via `list_db=False` + fixed `dbfilter=^ff_<id>$`.
4. Keep the existing single-tenant `manage.py` dev flow working unchanged (do not regress local dev).

### Scope (prove — negative tests, local, synthetic data)
Seed alpha and beta with **overlapping record IDs** and the **same user email** in both. Then demonstrate, from ordinary user sessions (not superuser):
- alpha credentials/session cannot read or modify beta data via direct URL, JSON-RPC, `db` selector, export, report, or guessed attachment id.
- alpha's DB role cannot connect to beta's DB; alpha runtime cannot read beta's filestore/secrets.
- A spoofed/unknown `Host`/`X-Forwarded-Host` does not reach any tenant.
- `/web/database/manager` and DB-list routes are blocked on both.

### Acceptance criteria (all must pass, with logged evidence)
- [ ] One provisioning implementation creates both tenants; a second run is idempotent; a killed run leaves no publicly reachable half-tenant.
- [ ] `psql` as `ff_alpha` to `ff_beta` is **denied**; volume/secret cross-mount is absent (inspected).
- [ ] Every cross-tenant read/write attempt above is **rejected**; evidence captured as commands + outputs (no screenshots-as-proof).
- [ ] Unknown host fails closed; DB-management routes blocked; each host reaches only its own tenant.
- [ ] Existing 14 tests still pass; single-tenant dev flow still works.
- [ ] No secrets in logs or committed files; `.env`/per-tenant secrets git-ignored.

### Guardrails
- Local only. **No** public deployment, TLS to the internet, real domains, payments, or real customer data.
- Do not use Odoo multi-company as the boundary. Do not weaken any existing test, role restriction, or isolation check to pass.
- Core Odoo untouched; changes live in the deployment/control-plane layer and, if needed, the addon.
- Deliver as a small reviewable commit/PR with: the control-plane script, two-tenant compose/proxy config, the negative-test script, and a `P1_5_ISOLATION_EVIDENCE.md` reporting exact commands, results, and residual shared-host risk.

**Out of scope for P1.5:** branding (P2.6/TEN-02), backups/restore (P6/TEN-05), self-service signup + billing (P7/TEN-04). Those follow once the boundary is proven.
