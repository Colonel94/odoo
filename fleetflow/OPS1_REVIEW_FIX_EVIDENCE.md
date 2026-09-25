# OPS-1 — Dispatch-integrity correction evidence (review F01–F09)

**Date:** 23 September 2026; concurrency-regression follow-up 25 September 2026.
**Reviewed commit:** `c3e74670` on `feat/fleetflow-ops1` (baseline `59bfb037`).
**Correction commits:** `77ca3a24` → `9e2e96fd` (six increments, below), plus a
follow-up increment adding dedicated two-connection tests for the remaining F07
race pairs (see §1 and §2, F07).
**Scope:** the bounded dispatch-integrity correction requested by the independent
review. This document **replaces** the unqualified "Verified"/"logically covered"
claims in `OPS1_IMPLEMENTATION_EVIDENCE.md` with criterion-level status. It does
**not** claim OPS-1 is complete: UI/"Today" workflow, temporary-authority capture,
custody enhancements beyond F09, mobile acceptance, the standing exception process,
authenticated HTTP privacy regressions, and all HOST/TEN work remain outstanding.

Status legend: **Fixed-and-tested** (code + automated test) · **Implemented-unverified**
(built, not exercised by an automated test) · **Open** (not delivered here).

---

## 1. Environment and commands (reproducible)

| Item | Value |
|---|---|
| Runtime | `odoo:16.0` image (`16.0-20250909`) + PostgreSQL 15, isolated `fleetflow-test` compose project (`down -v` teardown) |
| Core baseline | Colonel94/odoo `16.0` at `7d63cda1` — unmodified |
| Command (structural) | `python fleetflow/check_static.py` |
| Command (tests) | `python fleetflow/manage.py test` → installs `fleetflow_operations`, runs `--test-enable --test-tags /fleetflow,/fleetflow_operations --stop-after-init --no-http` |
| Host | Windows 11, Docker 29.6.2 |

**Test totals (full suite, both addons):**
- Reviewed commit `c3e74670`: **59** tests (15 maintenance + 44 operations), 0 failed.
- After the six-increment correction (`9e2e96fd`): **106** tests, **0 failed, 0 error**.
- After the concurrency-regression follow-up: **111** tests, **0 failed, 0 error** —
  re-run in full on 25 September 2026 via `python fleetflow/manage.py test`
  (isolated `fleetflow-test` compose project, `down -v` teardown, exit 0);
  `python fleetflow/check_static.py` PASS (fleetflow 5 py/4 xml/9 ACL;
  fleetflow_operations 26 py/11 xml/40 ACL).
- Net new automated tests: **47** operations tests in the six increments
  (reproduction-first for F01–F06; regression for F07–F09), plus **5** dedicated
  two-connection race tests in the follow-up. All 15 maintenance tests retained
  and passing.

**Not executed here (explicitly):** authenticated HTTP/JSON-RPC and browser download/export requests (harness runs `--no-http`); mobile (390 px) rendering; upgrade/restart drills; the multi-tenant HOST/TEN gates.

---

## 2. Finding-by-finding status

| # | Finding | Status | Evidence (test file · commit) |
|---|---|---|---|
| **F01** | Context flags / draft-reset bypass workflow guards | **Fixed-and-tested** | `test_lifecycle.py` (ff_alloc/credential/hold_action no longer bypass; draft-reset can't smuggle custody; confirmed/checked-out cannot reset to draft) · `77ca3a24` |
| **F02** | Post-confirmation plan edits evade conflict/readiness | **Fixed-and-tested** | Server planning-lock + deletion guard `test_lifecycle.py`; guarded `action_reschedule` re-checks on prospective values `test_amendment_checkout.py` · `77ca3a24`, `546d8671` |
| **F03** | Eligibility passes for wrong subject/city; multi-product | **Fixed-and-tested** | `test_eligibility.py` (both subjects required, city match, suspension no-mask, recheck date, per-product independence, order-independence) · `6794c9c9` |
| **F04** | Approval/verified/published state forgeable | **Fixed-and-tested** | `test_lifecycle.py` (channel approve reviewer-gated + no direct approved; authorization verified action-only; published profile frozen; vehicle review-state action-only; staged supersession) · `77ca3a24` |
| **F05** | Missing age/validity produces green | **Fixed-and-tested** | `test_false_green.py` (unknown end-of-use → Needs review; blank/imprecise expiry → Needs review; unbounded/wrong-jurisdiction permit; operator-tz deterministic) · `a8b8787f` |
| **F06** | Checkout validates old plan, not actual handover | **Fixed-and-tested** | `test_amendment_checkout.py` (server-time window; evaluate `[now, planned_end]`; warning acknowledgement; rental physical checkout disabled) · `546d8671` |
| **F07** | Locking misses holds/evidence/channel changes | **Partial** — lock protocol + all named race pairs Fixed-and-tested; standing exception process + company-scope lock Open | `constants.bump_resource_locks` in hold/credential/channel mutations; `test_concurrency.py` — seven dedicated two-connection races: reservation/reservation, checkout/hold, checkout/channel-suspension, checkout/evidence-revocation, checkout/cancel, duplicate-checkout, reschedule/reservation (each asserts both workers finish, one wins, loser fails with a Postgres serialization failure, no partial state) · `0f06cf8c` + follow-up |
| **F08** | Private-file protection depends on unenforced metadata | **Partial** — binding + field access Fixed-and-tested; HTTP Open | `test_privacy_custody.py` (attachment bound+privatised on link; foreign/public attachment rebound; sensitive fields role-gated) · `9e2e96fd` |
| **F09** | Custody evidence + maintenance linkage incomplete | **Partial** — odometer + defect-chain Fixed-and-tested; rest Open | `test_privacy_custody.py` (finite/zero/last-accepted odometer; allocation→order→hold chain) · `9e2e96fd` |

### Remaining Open items within the findings (tracked, not delivered)

- **F03:** subject requirement uses a mode heuristic (chauffeur ⇒ vehicle+driver; rental ⇒ vehicle); a *channel-specific published profile* and *backing evidence* are not yet mandatory for coverage (the generic mode profile still supplies mode-level checks). **Implemented-unverified/Open.**
- **F04:** authorization verification is forge-proof and reviewer-gated but does **not** yet mandate a linked verified evidence document; a vehicle's review state forged at **create** time (vs. write) is not guarded (the field default `unreviewed` covers migration). **Open.**
- **F05:** insurance *use-scope* is not modelled as an evaluated field; category-evidence interval binding is not tightened. **Open.**
- **F06:** the checkout window enforces the *upper* bound (no handover after `planned_end`) and re-evaluates at server time; a configurable *early-grace* window is not added (server-time re-evaluation already prevents reliance on not-yet-effective evidence). **Implemented-unverified.**
- **F07:** all seven race pairs the review named now have dedicated two-connection tests (reservation/reservation, checkout/hold, checkout/channel-suspension, checkout/evidence-revocation, checkout/cancel, duplicate-checkout, reschedule/reservation). Still **Open**: the **standing exception process** that re-flags active/future allocations after an invalidation committed *after* handover (the review's "Live readiness / expiry exceptions" — the RPC-retry-then-re-block and deduplicated active exception is not yet a delivered feature; the current guarantee is that the loser fails cleanly and no double-commit survives), and a **company-scope lock** for company-wide invalidations (authorization/profile changes do not yet bump a shared company-level counter).
- **F08:** authenticated **HTTP** download/export/chatter regressions and public-token handling are **not run** (harness `--no-http`); privacy is proven at the ORM/model level only. **HTTP privacy: UNVERIFIED.**
- **F09:** cross-unit (km/mi) odometer normalisation (only same-unit reconciled), writing back the vehicle's odometer history, and minimum handover/return evidence capture are **Open.**

---

## 3. Claims retracted from the previous evidence report

The following `OPS1_IMPLEMENTATION_EVIDENCE.md` statements were **overclaims** and are corrected here:

- The **"fully eligible" fixture** approved only the driver on Uber; it silently omitted vehicle platform approval (root cause of the F03 false positive). Now corrected to approve **both** subjects; the new assertions were not relaxed to fit it.
- **"O1.06 — Allocation + custody … Verified"** and the concurrency claim that other races were "logically covered": only competing-confirmation was demonstrated at review time. The lock protocol is now extended and a second race is demonstrated, but the exception process and several race pairs remain Open (§2).
- Blanket **"Verified"** on O1.02/O1.03/O1.05 did not reflect the bypasses (F01/F04), the driver-only channel gap (F03) or the false-green paths (F05). Criterion-level status is in §4.
- Structural counts now reconcile with CI: **26 operations Python files, 11 XML files, 40 ACL entries** (`check_static.py`).

---

## 4. Acceptance requirements (O1.01–O1.10) — corrected status

| ID | Requirement | Corrected status |
|---|---|---|
| O1.01 | Master records | Fixed-and-tested (unchanged; no regressions). |
| O1.02 | Restricted versioned evidence | Fixed-and-tested: no self-approve, staged supersession keeps coverage, attachment binding enforced. HTTP file paths UNVERIFIED (F08). |
| O1.03 | Per-city/product channel enrolments | Fixed-and-tested for subject/city/suspension/freshness/per-product (F03); channel-specific-profile requirement Open. |
| O1.04 | Bounded readiness profiles | Fixed-and-tested: published versions frozen; unknowns fail closed. |
| O1.05 | Whole-interval evaluation | Fixed-and-tested: mid-interval expiry blocks; blank/imprecise validity → Needs review; deterministic operator tz (F05). |
| O1.06 | Allocation + actual custody | Fixed-and-tested for lifecycle/lock/amendment/checkout-window; standing exception process Open (F07); custody enhancements partial (F09). |
| O1.07 | Maintenance holds | Fixed-and-tested: independent clear; holds join the lock protocol; defect chain linked. |
| O1.08 | Today/assignment/compliance screens | **Open / not re-verified.** No mobile capture; the genuine interval-based "Today" resource overview is not delivered. |
| O1.09 | Foundation regression fixes | Fixed-and-tested: seeds use the review actions; 15 maintenance tests retained. |
| O1.10 | Evidence report | This document. |

---

## 5. Reproduce

```bash
git checkout feat/fleetflow-ops1            # correction increments 77ca3a24..HEAD
python fleetflow/check_static.py            # structural checks (PASS both addons)
python fleetflow/manage.py test             # 111 tests, 0 failed, 0 error (isolated containers)
```

The correction branch `feat/fleetflow-ops1` is **pushed to `origin`
(`Colonel94/odoo`) for review only** — it is **not merged**, not deployed, and
targets no auto-deploy. No paid infrastructure, real customer identity or Odoo
major-version change was performed. Local synthetic seeding (`manage.py demo` /
`ops`) was updated to use the review actions and remains synthetic-only.
