# OPS-1 — Targeted closure: renewal-integrity R1 and R2

Two focused renewal-integrity corrections on top of the reviewed baseline
(`a1423adc` on `feat/fleetflow-ops1`). Bounded to R1 and R2. Not a milestone, not
production approval, not regulatory certification. The completed PDF semantic-value
correction and its tests are unchanged.

## Environment, commits, commands

| Item | Value |
|---|---|
| Reviewed baseline | `a1423adc` on `feat/fleetflow-ops1` (module 16.0.1.2.0); local head == `origin/feat/fleetflow-ops1` |
| Draft PR | #2 `feat/fleetflow-ops1` → `feat/fleetflow-workflow-platform` (kept **DRAFT**) |
| Tested commit | this branch head after the change — SHA reported with the push |
| Runtime | `odoo:16.0` image `16.0-20250909` (`sha256:0f36a5002a20…`), Python 3.9.2, PyPDF2 1.26.0, Pillow, PostgreSQL 15 |
| Core / host | Colonel94/odoo `16.0` unmodified; Windows 11, Docker 29.6.2 |
| No schema change | this correction adds no field/column and no migration script (read-time + approval-flow semantics only) |

```
python fleetflow/check_static.py
python fleetflow/manage.py test        # model + concurrency (-ff_http, --no-http)
python fleetflow/manage.py test-http   # authenticated HTTP/JSON-RPC (ff_http)
python fleetflow/manage.py test-update # disposable install -> -u smoke
# data-safety: genuine d0486a74 -> new drill (fleetflow/migrate_drill/c1_seed.py, c1_assert.py)
```

### Results (this session; `odoo.tests.result` totals, isolated containers, `down -v`)

| Suite | Total (result line) | Outcome |
|---|---|---|
| `check_static.py` | fleetflow 5 py/4 xml/9 ACL; fleetflow_operations 37 py/11 xml/40 ACL | **PASS** |
| `manage.py test` | **210 tests** (204 baseline + 6 new) | **0 failed, 0 error** |
| `manage.py test-http` | **20 tests** (B01–B20) | **0 failed, 0 error** |
| `manage.py test-update` | **195 tests** (189 baseline + 6 new) | **0 failed, 0 error** (no migration — no schema change) |
| c1 data-safety drill | `C1_SEED_OK` (old `d0486a74`) → `C1_ASSERT_OK` (new) | **PASS** |

Counts are the final `odoo.tests.result` totals, not summed per-module/per-setup stats.

### Targeted failure against the reviewed behaviour (isolated run)

Reverting only `credential.py` to the reviewed `a1423adc` and running the new
classes proves the tests catch the defects (5 failed of 25); with the fix restored
they pass (43 of 43 in the same targeted run).

| New test | Baseline (`a1423adc`) | With fix |
|---|---|---|
| `TestRenewalIdentity.test_revoked_predecessor_competing_approvals_only_one_wins` | FAIL (`superseded_by_id` not recorded; both siblings approvable) | PASS |
| `TestRenewalIdentity.test_revoked_predecessor_single_legitimate_renewal_still_approves` | FAIL (winner slot not recorded on a revoked predecessor) | PASS |
| `TestRenewalIdentity.test_inconsistent_successor_grants_no_coverage_from_either_side` | FAIL (`inconsistent successor must be unreliable`) | PASS |
| `TestConcurrency.test_revoked_predecessor_two_connection_race_one_winner` | FAIL (both approvals win) | PASS |
| `TestConcurrency.test_revoked_predecessor_serialization_then_clean_retry` | FAIL (no single surviving winner) | PASS |
| `TestRenewalIdentity.test_valid_same_identity_and_independent_controls_still_cover` | PASS (control — no spurious failure either way) | PASS |

## R1 — a winning successor is recorded even when the predecessor is already revoked

### Confirmed pre-fix behaviour (reviewed `credential.py` at `a1423adc`)

`action_verify` checked `predecessor.superseded_by_id` for a competing winner, but
assigned it **only inside `if predecessor.state == "verified":`**. A predecessor
revoked before either renewal was approved therefore never recorded its first
accepted successor, so a second sibling renewal could also be approved (two verified
successors of one predecessor).

### Fix

`action_verify` now, under a `FOR UPDATE` lock on every predecessor and **before any
verified state is written**:
- detects the competing-winner conflict on the actual `superseded_by_id` link (plus
  an in-batch guard), and refuses a losing sibling with a business `UserError` while
  leaving **no** partial change (no verified state, attribution, link or attachment
  mutation);
- records the winning `superseded_by_id` on the predecessor **whether or not it is
  still verified**. A still-verified predecessor is additionally moved to
  `superseded` with its effective cutover; a revoked predecessor keeps its `rejected`
  state and its verification+revocation attribution, grants no coverage, but durably
  records its one accepted successor.

Result: one unambiguous accepted successor even for a revoked predecessor; a
legitimate first renewal still approves for its own validity window; subsequent
sibling approvals fail; revoking the predecessor or the accepted successor neither
erases the winner nor reopens an alternative sibling; never-approved siblings never
consume the slot. `test_revoked_predecessor_before_future_successor_starts` intent
preserved (the lone legitimate renewal still approves).

### Reproduction / coverage (public actions, RPC, two connections)

- `TestRenewalIdentity.test_revoked_predecessor_competing_approvals_only_one_wins`
  — the full sequential public-action sequence (create+verify P → stage R1,R2 →
  revoke P → approve R1 → R2 refused), exactly-one-survivor, attribution preserved,
  revocation of either record does not reopen R2, independent credential unaffected.
- `TestRenewalIdentity.test_revoked_predecessor_single_legitimate_renewal_still_approves`.
- `TestConcurrency.test_revoked_predecessor_two_connection_race_one_winner` — barrier
  race; exactly one wins, the loser aborts (serialization) or is refused.
- `TestConcurrency.test_revoked_predecessor_serialization_then_clean_retry` — forced
  ordering that guarantees the serialization path, then a clean business refusal on
  retry in a fresh transaction; asserts one surviving successor and that the
  predecessor's revocation and source-byte hash survive, from a fresh transaction.
- `TestHttpBoundary.test_B19_revoked_predecessor_competing_renewals_over_rpc` —
  authenticated JSON-RPC, including the successful legitimate first approval.

## R2 — reject coverage from both sides of an inconsistent legacy identity link

### Confirmed pre-fix behaviour

`_cutover` already rejected the predecessor→successor direction on an identity
mismatch, but `_effective_interval` accepted a verified successor without checking
its own identity against `supersedes_id`. An inconsistent `Car A → Car B` chain
therefore still let the successor satisfy Car B's document check as a single record.

### Fix

`_effective_interval` now returns not-reliable when `supersedes_id` is set and the
record does not share its predecessor's full compliance identity (company, subject
type, exact subject, document kind) — detected **on the successor itself**, so the
record supplies no trusted coverage and surfaces as needs-review. Same-identity
renewals of a revoked predecessor (case B) and independent credentials (case C) are
unaffected. No stored identity, link, state, source file or attribution is rewritten.

### Coverage

- `TestRenewalIdentity.test_inconsistent_successor_grants_no_coverage_from_either_side`
  — the successor's own `_effective_interval`/`_validity`, alone in
  `_resolve_coverage`, alongside the predecessor in both record orders, and the
  actual readiness `_check_document` for the successor's subject, over an interval
  **inside** the successor's own validity window; asserts the affected reason is
  `needs_review`/`doc_validity_unknown` specifically.
- `TestRenewalIdentity.test_valid_same_identity_and_independent_controls_still_cover`
  — cases B and C controls.
- `TestHttpBoundary.test_B20_inconsistent_successor_needs_review_over_rpc` — the real
  readiness endpoint over authenticated RPC.
- `TestEffectiveCutover.test_inconsistent_legacy_chain_flagged_not_covered` (existing)
  — predecessor side, still green.

### Strengthened data-safety drill (`fleetflow/migrate_drill/c1_seed.py`, `c1_assert.py`)

Genuine `d0486a74` → new upgrade on a disposable DB. The seed now creates the
inconsistent redirected chain **and** two controls (a valid same-identity chain, an
independent credential), each with a real PDF source file. The assertion (corrected
wording, states exactly what it checks) confirms, under the new code:
- stored identities, replacement links, states, verification attribution and
  source-byte SHA-256 hashes are preserved for all three cases;
- the inconsistent chain grants no trusted coverage from **either** side — the
  predecessor and the redirected successor, alone and together in both record orders,
  and the readiness document check returns `needs_review`/`doc_validity_unknown` for
  **both** affected subjects, over an interval inside the successor's validity window;
- the valid chain still covers on both sides of its cutover and the independent
  credential is evaluated normally.

Observed: `C1_SEED_OK …` then `C1_ASSERT_OK …`.

## Preserved (no regression)

Pending-renewal identity write/verification guards; legitimate editable renewal
dates/issuer/reference and replacement uploads; PDF direct/indirect validation and
positive acceptance; approval-time attachment validation and source-lock race
protection; attachment privacy and immutable approved evidence;
verification/revocation attribution; allocation/maintenance/readiness and
company/role restrictions; existing interface and working databases. Full suites
green (210 / 20 / 195).

## CI status

Local isolated Docker runs only (results above). No CI run was triggered from this
session; treat repository CI as **pending** until it runs on the pushed head.

## Remaining limitations / out of scope

- The parser's independent execution/resource isolation remains an explicit
  pre-customer-upload requirement (PyPDF2 parse time is not sandboxed); **not** solved
  here and not part of this correction.
- Not bundled: handover/returns, live eligibility exceptions, Today/mobile, billing,
  integrations, tenant provisioning. The next separately reviewed increment remains
  vehicle handover and return integrity.
