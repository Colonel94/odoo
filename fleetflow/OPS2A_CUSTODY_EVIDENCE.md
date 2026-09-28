# OPS-2A — Physical vehicle handover, custody and return integrity

A bounded product increment: physical custody is now represented by immutable,
attributable events, checkout obeys a real handover-timing policy and re-checks
readiness at the actual moment, and returned custody history cannot be rewritten.
Not production approval, not regulatory certification.

## Commits

| Item | Value |
|---|---|
| Starting commit | `736752af1b0187a2c9dfb35a4d8835cfb2671597` on `feat/fleetflow-ops1` |
| Final tested commit | this branch head after the change — SHA reported with the push |
| Draft PR | #2 `feat/fleetflow-ops1` → `feat/fleetflow-workflow-platform` (kept **DRAFT**) |
| Module version | **16.0.1.2.0 → 16.0.1.3.0** (schema addition + explicit migration) |
| Runtime | `odoo:16.0` image `16.0-20250909`, Python 3.9, PostgreSQL 15, Docker 29.6.2 |
| Core / host | Colonel94/odoo `16.0` unmodified; Windows 11 |

## Custody data model — `fleetflow.custody.event`

An immutable, attributable record of a PHYSICAL handover (not a reservation).
Fields: allocation, vehicle, driver, company, `event_type` (checkout/return),
authoritative `event_time`, `performed_by`, `odometer` (+ `odometer_unit` and
canonical `odometer_km`), structured `energy_kind`/`energy_level` (%) and free
`fuel_note`, structured `condition` code, `defect`, `notes`, provenance links
`hold_id`/`order_id`, correction link `corrects_id`/`correction_reason`, and legacy
provenance `is_legacy`/`legacy_source`.

- The factual fields are frozen after creation (`write` refuses them even under
  sudo); a mistake is fixed by `action_correct`, which records a NEW attributable
  event pointing at the original — history is never edited.
- There is no public create/write/unlink right (ACL grants read only); events are
  created only by the workflow (privileged) and deleted only by superuser
  (migration/teardown). Company isolation and driver-own record rules apply.
- The allocation keeps `checkout_event_id`/`return_event_id` mirrors and derived
  read-only `current_holder_id`/`is_out`/`is_overdue`/`distance_travelled_km`; the
  editable capture fields are frozen once their handover event exists, so they can
  never become a second, divergent source of truth.

## Handover-timing policy

Server time is authoritative. Checkout is allowed only within
`[planned_start − tolerance, planned_end)`, where `tolerance` is
`res.company.ff_checkout_early_tolerance_minutes` — a FleetFlow operational rule
(not legal), **defaulting to 0** (no early handover; checkout only from planned_start
until planned_end). Checkout after `planned_end` is refused (reschedule instead).
Readiness is re-evaluated over the ACTUAL window `[now, planned_end)` at checkout.

## Concurrency / locking design

Checkout and return acquire the existing shared vehicle/driver row-lock counter
(`bump_resource_locks`, Postgres first-updater-wins under REPEATABLE READ) before any
state change, in the established vehicle-then-driver id order, so competing handovers
serialise. Custody conflicts are computed over the ACTUAL custody horizon
`[now, planned_end)`: any active reservation whose planned window intersects it, plus
any unreturned physical custody, blocks — so an early checkout cannot seize a car a
current reservation still holds, and a late return blocks the next checkout. Exactly
one open custody per vehicle results; the loser aborts with a serialization failure
(clean retry then refused) or a business denial. Access is always checked before raw
SQL.

## Odometer / unit policy

Readings are validated finite, non-negative and non-decreasing. Comparison is done in
canonical kilometres (`odometer_km`; `MI_TO_KM = 1.609344`) against the vehicle's
latest trusted km (`fleet.vehicle.ff_last_odometer_km`, advanced monotonically by
each committed event), so `100 mi` is never compared with `100 km` and a return below
checkout is caught through the same floor. The reported value and unit are retained
for audit. Zero is a valid reading (validated, not treated as "unset").

## Migration behavior (16.0.1.3.0)

Reconstructs custody history for pre-OPS-2A allocations without inventing precision:
a legacy checkout event for every handed-out allocation and a legacy return event for
every returned one, at the recorded `custody_out_at`/`custody_in_at` times, with the
recorded odometer. The handover ACTOR was never captured before OPS-2A, so
`performed_by` is left empty and the event is marked `is_legacy` with an explicit
`legacy_source` — unknown data is flagged, never faked. The vehicle's trusted
odometer is seeded from the highest legacy reading in km. Allocation ids, states,
timestamps, mileage, defect flags, chatter and existing hold/work-order links are
untouched. Existing companies get the conservative default tolerance (0). Re-runnable
(skips allocations that already have events).

## H01–H20 completion matrix

| # | Scenario | Coverage | Status |
|---|---|---|---|
| H01 | Checkout+return → immutable paired events | `TestCustody.test_H01_checkout_return_produces_immutable_paired_events` | ✅ |
| H02 | Checkout before window refused | `test_H02_checkout_before_window_refused_default_zero_tolerance` (+ `test_H02b…tolerance_allowed`) | ✅ |
| H03 | Late checkout after planned_end refused | `test_H03_checkout_after_window_refused` | ✅ |
| H04 | Early checkout can't bypass a current reservation | `test_H04_early_checkout_cannot_bypass_current_reservation` | ✅ |
| H05 | Two simultaneous checkouts of one vehicle: one wins | `TestConcurrency.test_duplicate_checkout_only_one_wins` | ✅ |
| H06 | Late return keeps next driver blocked | `test_H06_late_return_blocks_next_driver` | ✅ |
| H07 | Next allocation proceeds after actual return | `test_H07_next_driver_proceeds_after_actual_return` | ✅ |
| H08 | Return defect → provenance-linked hold/order, next blocked | `test_H08_return_defect_creates_linked_hold_and_blocks_next` | ✅ |
| H09 | Odometer cannot decrease | `test_H09_odometer_cannot_decrease` | ✅ |
| H10 | Zero/NaN/inf/negative handled | `test_H10_zero_is_valid_reading`, `test_H10_nan_inf_negative_rejected` | ✅ |
| H11 | km/mi conversion deterministic | `test_H11_unit_conversion_is_km_canonical` | ✅ |
| H12 | Direct writes can't forge timestamps/actors | `test_H12_cannot_forge_custody_facts` | ✅ |
| H13 | Returned history can't be edited/deleted | `test_H13_returned_history_is_immutable` | ✅ |
| H14 | Cross-company custody access denied | `test_H14_cross_company_custody_denied` | ✅ |
| H15 | Checkout re-evaluates readiness at handover | `test_H15_checkout_reevaluates_readiness` | ✅ |
| H16 | Credential/channel suspension race vs checkout | `TestConcurrency.test_checkout_and_channel_suspension_serialise`, `…evidence_revocation_serialise` | ✅ |
| H17 | Hold creation race vs checkout | `TestConcurrency.test_checkout_and_hold_creation_serialise` | ✅ |
| H18 | Actual return, not planned_end, releases custody | `test_H18_planned_end_never_auto_closes_custody` | ✅ |
| H19 | Authenticated RPC full workflow | `TestHttpBoundary.test_B21_custody_workflow_over_rpc` | ✅ |
| H20 | Legitimate cancel/reschedule before checkout | `test_H20_cancel_and_reschedule_before_checkout` | ✅ |

Plus `test_correction_creates_new_event_leaves_original` for the attributable
correction mechanism.

## Commands and final result totals (isolated containers, `down -v`)

```
python fleetflow/check_static.py     -> PASS (fleetflow_operations 41 py / 12 xml / 44 ACL)
python fleetflow/manage.py test      -> 229 tests, 0 failed, 0 error
python fleetflow/manage.py test-http -> 21 tests,  0 failed, 0 error (B01–B21)
python fleetflow/manage.py test-update -> 214 tests, 0 failed, 0 error
```

Genuine old→new custody migration drill (`fleetflow/migrate_drill/c2_seed.py`,
`c2_assert.py`, `BASELINE=736752af`): `C2_SEED_OK` → `module fleetflow_operations:
Running migration [16.0.1.3.0>] post-migrate` → `C2_ASSERT_OK`. Counts are the final
`odoo.tests.result` totals.

## Reproduced pre-fix problems

- Reviewed `action_checkout` refused checkout only when `now >= planned_end`, so a
  vehicle planned for tomorrow could be physically checked out today (no early-window
  policy). The corrected policy refuses early checkout beyond the configured
  tolerance; the previously-passing checkout tests were updated to check out inside
  the handover window (fixtures only — assertions unchanged).
- Checkout conflicts were computed over the PLANNED window, so an early checkout
  could seize a car another current reservation still held (H04) — now computed over
  the actual `[now, planned_end)` custody horizon.
- Custody odometer/return fields on `fleetflow.allocation` were plain inputs an
  ordinary user could rewrite after the fact (post-return history editing) — now
  frozen mirrors of immutable events.

## UI

The allocation form now shows, per state, planned driver/vehicle/interval, current
readiness, current custody status ("Currently with … since …"), an Overdue ribbon
when `planned_end` has passed with custody still open, the checkout/return capture
groups, distance travelled, and a read-only immutable custody-event history. A
read-only "Custody history" list/menu is added. No application redesign; no Today
dashboard.

## Authorization

Checkout/return/reschedule/cancel remain dispatcher-controlled; custody correction
requires a fleet manager; custody events are read-only to dispatcher/compliance/fleet
(driver sees only their own). No driver self-checkout was introduced (not an existing
approved requirement). Cross-company users cannot see or manipulate another company's
custody events.

## CI status

Local isolated Docker runs only (totals above). Repository CI is **pending** until it
runs on the pushed head; old CI is not treated as proof of this code.

## Remaining limitations / out of scope

- "Late-return" migration history is time-dependent; the drill represents it via the
  currently-checked-out (overdue-capable) case, whose recorded times migrate
  identically. The `is_overdue` TRUE branch is a time-based UI compute (asserted
  False on a fresh checkout; the auto-close guarantee is asserted directly).
- Physical RENTAL checkout remains disabled (needs renter/contract controls).
- The parser's independent execution/resource isolation remains an explicit
  pre-customer-upload requirement, unchanged and untouched here.
- Not started (deferred, as instructed): Today dashboard, live compliance alerts,
  billing, Uber/Careem integrations, rental-contract lifecycle, tenant provisioning,
  general UI redesign. Commercial requirements (owner-hosted subscriptions; isolated
  per-customer runtime/DB/filestore/secrets; branding; private backup/restore; shared
  provisioning) remain unchanged.
