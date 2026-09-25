# OPS-1 — Evidence lifecycle & approval-ownership closure (E01–E07)

**Increment:** approved claims retain their identity/evidence; future renewals
preserve legitimate current coverage; rejecting evidence never re-opens its
approved source. Bounded to E01–E07; does NOT complete the later handover/custody,
live-exceptions, Today/mobile, or any HOST/TEN hosting gate, and does not certify
RTA compliance or authorize use with paying customers.

## 1. Environment, commits, exact commands

| Item | Value |
|---|---|
| Starting commit | `453adc5d` on `feat/fleetflow-ops1` (previous reviewed head) |
| Final commit | see the pushed SHA in the PR / report (this branch head after group 3) |
| Runtime | `odoo:16.0` image (`16.0-20250909`) + PostgreSQL 15, isolated compose projects (`fleetflow-test`, `fleetflow-http-test`, `fleetflow-update-test`), `down -v` teardown |
| Core baseline | Colonel94/odoo `16.0` at `7d63cda1` — unmodified |
| Host | Windows 11, Docker 29.6.2 |
| Structural | `python fleetflow/check_static.py` |
| Model + concurrency | `python fleetflow/manage.py test` (`--test-tags /fleetflow,/fleetflow_operations,-ff_http --no-http`) |
| Authenticated HTTP | `python fleetflow/manage.py test-http` (`--test-tags ff_http`, HTTP server ON) |
| Module-update drill | `python fleetflow/manage.py test-update` (install → `-u` upgrade, runs migration + model suite on the upgraded module) |

**Results (each in full, isolated containers, clean teardown, this session):**

| Suite | Result |
|---|---|
| Model + concurrency (`test`) | **154 tests, 0 failed, 0 error** |
| Authenticated HTTP (`test-http`, `ff_http`) | **15 tests (B01–B15), 0 failed, 0 error** |
| Module-update drill (`test-update`) | install + `-u` upgrade clean; **139 model tests, 0 failed, 0 error** on the upgraded module |
| Structural (`check_static.py`) | PASS (fleetflow 5 py/4 xml/9 ACL; fleetflow_operations 31 py/11 xml/40 ACL) |
| Concurrency | the 9 two-connection races run inside the model suite; still green |

Reported **separately**; no single count stands in for all three. `test-http` runs a
real Odoo HttpCase HTTP server (not ORM-only or mocked auth); denials are asserted
by **business** exception type (AccessError/UserError/ValidationError), so an
unrelated programming error or HTTP 500 fails the test.

## 2. Reproduced pre-fix failures (measured)

The E01/E02/E05 logic (`credential.action_verify`, `_validity`, `action_reject`,
`ir_attachment._ff_is_frozen_source`) was reverted to the `453adc5d` behaviour with
the new tests kept, and `manage.py test` re-run. **4 tests failed** and pass with
the fix:

- `TestEvidenceLifecycle.test_future_effective_renewal_preserves_current_and_supplies_future` (E01)
- `TestEvidenceLifecycle.test_reject_records_revocation_without_overwriting_verification` (E02)
- `TestEvidenceLifecycle.test_rejected_source_file_stays_immutable` (E02)
- `TestEvidenceLifecycle.test_file_changed_after_link_is_revalidated_at_verify` (E05)

New coverage that is correct on both sides (deterministic, not a reproduced defect):
`test_real_gap_between_predecessor_and_renewal_is_not_ready` and
`test_revoked_predecessor_coverage_not_resurrected` (both fail-closed pre- and
post-fix). The E03/E04 guards (default_state create leak, authorization
company/evidence freeze, profile provenance freeze, reviewed-record deletion) are
new controls absent at `453adc5d`; they are verified passing with the fix and
covered by `TestBoundaryAuthority`/`TestDocumentOwnership` + HTTP B14/B15.

## 3. Acceptance gates E01–E07

| Gate | Status | Evidence (tests) |
|---|---|---|
| **E01** real linked future renewal preserves current coverage; boundaries/gaps/revocation/competing revisions deterministic | **Fixed-and-tested** | model `TestEvidenceLifecycle.test_future_effective_renewal_*`, `_real_gap_*`, `_revoked_predecessor_*`; HTTP `test_B05_future_effective_linked_renewal_preserves_coverage` (real `action_supersede`, readiness before/after) |
| **E02** rejection/revocation never unlocks a once-approved source or overwrites original verification attribution | **Fixed-and-tested** | model `test_reject_records_revocation_*`, `test_rejected_source_file_stays_immutable`; HTTP `test_B11_revoked_source_stays_immutable_over_rpc` |
| **E03** reviewed ownership/evidence/provenance/history cannot be transferred or deleted by ordinary writer access | **Fixed-and-tested** | model `test_verified_authorization_company_and_scope_frozen`, `test_published_profile_company_and_provenance_frozen`, `test_reviewed_records_cannot_be_deleted_by_reviewer`, `test_two_company_reviewer_cannot_transfer_an_approval`; HTTP `test_B14_two_company_reviewer_cannot_transfer_approval` |
| **E04** create/default/copy/related paths cannot manufacture reviewed state/attribution; legitimate draft editing works | **Fixed-and-tested** | model `test_channel_default_state_context_cannot_forge_approval`, `test_copy_of_approved_enrolment_starts_pending`, prior create-forge tests; HTTP `test_B15_default_state_context_cannot_forge_approval`, `test_B03_*` |
| **E05** changes after upload cannot evade validation at verification | **Fixed-and-tested** | model `test_file_changed_after_link_is_revalidated_at_verify`; HTTP `test_B12_file_changed_after_link_fails_verification` |
| **E06** role/route matrix + real valid-token lifecycle pass precise negative & positive tests | **Fixed-and-tested** | HTTP `test_B08_binary_download_is_role_and_company_scoped`, `test_B09_public_and_token_variants_are_forbidden`, `test_B13_pre_binding_token_is_voided_by_binding`, `test_B10_allowed_actions_still_work` |
| **E07** both addons, HTTP, concurrency and a disposable existing-data module update pass without damaging history/unrelated behaviour | **Fixed-and-tested** | `test` 154/0/0, `test-http` 15/0/0, `test-update` install+`-u` clean (139/0/0), `check_static` PASS |

## 4. What changed (mechanism)

- **Effective-dated coverage (E01):** `_validity` counts a `verified` OR `superseded`
  (non-revoked) record by its own effective interval; `action_verify` records only
  the supersession relationship (`superseded_by_id` + `replaced_on`) rather than
  wall-clock-dropping the predecessor. A future renewal thus covers only its window
  and today stays covered; a real gap yields not-Ready; revoked/rejected records
  never provide coverage. `action_supersede` returns a serializable id.
- **Durable source immutability + separate revocation (E02):** new `ever_verified`
  marker (set at first verify, never cleared) keys the `ir.attachment` freeze, so a
  once-approved file stays immutable through rejection/supersession/expiry/archival;
  `action_reject` records `revoked_by/on/reason` and no longer overwrites
  `verified_by/on`.
- **Re-validate at verify (E05):** `action_verify` re-checks the current file bytes
  under a row lock, so a post-link change or concurrent mutation cannot yield
  verified evidence on unvalidated bytes.
- **Identity/history freeze + deletion guards (E03/E04):** authorization
  `company_id`/`evidence_id`, profile `company_id`/`source_ref`/`source_version`
  frozen once reviewed; reviewed authorizations/profiles/enrolments/credentials
  cannot be deleted (only unused drafts); channel-enrolment create always forces
  `pending` with no attribution (defeats `default_state`/copy forging); linked
  evidence is scope/company-validated.
- **File policy (E04/E06):** PDFs structurally checked and rejected for malformed or
  active/embedded content; images parsed (header) with a bounded pixel budget;
  size/empty enforced — judged on real bytes. Binding voids any pre-existing access
  token and privatises; a protected source cannot regain a token via generic routes.

## 5. Migration / update behaviour

New field `ever_verified` (+ `revoked_by/on/reason`, `replaced_on`). A
`post_init_hook` (fresh install) and a `migrations/16.0.1.1.0/post-migrate.py`
(upgrade) backfill `ever_verified` **only** from unambiguous recorded state
(`verified`/`superseded`); `rejected` rows are left `False` (older code also stamped
a verification timestamp on plain rejections, so that column is ambiguous there) and
would surface for review rather than have a prior verification fabricated. No
document is deleted or altered. The `test-update` drill runs install then `-u`
upgrade in a disposable DB and passes the model suite on the upgraded module; the
normal development database and volumes are never used as fixtures.

## 6. Transient login HTTP 500 (cold asset generation) — investigation

**Not reproduced** in this session. The authenticated `test-http` run logged no
error/500 (`grep " ERROR | 500 |Internal Server Error"` → none). The
`assetsbundle: Failed to find attachment for assets …min.js` lines are normal
INFO-level cold-cache pregeneration, not errors. The suite authenticates via
JSON-RPC session and exercises `/web/dataset/call_kw` and `/web/content`, which do
not compile the full backend JS bundle the interactive login page does, so the
cold-asset path that produced the earlier transient 500 is not on these routes. No
errors were suppressed and Odoo core was not modified. **Status: unreproduced here;
remains a separate open item** tied to first interactive login on a cold cache.

## 7. Corrections to earlier evidence

- **B05** previously created an *unrelated* document starting today. It is replaced
  by `test_B05_future_effective_linked_renewal_preserves_coverage`, which drives the
  actual `action_supersede` linked renewal with a future effective start and asserts
  readiness before and after the start.
- **B08/B09** claims are narrowed: B08 asserts dispatcher/driver/other-company
  sessions do not receive the bytes AND the owning-company reviewer does, plus that
  metadata stays readable; B09 keeps unauthenticated and guessed-token denials, and
  **B13** adds the real pre-binding-token lifecycle (a genuine token issued before
  binding is voided by binding). Denials now require a business exception type, so a
  500/programming error no longer counts as a pass.
- `OPS1_BOUNDARY_CLOSURE_EVIDENCE.md` and `OPS1_REVIEW_FIX_EVIDENCE.md` remain;
  their historical results are retained.

## 8. Remaining — NOT delivered or waived

Actual handover interval/conflicts and immutable custody/decision events; complete
evidence-bound readiness and live expiry exceptions; company-wide invalidation
subsystem; Today/guided operations/mobile acceptance; mandatory verified evidence as
a *precondition* of every channel/authorization approval (scope validated when
present, not yet required); and all HOST/TEN hosting gates. This patch closes
E01–E07 only.
