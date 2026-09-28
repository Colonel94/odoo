# OPS-2A — Accurate handover capture and operationally effective corrections

A bounded correction on top of the custody framework: what the dispatcher enters,
what the immutable history records, and what FleetFlow uses to permit the next
handover now agree; custody corrections are validated and operationally effective;
and safety-coded conditions control dispatch consistently. Not production approval,
not regulatory certification.

## Commits

| Item | Value |
|---|---|
| Starting commit | `4ed1fa8ca6fd795cc95088f26d5427e7112b5224` on `feat/fleetflow-ops1` |
| Final tested commit | this branch head after the change — SHA reported with the push |
| Draft PR | #2 `feat/fleetflow-ops1` → `feat/fleetflow-workflow-platform` (kept **DRAFT**) |
| Module version | **16.0.1.3.0 → 16.0.1.4.0** (additive schema + explicit migration) |
| Runtime | `odoo:16.0` image `16.0-20250909`, Python 3.9, PostgreSQL 15, Docker 29.6.2 |
| Core / host | Colonel94/odoo `16.0` unmodified; Windows 11 |

## Reproduced defects vs preventive improvements

**A — form inputs ignored (reproduced defect).** `action_checkout` resolved the
odometer from the form but passed the raw optional condition/energy/notes arguments
(None on the button path) into `_create_custody_event`, which then applied defaults.
The immutable event and the allocation mirror could disagree. Also a single
allocation `odometer_unit` was the authority for BOTH handovers, so a return in km
relabelled a checkout recorded in miles.

**B — corrections not validated or effective (reproduced defect).** `action_correct`
appended a `corrects_id`-linked record, but operational consumers (trusted mileage,
distance, displays) kept using the original; the correction path applied none of the
handover odometer checks and enforced no correctable-field allowlist.

**C — safety findings did not control dispatch consistently (reproduced defect).**
`action_return` raised a blocking hold only when `defect` was true; a safety-coded
structured condition raised nothing, and `action_correct` could add defect
information without any follow-up.

## Input-resolution rule

Each supported input is resolved ONCE — explicit action argument when supplied, else
the saved form value — and the immutable event AND the allocation mirrors are built
from the SAME resolved payload. Explicit zero is preserved; energy is "recorded" only
when a kind is set, so a measured 0% stays distinct from "not recorded". Free-text
`checkout_notes` / return condition are preserved. Checkout and return each carry
their OWN reported unit (`odometer_unit` for checkout, new `return_odometer_unit` for
return); canonical km drives comparisons and distance. Return capture kept its
already-correct fallback behaviour.

## Effective-correction rules

- Original events are immutable; a correction is a NEW attributable event
  (`corrects_id`, reason, corrector, recording time) that never changes who
  physically received/returned the vehicle or when.
- Corrections form ONE linear chain: `action_correct` always targets the current
  accepted tip (`_effective_tip`), never a superseded version — no competing branches.
- Operations use the effective tip consistently: trusted vehicle mileage
  (`_ff_recompute_trusted_odometer`), checkout/return comparison, distance travelled,
  and historical value/unit display.
- Shared measurement validation is reused: finite, numeric, non-negative, valid unit,
  canonical km, and chronological consistency with the surrounding accepted readings
  (a correction that would contradict a later accepted movement is refused with a
  "requires review" business error, never a silent rewrite or floor drop).
- A correctable-field allowlist (`odometer`, `odometer_unit`, `energy_kind`,
  `energy_level`, `condition`, `defect`, `notes`) rejects injecting allocation,
  vehicle, company, driver, actor, time, canonical value or legacy marker.
- Fleet-manager role + record access are checked before any privileged create/SQL.
- Corrections coordinate with checkout/return on the shared vehicle lock; a losing
  concurrent correction aborts (serialization) and retries against the new tip, and a
  checkout either sees the corrected floor or an incompatible correction is refused
  after the checkout commits.
- A correction never opens or closes physical custody or changes allocation state.

Worked example (checkout 100 km, return 200 km, no later movement, correct return to
250 km): original 200 km stays in history; effective return 250 km; effective distance
150 km; next checkout at 210 km refused; a non-decreasing reading ≥ 250 proceeds.

## Safety-condition policy (FleetFlow internal, not legal)

`constants.SAFETY_CONDITION_CODES = {tyre_issue, warning_light, body_damage}` require a
dispatch-blocking safety review; cosmetic codes (interior_issue, generic damage_noted,
clean/acceptable/other) do not, and classification is never guessed from free text.
- A return with a safety-coded condition raises the blocking hold + work order even
  when `defect=False`; the car is still recorded as physically returned, atomically
  with the follow-up (custody closes, hold active, next checkout blocked, provenance
  points to the exact return event).
- An explicit `defect=True` also triggers follow-up.
- A checkout with a safety-coded condition is refused (no rolled-back hold is claimed).
- A correction that ADDS a safety finding raises the follow-up (linked to the
  correction, deduplicated); a later correction back to `defect=False` never clears an
  existing hold — clearance stays with the authorised hold-clearance workflow.

## F01–F10 results (exact test names)

| # | Coverage | Status |
|---|---|---|
| F01 | `TestCustodyCorrections.test_F01_saved_form_values_flow_into_event` | ✅ |
| F02 | `test_F02_explicit_args_override_form`, `test_F02_measured_zero_vs_not_recorded` | ✅ |
| F03 | `test_F03_mixed_unit_history_display` | ✅ |
| F04 | `test_F04_valid_correction_is_effective` + RPC `TestHttpBoundary.test_B22_effective_correction_over_rpc` | ✅ |
| F05 | `test_F05_invalid_corrections_rejected`, `test_F05_correction_conflicting_with_later_reading_rejected` | ✅ |
| F06 | `test_F06_correction_does_not_change_custody` | ✅ |
| F07 | `test_F07_safety_coded_return_raises_hold_without_defect`, `test_F07_non_blocking_condition_raises_no_hold`, `test_F07_checkout_safety_condition_refused` | ✅ |
| F08 | `test_F08_correction_adds_safety_then_not_cleared` | ✅ |
| F09 | `TestConcurrency.test_concurrent_corrections_one_wins`, `test_correction_vs_checkout_serialise` | ✅ |
| F10 | `test_F10_authorization_and_company_isolation`, `test_F10_correction_field_allowlist` + RPC `TestHttpBoundary.test_B23_form_values_flow_into_checkout_over_rpc` | ✅ |

F01 uses the real save-then-button pattern (form fields written, then `action_checkout`
with no measurement arguments). A live browser render of the allocation form was run on
a disposable instance (login + screenshots) confirming the Checkout Notes field and
per-handover units (checkout `100.00mi`, return `200.00km`, distance `39.07 km`) with no
console errors.

## Commands and final result totals (isolated containers, `down -v`)

```
python fleetflow/check_static.py     -> PASS (fleetflow_operations 43 py / 12 xml / 44 ACL)
python fleetflow/manage.py test      -> 245 tests, 0 failed, 0 error
python fleetflow/manage.py test-http -> 23 tests,  0 failed, 0 error (B01–B23)
python fleetflow/manage.py test-update -> 230 tests, 0 failed, 0 error
```

Genuine old→new upgrade drill (`fleetflow/migrate_drill/c2_seed.py`, `c2_assert.py`,
`BASELINE=736752af` module 1.2.0 → new 1.4.0): `C2_SEED_OK` → `Running migration
[16.0.1.3.0>]` → `Running migration [16.0.1.4.0>]` → `C2_ASSERT_OK`, including the new
assertion that a miles return keeps its unit (`return_odometer_unit` backfilled from
the previously-shared `odometer_unit`, canonical km derived).

### Targeted failure against the reviewed behaviour (isolated worktree at `4ed1fa8c`)

Running the new `TestCustodyCorrections` class against the reviewed baseline (new tests
dropped into a `git worktree` at `4ed1fa8c`, disposable compose project) fails **7 and
errors 2 of 14** — F01/F03 (input resolution + units, A), F04/F05/F10-allowlist
(effective + validated corrections, B), F07-checkout/F07-safety-return/F08 (safety
policy, C). All pass on the fixed tree (counted in the 245 above).

## Migration

`migrations/16.0.1.4.0/post-migrate.py` backfills `return_odometer_unit` from the
previously-shared `odometer_unit` for allocations already returned (so a historical
miles return is not relabelled km), defaulting never-returned rows to km. No event id,
physical timestamp, actor, measurement, correction link or maintenance provenance is
altered; `checkout_notes` has no historical value to reconstruct and is left empty
(never fabricated).

## Remaining limitations

- A complex meter-replacement/reconciliation workflow is deliberately out of scope; a
  correction that contradicts a later accepted reading is surfaced for review, not
  auto-reconciled.
- The `is_overdue` TRUE branch remains a time-based UI compute; physical rental
  checkout remains disabled.
- The parser resource-isolation requirement stays open before untrusted customer
  uploads (unchanged, untouched here). Completed PDF/renewal work was not reopened.
- Not started (next, after review): live eligibility exceptions and the Today
  operations screen. Owner-hosted subscription, separate-customer environments,
  branding, customer-addon isolation, backup/restore and onboarding remain future
  delivery gates.

## CI status

Local isolated Docker runs only (totals above); repository CI is **pending** until it
runs on the pushed head. Historical green CI is not reused as proof of this code.
