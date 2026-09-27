# OPS-1 — Targeted closure: linked-renewal identity (C1) and indirect PDF values (C2)

Two focused integrity corrections on top of the reviewed baseline. Not a milestone,
not production approval, not regulatory certification.

## Environment, commits, commands

| Item | Value |
|---|---|
| Reviewed baseline | `d0486a74` on `feat/fleetflow-ops1` (module 16.0.1.2.0), local == origin |
| Tested commit | this branch head after the change — SHA reported with the push |
| Runtime | `odoo:16.0` image `16.0-20250909` (`sha256:0f36a500…`), Python 3.9.2, **PyPDF2 1.26.0**, Pillow 8.1.2, PostgreSQL 15 |
| Core / host | Colonel94/odoo `16.0` unmodified; Windows 11, Docker 29.6.2 |
| No schema change | this correction adds no field/column and no migration script (read-time semantics only) |

```
python fleetflow/check_static.py
python fleetflow/manage.py test        # model + concurrency (-ff_http, --no-http)
python fleetflow/manage.py test-http   # authenticated HTTP/JSON-RPC (ff_http)
python fleetflow/manage.py test-update # disposable install -> -u smoke
# data-safety: fleetflow/migrate_drill/ (c1_seed.py / c1_assert.py), genuine d0486a74 -> new
```

### Results (this session; `odoo.tests.result` totals, isolated containers, `down -v`)

| Suite | Total (result line) | Outcome |
|---|---|---|
| `check_static.py` | fleetflow 5 py/4 xml/9 ACL; fleetflow_operations 37 py/11 xml/40 ACL | **PASS** |
| `manage.py test` | **204 tests** | **0 failed, 0 error** |
| `manage.py test-http` | **18 tests** (B01–B18) | **0 failed, 0 error** |
| `manage.py test-update` | **189 tests** | **0 failed, 0 error** (no migration — no schema change) |

Counts are the final `odoo.tests.result` totals, not summed per-module/per-setup stats.

## C1 — Linked-renewal identity protected during editing and verification

### Confirmed pre-fix behaviour (reviewed `credential.py` at `d0486a74`)

`action_supersede` forced the predecessor's company/subject/doc-kind onto the new
draft, but `credential.write` allowed those identity fields to change while the
renewal was draft/pending, and `action_verify` did not revalidate continuity. A
linked renewal could therefore be redirected to a different vehicle / document kind
/ company+subject and then approved as a continuation of a claim it no longer
matched. Reproduced with an ordinary compliance reviewer and the real
`action_supersede` (no injected protected links).

### Fix

- **Write guard:** a linked renewal (`supersedes_id` set) may not change any
  identity field (`company_id`, `operator_company_id`, `vehicle_id`, `driver_id`,
  `doc_kind`) to a value differing from the predecessor's, at any point in its
  lifecycle — while dates, issuer/reference and the replacement upload stay
  editable. Only the identity is fixed; ordinary (non-renewal) drafts are
  unaffected (no blanket field freeze).
- **Verification re-check under lock:** `action_verify` locks the records being
  verified `FOR UPDATE`, re-reads their identity and refuses any renewal whose
  identity no longer matches its predecessor — so a redirect cannot defeat approval
  even via a path that bypassed the write guard or a concurrent edit.
- **Single unambiguous replacement:** the competing-approval conflict is judged on
  the actual replacement link (`superseded_by_id`), not merely the predecessor's
  current `state`, so a predecessor already linked to a since-revoked successor
  cannot silently gain a second one.
- **Inconsistent legacy chains flagged:** `_cutover` returns None when the linked
  successor does not share the predecessor's identity, so such a chain grants no
  coverage (surfaced for review) and its historical identity is never rewritten.

### Post-fix results

Model `TestRenewalIdentity` (13 tests) and HTTP `test_B18_linked_renewal_identity_protected_over_rpc`
pass. Redirect over ORM and RPC is refused with a business error; the predecessor,
renewal, links and attribution are unchanged; a legitimate same-identity renewal
(dates/issuer edited) still prepares, verifies and covers correctly on both sides of
the cutover; the supersedes link stays unforgeable; copies are independent.

### Reproduction (isolated copy, `credential.py` reverted to `d0486a74`)

`TestRenewalIdentity` failing pre-fix, passing post-fix:
`test_cannot_redirect_renewal_to_another_subject`,
`test_cannot_change_renewal_document_kind`, `test_cannot_change_renewal_subject_type`,
`test_two_company_reviewer_cannot_transfer_renewal`,
`test_rejected_redirect_leaves_both_records_and_links_unchanged`,
`test_verification_refuses_a_diverged_renewal`,
`test_inconsistent_legacy_chain_flagged_not_covered` (7 tests). Preserved-behaviour
tests (legitimate edit, same-identity coverage, copy independence, link
unforgeability, competing-approval conflict) pass on both sides.

### Data safety (genuine old→new drill)

`fleetflow/migrate_drill/c1_seed.py` + `c1_assert.py`, baseline `d0486a74` → new:
seeded a real redirected chain under the OLD code (Car A predecessor superseded,
Car B renewal verified — the bug), upgraded, and asserted **C1_ASSERT_OK**: stored
identities (Car A / Car B) and the replacement link are preserved, the chain is
flagged (`_cutover` None) and grants no coverage. No schema change, no migration
script; the drill proves the read-time semantics are safe for pre-existing data.

## C2 — Indirect PDF action/type values checked correctly

### Confirmed pre-fix behaviour

In `_pdf_check_dict` the `/S`, `/Type` and `/Subtype` values were normalised and
compared directly. When such a value is an `IndirectObject`, the comparison saw the
reference (e.g. `IndirectObject(6, 0, …)`), not the resolved name, so a prohibited
action/type stored as `N 0 R` bypassed the policy; the later graph traversal
resolved the object but no longer had the dictionary-key context. Verified against
the installed parser (PyPDF2 1.26.0) with genuinely valid, inert fixtures.

### Fix

`_pdf_check_dict` now resolves each semantic value (`_pdf_resolve_value`) while it
still knows the key, then applies the existing prohibited-feature policy to the
resolved name. Resolution follows an indirect chain bounded by a hop cap
(`_PDF_MAX_REF_CHAIN`) and a cycle set; a cyclic/over-long chain is unresolvable and
the document is rejected (fail closed); a broken reference raises inside the parser
and is turned into a business validation error. Keys (always direct) are still
checked directly. Not a raw-substring check; indirect objects are not blanket
blacklisted; valid PDFs with harmless indirect values are still accepted. Applied at
binding and immediately before verification.

### Post-fix results

Fixtures verified against PyPDF2 1.26.0. Model `TestPdfValidation`:
`test_indirect_action_and_type_values_rejected` (indirect `/S` → /Launch, indirect
`/Type` → /EmbeddedFile, indirect `/Subtype` → /Screen, a reference chain, and a
hex-escaped indirect name — all rejected on the resolved value),
`test_cyclic_reference_fails_safe_as_business_error`,
`test_harmless_indirect_values_accepted` (indirect `/Subtype` → /Link and `/S` →
/URI accepted), `test_indirect_direct_action_still_rejected`, plus the
`test_bad_pdfs_are_rejected_as_business_errors` / `test_valid_pdfs_bind_and_verify`
loops (which now include the indirect fixtures). HTTP `test_B16` exercises indirect
`/S`, indirect `/Subtype`, a cyclic reference, `js_indirect`, `fake_header` and
`encrypted` over authenticated RPC — each a **business** denial (never a 500) — and
a valid PDF still binds and verifies.

### Reproduction (isolated copy, `credential.py` reverted to `d0486a74`)

`test_indirect_action_and_type_values_rejected` and
`test_bad_pdfs_are_rejected_as_business_errors` fail pre-fix for
`s_indirect`, `type_indirect`, `subtype_indirect`, `s_ref_chain`,
`s_indirect_escaped` (10 subtest failures), and pass post-fix. Direct-action and
cyclic cases pass on both sides (already handled by the direct check / the parser's
bounded recursion).

Isolated-copy reproduction total: **17 failed of 24** targeted tests on the reviewed
`credential.py`; **0 failed** with the fix (part of the 204-test suite).

## C3 — Existing regression suites remain passing

`check_static` PASS; `manage.py test` 204/0/0 (incl. the verification-race
multi-connection suite, effective-cutover, evidence-lifecycle, allocation, boundary,
ownership, privacy); `manage.py test-http` 18/0/0 (B01–B18); `manage.py test-update`
189/0/0. The source-lock fix, attachment immutability/privacy, replacement cutoffs,
verification/revocation history and company/role restrictions are unchanged and
covered by the existing tests.

## Retained limitation (unchanged, still open)

PyPDF2 1.26.0's own parse is not independently time-limited. Input-size and
traversal (object/reference/depth/page/ref-chain) budgets bound our work but do NOT
prove all parser work is time-bounded. This remains an explicit **pre-customer-upload
requirement**: a bounded local parsing mechanism must be implemented and tested
before accepting untrusted customer uploads. It does not block isolated synthetic
development of the next operations increment. No malware-protection claim is made.

## Scope / not done

Handover and return integrity, live eligibility exceptions and the Today operations
screen are the next increments and are **not** started here. Commercial requirements
(owner-hosted monthly subscriptions; isolated per-customer runtime/DB/filestore/
secrets; branding; optional customer addons; private backup/restore; shared
provisioning) are retained as requirements, not implemented. This correction is not
production approval or regulatory certification.
