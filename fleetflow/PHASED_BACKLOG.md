# FleetFlow — Revised Phased Backlog (gap-driven)

**Date:** 21 September 2026. Derived from `fleetflow-phased-delivery-plan-v2.md` and the verified current state (`NEXT_REVIEW.md`, `TENANT_REQUIREMENTS_MATRIX.md`).

Status legend: ✅ done · 🟡 partial · ⛔ not started · 🔒 launch-gate (blocks real hosting).
Progress is evidence-gated, not date-gated. A phase ends only at its exit gate.

---

## Phase 0 — Recover and verify + hosted architecture
Exit gate: reproducible source; blockers documented; runtime & hosting architecture reviewed.

| WP | Item | Status | Note |
|---|---|---|---|
| P0.1 | Safely apply source | ✅ | Extracted; full Odoo checkout assembled; core untouched |
| P0.2 | Validate dev setup / which Odoo runs | ✅ | Confirmed image core runs (not old checkout); deploy fix documented |
| P0.3 | Baseline tests | ✅ | check_static PASS; 14/14 integration tests pass |
| P0.4 | Version decision (maintained baseline) | 🟡 | **Needs Omar's sign-off.** De facto runs on maintained `odoo:16.0` image; addon is version-agnostic in 16.0 |
| P0.5 | Hosted-customer architecture review | ✅ | `ADR-HOSTED-TENANCY.md` + `TENANT_REQUIREMENTS_MATRIX.md` produced |
| — | Commit verified addon + baseline report | ⛔ | D5: still uncommitted; no branch/PR |

## Phase 1 — Maintained foundation + two isolated local tenants
Exit gate: lifecycle passes; **tenant credentials/mounts do not cross boundaries.**

| WP | Item | Status | Note |
|---|---|---|---|
| P1.1 | Port/fix compatibility | ✅ | Runs on maintained image; deploy-layer fix only |
| P1.2 | Lifecycle (fresh DB, install, restart, update) | 🟡 | init/install/restart verified; module **update** path not yet tested |
| P1.3 | Continuous verification / regressions | 🟡 | 14 tests pass; **concurrency regression (D3) missing** |
| P1.4 | Live frontend verification | ✅ | Workspace + role views verified in browser, 0 console errors |
| **P1.5** | **Two isolated local tenant fixtures + trusted host routing** | ⛔ | **Next implementation — see `NEXT_IMPLEMENTATION_PROMPT.md`** (TEN-01) |

## Phase 2 — Real UI/UX + branding
Exit gate: real tasks succeed; each hostname shows only its own identity.

| WP | Item | Status |
|---|---|---|
| P2.1–P2.5 | Role screens, consistent workspace, guided flows, responsive/a11y, data-connected cards | 🟡 (workspace strong; a11y/keyboard + full form-flow polish outstanding) |
| P2.6 | Customer branding (login/workspace/reports/email), host-resolved | ⛔ (TEN-02) |

## Phase 3 — Workshop operations
| WP | Item | Status |
|---|---|---|
| P3.1 Dispatch/conflicts · P3.2 Maintenance holds · P3.3 Evidence/history · P3.4 Scope/rework · P3.5 Inspection policy | ⛔/🟡 | Base rework + immutable history ✅; conflicts/holds/attachment validation/inspection-per-type ⛔ |
| P3.6 | Security & **concurrency** (competing transitions, direct RPC) | 🟡 | RPC/forged-write ✅ tested; **multi-connection race ⛔ (D3)** |

## Phase 4 — Repeatable/configurable workflows
All ⛔ (templates, target-time, preventive generation, automation observability). Guardrail: no arbitrary code eval; idempotent scheduling.

## Phase 5 — Cost & performance visibility
All ⛔ (structured costs, KPI dictionary, verifiable reports, optional stock/purchase). Cost fields exist on the model; reporting/KPI definitions ⛔.

## Phase 6 — Harden & controlled pilot 🔒
| WP | Item | Status |
|---|---|---|
| P6.1 Recovery rehearsal · P6.2 Deploy safeguards · P6.3 Performance · P6.4 Monitor/operate · P6.5 Acceptance | ⛔ |
| **P6.6 Enforce hosted launch gates (TEN-06)** | 🔒 ⛔ | **Blocks all real-customer hosting incl. manual pilot** |

## Phase 7 — Owner-hosted subscription onboarding
| WP | Item | Status |
|---|---|---|
| P7.1 One provisioning workflow · P7.2 Self-service signup · P7.3 Owner-assisted customization · P7.4 Subscription lifecycle · P7.5 Safe demo · P7.6 Release packaging | ⛔ (TEN-04) | Payment integration explicitly deferred/missing |

---

## Critical path to a hosted pilot

```
P0.4 version sign-off  +  commit addon
        │
        ▼
P1.5 two isolated local tenants + host routing  (TEN-01)      ← NEXT
        │
        ▼
P2.6 branding (TEN-02)  +  P3.6 concurrency (D3)
        │
        ▼
P6.6 TEN-06 two-tenant negative tests + P6.1 recovery   🔒 launch gate
        │
        ▼
P7.3 owner-assisted manual pilot  →  P7.1/P7.2 automatic signup + billing
```

**Pull-forward rule:** the TEN-06 isolation, TEN-02 branding, access and TEN-05 recovery gates must pass **before any live customer**, even a manually onboarded one. Automatic signup and billing may follow the manual pilot.
