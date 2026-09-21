# ADR — Hosted Tenancy Architecture for FleetFlow

**Status:** Proposed (review pass, 21 September 2026). Not implemented.
**Decision owner:** Omar (product/hosting). **Author:** Claude Code review pass.
**Context source:** `fleetflow-claude-handoff-v2.md` (TEN-01…06), `fleetflow-phased-delivery-plan-v2.md`.

## 1. Decision context

Omar's confirmed model: **monthly subscription, always hosted by Omar**, browser access only, with both automatic self-service signup and owner-assisted onboarding/customization. Customers never install or operate servers. The current build is a verified **single-tenant** Odoo 16 workshop app; this ADR defines the boundary and mapping needed to host multiple unrelated customers safely.

## 2. Decision: isolation model

**Chosen: one Odoo runtime + one PostgreSQL database + one filestore per customer ("container-per-tenant"), on shared host hardware.**

Rejected alternatives:
- **Odoo multi-company inside one DB as the customer boundary** — explicitly forbidden by TEN-01. Company rules are intra-customer authorization, not a security boundary between paying strangers. A bug or misconfigured record rule leaks across companies in the same DB/filestore.
- **Odoo native multi-DB (one runtime, `dbfilter` per host, many DBs)** — one runtime process holds credentials able to reach every tenant DB and every tenant's filestore directory. A single app-layer RCE or path bug crosses all tenants. Weaker than process isolation and harder to bound per-tenant resource use. Acceptable only as a documented interim, not the target.

**Trust boundary (documented, not absolute):** tenants share host kernel, Docker engine, reverse proxy and the operator. Omar (operator) can access customer data; this must be stated to customers, never denied (TEN-05). Isolation guarantees are: separate process, separate DB with a role scoped to only that DB, separate filestore volume, separate secrets, no tenant process granted CREATE DATABASE/ROLE or host/Docker socket access.

## 3. Mapping: hostname → runtime → database

```
customer subdomain (alpha.fleetflow.example)
        │   TLS terminates at reverse proxy (operator-controlled)
        ▼
reverse proxy with an ALLOWLIST  host → upstream
  - unknown/spoofed Host or X-Forwarded-Host  → 404/close (fail closed)
  - sets trusted forwarded headers; strips client-supplied ones
        ▼
tenant runtime  ff-<tenant>-web   (odoo, proxy_mode=True, workers>0)
  - dbfilter = ^<tenant_db>$   (single, fixed)
  - list_db = False;  /web/database/* management routes blocked at proxy AND config
  - db_user = ff_<tenant> (LOGIN, NOSUPERUSER/NOCREATEDB/NOCREATEROLE, owns only <tenant_db>)
        ▼
tenant database  ff_<tenant>   (separate Postgres role+db; not host-published)
tenant filestore ff-<tenant>-data volume (mounted only into that runtime)
tenant secrets   ff-<tenant>.env  (mounted only into that runtime; 0600)
```

Provisioning/control plane (creates DBs, roles, volumes, proxy entries) runs **outside** all tenant runtimes with elevated privileges it never shares with them.

## 4. Secrets, filestore, backup boundaries

- **Secrets:** one env/secret set per tenant, generated at provisioning (as today's `manage.py` does for one), never logged, git-ignored, mounted only into the owning runtime.
- **Filestore:** one named volume per tenant; never bind-mounted across tenants; never mounted into the proxy or control plane.
- **Backups:** per-tenant DB dump + filestore snapshot + minimal deploy manifest, written to an access-controlled store; restore always targets an **isolated** environment first (TEN-05/06). A restore of tenant A must be incapable of writing tenant B's volume or DB.

## 5. Standard core vs customer customization (TEN-03)

- Shared behavior stays in the versioned `fleetflow` addon, deployed to every tenant.
- Customer-specific requests become separate, reviewed, versioned optional addons, enabled **only** in that tenant's `addons_path` and recorded in that tenant's deployment manifest (core version, addon versions, enabled features).
- No core patches, no per-customer product fork, no arbitrary code upload through any onboarding/customization screen. Upgrades are staged with a tested rollback; a change to A must not alter B.

## 6. Onboarding (TEN-04): one provisioning path, two entry points

Automatic signup and owner-assisted setup both call the **same** provisioning service (unique tenant id + hostname, create role/DB/volume/secrets, write proxy allowlist entry, install addons, health check, activate). Properties: idempotent, retry-safe, concurrency-safe, and failure cleanup limited to resources that attempt created. A partially provisioned tenant is never publicly reachable. Subscription/access state is tracked **separately** from provisioning state. Payment integration is explicitly deferred and marked missing until a provider and budget are approved.

## 7. Consequences

- **Positive:** strong, easy-to-reason isolation; per-tenant resource limits; simple per-tenant backup/restore/upgrade; smallest blast radius.
- **Negative / to manage:** more containers and memory (one Odoo per tenant); a real control plane and reverse proxy must be built and hardened; operator-access transparency is required; density/cost per tenant is higher than shared-DB. Reassess with a lightweight/idle-suspend strategy if tenant count grows.
- **Interim allowance:** a *manual* pilot may run on this model with a single hand-provisioned second tenant **only after** the common isolation, branding, access and recovery gates (TEN-01/02/05 relevant parts + TEN-06 negative tests) pass. It may precede full automatic signup/billing.

## 8. Open decisions for Omar (not assumed here)

Retention/RPO/RTO targets, infra budget and density, subdomain scheme and TLS/domain management, payment provider, support-access policy and audit retention, and SLA commitments. None are fabricated in this ADR.
