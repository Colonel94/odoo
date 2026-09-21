# FleetFlow — NEXT_REVIEW

**Review type:** Review-and-planning pass (no roadmap implementation).
**Date:** 21 September 2026.
**Reviewer:** Claude Code (Opus 4.8), local session.
**Scope:** Verify current reality of the `Colonel94/odoo` checkout + FleetFlow addon, and assess the revised hosted-tenancy requirements TEN-01…TEN-06 from `fleetflow-claude-handoff-v2.md`.

This report corrects the stale status carried in the documentation ("unexecuted runtime tests, no implementation"). That status is **no longer accurate** for the local environment. It remains accurate for GitHub (nothing pushed) and for the hosted/multi-tenant product (not started).

---

## 1. Environment and commit

| Item | Value (verified this session) |
|---|---|
| Repo root | `C:\Users\USER\Desktop\Fleetflow` = full Odoo 16.0 checkout + FleetFlow |
| Core baseline (HEAD) | `7d63cda14808a1b3e363f66a21ee133b4a41a3a6` (Odoo 16.0, May 2023) — **unmodified** |
| FleetFlow addon / deploy layer | Present in working tree, **untracked/uncommitted** (`?? custom_addons/`, `?? fleetflow/`) |
| Runtime Odoo | Container image `odoo:16.0`, version `16.0-20250909` |
| Reproducible image pin | `odoo@sha256:0f36a5002a200bb1649771c2cb9403ca5392d7ac4bb23f9ad500b339df3f5a3a` (created 2025-09-09) |
| Database | PostgreSQL 15 (`postgres:15`), single DB `fleetflow` |
| Web binding | `127.0.0.1:8069` only. DB port **not** published to host. |
| App DB role | `fleetflow` — NOSUPERUSER, NOCREATEDB, NOCREATEROLE (verified via `pg_roles`) |
| Runtime config | `list_db=False`, `dbfilter=^fleetflow$`, `proxy_mode=False`, `addons_path=<image core>,/workspace/custom_addons` |

**Deviation from the delivered deployment design (already applied, documented):** the delivered `entrypoint.py` ran `/workspace/odoo-bin` (old checkout core). That is incompatible with the image's newer bundled addons (`ImportError: get_public_method`). Resolved in the **deployment layer only** by running the image's coherent core with `addons_path = image core + custom_addons`. Core Odoo untouched; addon unchanged. See `IMPLEMENTATION_STATUS.md` note and `entrypoint.py` header.

## 2. Executive findings

1. **The single-tenant application works and is verified locally.** Module installs, all 14 integration tests pass, and the live Owl workspace renders with zero console/page/network errors at 1440 px and 390 px, including correct server-side role filtering (technician view is scoped and loses create/Reports).
2. **Intra-customer authorization is solid** (company isolation, record rules, role gates, forged-write/context-injection defenses — all test-covered). The handoff is explicit that this is **not** a tenant boundary.
3. **The hosted, multi-tenant product does not exist yet.** There is one runtime, one database, one filestore, no host routing, no per-customer branding, and no provisioning. **TEN-01…TEN-06 are largely Missing or Blocked** (see `TENANT_REQUIREMENTS_MATRIX.md`).
4. **Nothing is on GitHub.** HEAD is the untouched Odoo baseline; the addon is an uncommitted working tree. No PR exists.
5. **No payment integration exists** and none is stubbed — reported honestly, per TEN-04.

## 3. What was tested (evidence)

| Check | Command | Result |
|---|---|---|
| Static structure | `python fleetflow/check_static.py` | PASS (9 py, 4 xml, assets, refs, 9 ACLs, buttons) |
| Module install | `python fleetflow/manage.py init` | `fleetflow` state = **installed**; web healthy; login HTTP 200 |
| Integration tests | `python fleetflow/manage.py test` | **0 failed, 0 error(s) of 14 tests** |
| Live UI (manager) | Playwright login `ff_manager`, workspace | Renders; metrics 5/1/1/1; queue FF/2026/0000x; 0 console errors; no 390 px overflow |
| Live UI (technician) | Playwright login `ff_tech` | Scoped to 1 assigned order; no Reports; no "New work order"; 0 console errors |
| DB role privileges | `pg_roles` query | NOSUPERUSER/NOCREATEDB/NOCREATEROLE confirmed |

## 4. Defects and gaps found

| # | Severity | Area | Finding |
|---|---|---|---|
| D1 | Fixed (this review's predecessor session) | Deploy | Old-checkout core vs new image addons import crash. Resolved in deploy layer. |
| D2 | Fixed | Tests | `test_company_isolation` used a tuple in `assertRaises`, which the image's Odoo rejects; rewritten as manual try/except (not weakened). |
| D3 | Open (known) | Concurrency | No multi-connection race regression for competing transitions (handoff step 8 / P3.6). SQL `FOR UPDATE` locks exist but are only single-connection tested. |
| D4 | Open (expected) | Tenancy | No tenant isolation, host routing, branding, provisioning, or recovery — the entire hosted model (TEN-01…06). |
| D5 | Open | Delivery | Addon uncommitted; no branch/PR on GitHub. |

## 5. What was NOT tested / out of scope this pass

- Any multi-tenant behavior (only one tenant exists — cannot run TEN-06).
- Concurrency race conditions between competing transitions (D3).
- Backup/restore, upgrade/rollback, performance at scale (Phase 6).
- Keyboard-only navigation and full accessibility audit (partial: viewports + contrast checked visually).
- Remote/production deployment, TLS, payments — explicitly excluded by the pack.

## 6. Recommendation

Phase 0 is effectively **complete except for two artifacts and a decision**: (a) commit the verified addon (D5), (b) approve the maintained-baseline version decision (P0.4), which this environment already exercises implicitly by running on the maintained `odoo:16.0` image. The architecture is captured in `ADR-HOSTED-TENANCY.md`. The single bounded next implementation step is **Phase 1 · P1.5 — two isolated local tenant fixtures + trusted host routing**, because every hosted requirement and the TEN-06 launch gate depend on it. See `NEXT_IMPLEMENTATION_PROMPT.md`.

Nothing here authorizes deployment, payments, or a public pilot.
