# OPS-1 — Approval-boundary & document-ownership closure evidence (review R01–R03)

**Increment:** close the approval/authority boundary (R01–R03) plus the directly
related vehicle-review (R04) and hold-history (R05) paths, and prove it through
real authenticated HTTP requests. This is the bounded correction the 25 Sep 2026
review asked for; it does **not** deliver or waive R04–R07's remaining scope, the
Today/handover UX, temporary authority, or any HOST/TEN hosting requirement.

## 1. Environment, commits and exact commands

| Item | Value |
|---|---|
| Starting commit | `dbfca40a` on `feat/fleetflow-ops1` (the reviewed head) |
| Runtime | `odoo:16.0` image (`16.0-20250909`) + PostgreSQL 15, isolated Docker compose projects (`fleetflow-test`, `fleetflow-http-test`), `down -v` teardown |
| Core baseline | Colonel94/odoo `16.0` at `7d63cda1` — unmodified |
| Host | Windows 11, Docker 29.6.2 |
| Structural | `python fleetflow/check_static.py` → **PASS** (fleetflow 5 py/4 xml/9 ACL; fleetflow_operations 29 py/11 xml/40 ACL) |
| Model + concurrency suite | `python fleetflow/manage.py test` → `--test-tags /fleetflow,/fleetflow_operations,-ff_http --no-http` |
| Authenticated HTTP suite | `python fleetflow/manage.py test-http` → `--test-tags ff_http` (HTTP server ON; no `--no-http`) + new CI job |

**Results (each run in full, isolated containers, clean teardown, this session):**

| Suite | Result |
|---|---|
| Model + concurrency (`test`) | **137 tests, 0 failed, 0 error** |
| Authenticated HTTP (`test-http`, `ff_http`) | **10 tests (B01–B10), 0 failed, 0 error** |
| Structural (`check_static.py`) | PASS both addons |
| Concurrency | the 9 real two-connection races (incl. the earlier F07 set) run inside the model suite and remain green; no lock regressions from the new write/unlink guards |

These three gates are reported **separately**; no single green count stands in for
all three. The `test-http` run really exercises a live HTTP server (Odoo HttpCase),
not an ORM-only or mocked-auth substitute.

## 2. Reproduce-before-fix (measured, not asserted)

The model logic was reverted to `dbfca40a` (via `git stash` of `models/` only,
new tests kept) and `manage.py test` was re-run. **23 of the new tests failed
against the pre-fix code**, demonstrating they catch real defects; all 23 pass
with the fix. Failing-before-fix set:

*Authority / revision (16):* `test_dispatcher_cannot_repoint_approved_enrolment_subject`,
`test_dispatcher_cannot_change_approved_enrolment_scope`,
`test_dispatcher_cannot_extend_recheck_on_approved`,
`test_enrolment_evidence_must_match_subject`,
`test_verified_credential_cannot_be_downgraded`,
`test_rejected_credential_content_frozen`,
`test_suspended_enrolment_cannot_be_reset_to_pending`,
`test_verified_authorization_cannot_be_downgraded`,
`test_published_profile_cannot_be_unpublished`,
`test_manager_cannot_forge_reviewed_vehicle_at_create`,
`test_default_context_cannot_forge_reviewed_vehicle`,
`test_cannot_forge_verified_authorization_at_create`,
`test_cannot_forge_published_profile_at_create`,
`test_manager_cannot_delete_hold`,
`test_manager_cannot_downgrade_blocking_flag`,
`test_manager_cannot_move_hold_to_other_vehicle`.

*Document ownership (7):* `test_foreign_file_bound_elsewhere_is_rejected_and_unchanged`,
`test_attachment_bound_to_other_credential_is_rejected`,
`test_foreign_company_file_is_rejected`, `test_active_content_is_rejected`,
`test_empty_file_is_rejected`, `test_verified_evidence_source_cannot_be_mutated_or_deleted`,
`test_verified_source_cannot_be_rebound`.

**New coverage (passes on both pre- and post-fix — hardening, not a reproduced
defect):** the positive paths (`test_reviewer_can_manage_recheck_on_approved`,
`test_authorized_clear_is_attributable_and_still_works`,
`test_own_unbound_upload_binds_and_privatises`) and
`test_other_company_reviewer_cannot_read_evidence_file` (core already denied the
cross-company read via the linked-record rule; the explicit check makes it robust).

## 3. Authenticated HTTP acceptance (B01–B10)

All run as real sessions via `/web/dataset/call_kw` and `/web/content`; superuser
only builds fixtures. Each asserts the **response body and resulting DB state**,
not just transport status. Test class: `TestHttpBoundary` (`tests/test_http_boundary.py`).

| ID | Case | Test | Status |
|---|---|---|---|
| B01 | Dispatcher can't transfer an approved enrolment (city) or lift a suspension | `test_B01_dispatcher_cannot_mutate_approved_or_lift_suspension` | **Fixed-and-tested** |
| B02 | Writers can't downgrade a verified credential / published policy in place | `test_B02_compliance_cannot_downgrade_history` | **Fixed-and-tested** |
| B03 | create/default-context can't fabricate reviewed state or exemption | `test_B03_create_cannot_forge_review_state` | **Fixed-and-tested** |
| B04 | Hold can't be deleted / made non-blocking; authorized clear works & is attributable | `test_B04_hold_history_is_protected_but_clear_works` | **Fixed-and-tested** |
| B05 | Future renewal preserves current coverage; competing revisions deterministic | `test_B05_future_renewal_preserves_current_coverage` | **Fixed-and-tested** (coverage-preservation over HTTP; full supersede-link staging also covered by model `test_lifecycle`/`test_evidence`) |
| B06 | Own upload links; foreign/bound file rejected unchanged | `test_B06_own_upload_links_foreign_rejected` | **Fixed-and-tested** |
| B07 | Verified source can't be replaced/published via generic attachment RPC | `test_B07_verified_source_immutable_over_rpc` | **Fixed-and-tested** |
| B08 | Dispatcher / other-company sessions can't fetch bytes via `/web/content`; owner can; metadata stays readable | `test_B08_binary_download_is_role_and_company_scoped` | **Fixed-and-tested** |
| B09 | Unauthenticated / guessed-access-token requests return no protected bytes | `test_B09_public_and_token_variants_are_forbidden` | **Fixed-and-tested** |
| B10 | Allowed reviewer/verify/attachment actions still work; unrelated attachments intact | `test_B10_allowed_actions_still_work` | **Fixed-and-tested** |

## 4. What was implemented (transition / field matrix)

Guards are enforced on public `create`/`write`/`unlink`/`copy`/`default_*` paths;
authorized transitions go through private action methods that write via `_apply`
(ORM-level, after role/state/prerequisite checks). No caller-controlled context
flag is a capability.

| Model | Unforgeable at create | Frozen once reviewed | State transitions | Notes |
|---|---|---|---|---|
| `credential` | `verified/superseded` state + `verified_by/on` (all users) | content of `verified/superseded/rejected` | verify/reject/supersede only; **no downgrade** of a terminal record by direct write (non-su) | supersede stages a renewal; predecessor stays effective until the renewal is verified |
| `channel.enrolment` | reviewed state + `verified_as_of` | subject/company/channel/product/city/`evidence_id` (hard, incl. su) | approve/suspend/reject only; **no direct state write** (non-su), incl. suspended→pending | `recheck_date` reviewer-only once reviewed; linked `evidence_id` must match subject+company |
| `operating.authorization` | `verified/…` state + `verified_by/on` | scope/dates of a verified record | verify/reject only; **no downgrade** from terminal (non-su) | — |
| `operating.profile` | `published` state | required-checks of a published/archived version | publish action only; **no un-publish** in place (non-su) | corrections = a new published version |
| `fleet.vehicle` (review) | `ff_operational_state`, `ff_end_of_use_exempt`, `ff_authorized_end_of_use`, reviewer attribution (non-su create/copy/default) | set only via compliance actions | `ff_mark_reviewed` / `ff_review_end_of_use` | su may seed reviewed state for fixtures/migration |
| `vehicle.hold` | active + no clearance history | vehicle/type/reason/`dispatch_blocking`/source/reference (non-su) | clear action only (fleet-manager + note) | **`unlink` blocked** for non-su — deletion is not a clearance route |
| `ir.attachment` (evidence) | — | a verified-evidence source: bytes/binding/public/token immutable, `unlink` blocked (non-su) | binding via `credential._bind_attachment` after ownership/company/policy checks | read restricted to compliance/fleet **and** to the credential's company |

**Document ownership (R03):** the unconditional `sudo().write()` reparenting in
`credential.py::_bind_attachment` is removed. Binding now verifies, with the
caller's own rights, that the file is theirs to bind (writable, unbound-or-already-
this-credential, same company, passes a PDF/JPEG/PNG + size + non-active-content
policy judged on the real bytes) before privatising it and dropping any token. A
rejected link leaves the original owner/binding/bytes/public/token unchanged.

## 5. Legitimate fixture changes (explained, not to preserve a count)

- `tests/common.py::make_channel` gained a `city="Dubai"` argument.
- `tests/test_eligibility.py::test_wrong_city_enrolment_does_not_satisfy` now builds
  the approvals for the wrong city instead of re-pointing approved Dubai ones,
  because a reviewed enrolment's city is now frozen (part of what was approved).
  The tested behaviour (wrong city ⇒ not ready) is unchanged.
- `tests/test_privacy_custody.py`: the old `test_foreign_attachment_is_rebound_when_linked`
  (which asserted a foreign file **should** be reparented) is removed; the correct
  reject-and-leave-unchanged behaviour is covered in `tests/test_document_ownership.py`.
- Vehicle-review at create is now unforgeable for ordinary users; superuser fixtures
  (and `seed_ops.py`, which runs as `SUPERUSER_ID`) are unaffected, so no seed change
  was required.

## 6. Migration / update behaviour

Changes are model logic, ACL-compatible, and add no new fields or schema (the only
field-attribute change is `ff_authorized_end_of_use` gaining `copy=False`). Both
suites run with `-i fleetflow_operations` on a fresh install in disposable
containers; the guards are code-path checks that also apply on upgrade (they read
current record state, not install-time data). No security data that "loads once"
is relied upon. No working database or volume is touched by the test commands.

## 7. Files changed in this increment

Models: `channel_enrolment.py`, `credential.py`, `operating_authorization.py`,
`operating_profile.py`, `fleet_vehicle.py`, `vehicle_hold.py`, `ir_attachment.py`.
Tests: new `test_boundary_authority.py`, `test_document_ownership.py`,
`test_http_boundary.py`; edited `common.py`, `test_eligibility.py`,
`test_privacy_custody.py`, `tests/__init__.py`. Tooling: `fleetflow/manage.py`
(new `test-http` command; model run excludes `ff_http`), `.github/workflows/fleetflow.yml`
(new HTTP job). Evidence: this file; `OPS1_REVIEW_FIX_EVIDENCE.md` updated.

## 8. Remaining — explicitly NOT delivered or waived by this increment

R04–R07's full scope (actual handover interval/conflict re-evaluation, complete
evidence-bound readiness, company-wide invalidation, a persistent expiry-exception
subsystem, immutable custody/decision events), the operational Today screen, guided
handover/return, minimal reviewed temporary authority, mobile/lifecycle acceptance,
and all HOST/TEN hosting requirements (owner-hosted monthly subscriptions, per-
customer runtime/DB/filestore/secrets, branding, isolated customer addons,
provisioning) remain open. This patch closes the R01–R03 boundary and its directly
related R04/R05 paths only, and participates in the existing resource-lock protocol
without claiming the separate company-wide invalidation subsystem.
