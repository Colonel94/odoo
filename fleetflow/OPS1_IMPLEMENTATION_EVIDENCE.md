# OPS-1 — Implementation evidence

**Increment:** OPS-1 (resource readiness and controlled allocation).
**Branch:** `feat/fleetflow-ops1` (from `feat/fleetflow-workflow-platform`).
**Date:** 23 September 2026.
**Nature:** local, synthetic-data build. Not a hosting, certification or production-readiness claim.

This report states exactly what ran and passed. A file existing is not evidence it ran.

---

## 1. Environment

| Item | Value |
|---|---|
| Runtime | `odoo:16.0` image, version `16.0-20250909` (digest `sha256:0f36a500…`) + PostgreSQL 15 |
| Core baseline | Colonel94/odoo `16.0` at `7d63cda1` — **unmodified** |
| Addons | `custom_addons/fleetflow` (maintenance) + `custom_addons/fleetflow_operations` (new) |
| Web binding | `127.0.0.1:8069` only; DB not host-published |
| Version decision | Runs on the maintained `odoo:16.0` image; a formal core-migration decision remains **open** (Omar sign-off). Documented, not silently upgraded. |

## 2. Exact commands and results

```
python fleetflow/check_static.py
  -> PASS fleetflow: 5 py, 4 xml, 9 ACL
  -> PASS fleetflow_operations: 12 py, 8 xml, 32 ACL

python fleetflow/manage.py test        # installs fleetflow_operations (+fleetflow dep),
                                        # --test-tags /fleetflow,/fleetflow_operations
  -> 0 failed, 0 error(s) of 59 tests
```

**Test breakdown (59):**
- `fleetflow` maintenance lifecycle/security — 15 (all original tests retained; +1 server-cutoff regression).
- `fleetflow_operations` — 44:
  - `test_evidence` (8): pending upload cannot self-approve; create/context cannot forge verified; verify requires compliance; exactly-one-subject; subject/company consistency; verified immutable until superseded; whole-interval local-day boundary; dispatcher cannot download evidence attachment.
  - `test_readiness` (14): valid = Ready; no published profile = Needs review; expired doc = Blocked; mid-interval expiry = Blocked; missing/unverified = Needs review; unreviewed vehicle = Needs review; wrong employer = Blocked; Uber approval does not satisfy Careem; suspended channel = Blocked; stale channel = Needs review; verified renewal restores Ready; end-of-use exceeded = Blocked; result carries no attachment content.
  - `test_allocation` (13): confirm→checkout→return; blocked-when-not-ready; two allocations one vehicle conflict; two cars one driver conflict; adjacent intervals allowed; late return blocks second checkout; active hold blocks checkout; clearing one hold keeps others; work-order cancel does not clear hold; rental capacity block conflicts with shift; odometer decrease rejected; defect return creates hold + work order; cancel before checkout.
  - `test_concurrency` (1): **two real database connections** race to reserve the same vehicle; exactly one wins, no partial state.
  - `test_security` (8): cannot forge allocation confirmed via write; nor via create/default_* context; cannot forge hold cleared; driver cannot verify own evidence; dispatcher cannot clear a hold; driver sees only own allocations; cross-company driver injection rejected; only a dispatcher can confirm.

## 3. Live browser verification (dispatcher session, 1440 px)

Real Chromium (Playwright), logged in as `ff_ops_dispatcher`:
- FleetFlow Ops app loads (Today / Assignments / Vehicles / Drivers / Holds / Configuration). **Zero console errors.**
- Assignments list renders the demo allocations with State + Readiness columns.
- Allocation form: statusbar + Check readiness / Confirm / Check out / Return / Cancel.
- **"Check readiness" on scenario A returns a green "Ready" with per-check reasons** ("Vehicle active and authorised… Operating permit valid… insurance valid… uber/UberX approved and fresh") — an explained verdict, not an unexplained dot.

## 4. Three demo scenarios (running app, synthetic data)

Seeded by `python fleetflow/manage.py ops` (disposable-DB guard; refuses to clobber real users/data):
- **A — ready chauffeur shift** (`DEMO-OPS-1`, Aisha): all evidence verified, Uber/UberX approved → **Ready**, confirmable and checkoutable.
- **B — blocked** (`DEMO-OPS-2`, Bilal): insurance expired + no Careem approval → **Blocked / Needs review**; correcting the evidence (verified renewal) restores Ready (covered by `test_renewal_supersede_makes_ready_again`).
- **C — maintenance hold** (`DEMO-OPS-3`): an active dispatch-blocking safety hold → checkout blocked until the specific hold is cleared with a note (covered by `test_active_hold_blocks_checkout`, `test_clearing_one_hold_keeps_others`).

## 5. Foundation corrections shipped (O1.09)

- Dashboard drill-through uses **server-computed cutoffs** (`reference_time`/`released_since`); browser clock cannot change filter meaning. Regression test added.
- `seed_users`/`seed_demo`/`seed_ops` **refuse to clobber real users or reassign real orders**, only touch clearly-marked demo records, and refuse to seed where real data exists unless `FLEETFLOW_ALLOW_DEMO=1`.
- `IMPLEMENTATION_STATUS.md` updated to truthful executed evidence.

## 6. What was NOT done / explicitly deferred

- **Temporary operating authority (Takamul):** the doc-kind vocabulary exists, but the full application/approval/permit state model and its readiness check are **deferred** (OPS-5/OPS-3 boundary). The UI does not yet capture a reviewed temporary authorization. Readiness does not infer authority from shared ownership (there is no such inference).
- **Automated HTTP/browser tests:** UI verification was **manual** (Playwright screenshots), not committed automated tour tests. Mobile 390 px for the ops screens relies on standard responsive Odoo backend views and was not separately screenshot-verified this pass.
- **Odometer capture at checkout via the button** reads the in-form field; a dedicated wizard is not built.
- **Rental full lifecycle, TARS, payments, platform APIs, telematics** — out of OPS-1 by design (OPS-3/4).
- **Concurrency scope:** verified for competing *confirms* on a shared vehicle. Document-revocation-racing-checkout and reschedule/cancel races are covered logically (fresh readiness re-check under lock at checkout) but not each exhaustively as separate two-connection tests.
- **Version/core-migration decision** and all **HOST/TEN-01…06 tenant-isolation** gates remain open; **no real-customer hosting** in this increment.

## 7. Backlog status (O1.01–O1.10)

Legend: **Verified** = implemented + test/browser evidence · **Implemented** = built, lighter evidence · **Partial** · **Blocked**.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| O1.01 | Operator/vehicle/driver master records | **Verified** | fleet.vehicle extension + fleetflow.driver + operating.authorization; no duplicate vehicle model; `test_*` |
| O1.02 | Restricted versioned evidence | **Verified** | credential lifecycle; 8 evidence tests incl. no-self-approve, immutability, attachment restriction |
| O1.03 | Per-city/product channel enrolments | **Verified** | channel.enrolment; Uber≠Careem, suspended, stale tests |
| O1.04 | Bounded readiness profiles | **Verified** | operating.profile finite checks; no-policy→Needs review test |
| O1.05 | Whole-interval evaluation | **Verified** | local-day boundary; mid-interval expiry vs later renewal tests |
| O1.06 | Allocation + actual custody | **Verified** | 13 allocation tests + 1 two-connection concurrency test |
| O1.07 | Maintenance holds | **Verified** | independent holds; clear-one-keeps-others; order-cancel-keeps-hold |
| O1.08 | Today/assignment/compliance screens | **Verified (desktop)** | FleetFlow Ops app; readiness explainer; browser-verified 1440 px, 0 console errors. Mobile 390 px not separately captured. |
| O1.09 | Foundation regression fixes | **Verified** | server cutoffs + safe seeding + truthful docs; 15 maintenance tests retained |
| O1.10 | Evidence report | **This document** | commands, results, screenshots, gaps |
| (Takamul temporary authority) | Temporary operating authority model/workflow | **Deferred** | doc-kind exists; full model + readiness check deferred (see §6) |

## 8. How to run it

```
python fleetflow/manage.py init        # fresh DB, installs both addons, starts web
python fleetflow/manage.py ops         # seed the 3 synthetic scenarios + role users
# open http://localhost:8069  ->  FleetFlow Ops
# ff_ops_dispatcher / ff_ops_compliance / ff_ops_manager / ff_ops_driver  (pw: fleetflow)
python fleetflow/manage.py test        # 59 tests
```
