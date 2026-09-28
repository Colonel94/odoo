# OPS-1 — Targeted closure: effective-dated replacement, structural PDF, verification race

Bounded correction covering exactly three items. It does **not** complete the
OPS-1 milestone or any production-readiness/HOST/TEN gate, add handover/custody
redesign, live exceptions, Today/mobile, billing or integrations, and it does not
certify RTA/roadworthiness/legal compliance.

## 1. Environment, commits, exact commands

| Item | Value |
|---|---|
| Starting commit (reviewed baseline) | `e60aba4c` on `feat/fleetflow-ops1` (module 16.0.1.1.0) |
| Tested commit | this branch head after the change (module **16.0.1.2.0**) — SHA reported with the push |
| Runtime | `odoo:16.0` image `16.0-20250909` (digest `sha256:0f36a5002a200bb1649771c2cb9403ca5392d7ac4bb23f9ad500b339df3f5a3a`), **Python 3.9.2**, **PyPDF2 1.26.0**, **Pillow 8.1.2**, PostgreSQL 15 |
| Core baseline | Colonel94/odoo `16.0` — unmodified (the image's coherent core is used) |
| Host | Windows 11, Docker 29.6.2 |
| Isolation config (recorded) | PostgreSQL **`repeatable read`** (asserted by `TestVerificationRace.test_isolation_is_repeatable_read` via `SHOW transaction_isolation`) |

Commands (each in isolated compose projects, `down -v` teardown):

```
python fleetflow/check_static.py
python fleetflow/manage.py test         # model + concurrency; --test-tags /fleetflow,/fleetflow_operations,-ff_http --no-http
python fleetflow/manage.py test-http    # authenticated HTTP/JSON-RPC (ff_http), HTTP server ON
# genuine old->new migration drill (see fleetflow/migrate_drill/README.md)
```

### Results (this session, full isolated containers, clean teardown)

| Suite | Result |
|---|---|
| Structural (`check_static.py`) | **PASS** — fleetflow 5 py/4 xml/9 ACL; fleetflow_operations 36 py/11 xml/40 ACL |
| Model + concurrency (`test`) | **0 failed, 0 error** — fleetflow 17 tests, fleetflow_operations **205 tests** (incl. new `TestPdfValidation`, `TestEffectiveCutover`, `TestVerificationRace`) |
| Authenticated HTTP (`test-http`, `ff_http`) | **0 failed, 0 error of 17 tests** (B01–B17) |
| Old→new migration drill | **SEED_OK** (1.1.0) → migration ran (`Running migration [16.0.1.2.0>] post-migrate`) → **ASSERT_OK** (1.2.0) |

Each suite is reported separately; no single count stands in for another. HTTP
denials are asserted by **business** exception type (Access/User/Validation), so a
500/programming error fails the test.

## 2. Root causes and rationale

1. **Effective-dated replacement.** The reviewed `_validity` counted a `superseded`
   record over its **own full printed range**, so a predecessor kept operating
   authority after its successor took over. Root cause: coverage was keyed on the
   record's own dates with no notion of a cutover. Fix: a superseded record's
   effective interval now ends at its **cutover** — the successor's own effective
   start (`_cutover`) — derived from the immutable, linked successor (so it cannot
   silently move if the successor is later expired/revoked/rejected/archived, and
   is never confused with the approval timestamp). Whole-interval coverage is
   resolved by `_resolve_coverage`: a single record, else a **continuous reviewed
   renewal chain**; never a bridged gap or unrelated records. An approval-time
   guard refuses a linked renewal without a precise effective date (no guessing
   "today"); a `FOR UPDATE` lock + conflict check on the predecessor makes
   competing approvals produce one unambiguous chain.

2. **Structural PDF validation.** The reviewed check tested a `%%EOF` marker and
   raw prohibited substrings — it accepted a structureless "PDF" and both
   false-rejected ordinary page text mentioning a keyword and could be bypassed by
   an escaped/indirect name. Fix: parse with the runtime parser and enforce
   prohibited features **semantically** over the resolved object graph.

3. **Verification vs. attachment mutation race — reproduced.** `action_verify`
   took only a transient `SELECT … FOR UPDATE` on the source row and left **no
   committed change** on it. A writer that observed the still-unverified credential
   on an older REPEATABLE-READ snapshot could therefore commit an attachment
   overwrite/publish/rebind **after** approval without conflicting, leaving
   verified evidence pointing at un-validated bytes. Fix: approval now performs a
   committed source-row bump (`ff_source_lock`), so such a write conflicts
   (first-updater-wins) and aborts.

## 3. Replacement / cutover policy and boundary examples

Half-open `[start, end)` intervals, local-day boundaries in the operator timezone.
A superseded record covers `[date_start, min(date_end+1, cutover))`; the successor
covers from `cutover = its date_start`. Named synthetic example (predecessor valid
through 31 Dec 2026; successor approved 26 Sep 2026, **effective 1 Oct 2026**,
valid through 31 Oct 2026):

| Requested interval | Covered by | Test |
|---|---|---|
| 30 Sep 2026 | predecessor | `test_synthetic_predecessor_covers_before_cutover` |
| 1 Oct 2026 (cutover, inclusive) | successor | `test_synthetic_successor_covers_at_and_after_cutover` |
| 1 Nov 2026 (successor expired) | **nothing** — no fall-back to predecessor | `test_synthetic_no_fallback_to_predecessor_after_cutover` |
| 30 Sep 08:00 → 1 Oct 18:00 (spans cutover) | predecessor **+** successor (chain) | `test_synthetic_continuous_interval_spans_cutover` |
| revoke successor after activation | predecessor **not** restored | `test_revoking_successor_after_activation_does_not_restore_predecessor` |

Also covered: exact-cutover half-open equality; a real predecessor→successor gap
(not bridged); a multi-revision chain across two cutovers; a successor revoked
before its future start (recorded cutoff not erased); a never-approved rejected
renewal (coverage intact); a revoked predecessor before a future successor; missing
/imprecise effective date refused at approval; competing drafts/approvals (one
chain); ambiguous legacy cutover surfaced for review; order-independence; and
forged `superseded_by_id`/`supersedes_id`/`replaced_on` + copy rejected. External
readiness contract and reason codes are preserved; the "expiring soon" warning is
derived from the record actually used at the interval end (an obsolete
predecessor's expiry never warns for a successor-covered period).

## 4. PDF acceptance policy, parser version, limits

- **Parser:** `PyPDF2==1.26.0` (the version in `odoo:16.0`, Python 3.9), declared in
  the platform `requirements.txt`; no new dependency added. Opened `strict=False`;
  successful construction is **not** treated as success.
- **Structure:** a readable page tree is required (`getNumPages() ≥ 1`) and the
  catalog is walked; malformed/unsupported/broken-reference structures are rejected.
  **Encrypted** documents cannot be inspected and are rejected (no password handling
  added).
- **Prohibited features (semantic, over resolved indirect objects):** banned dict
  keys `/JS /JavaScript /AA /OpenAction /AcroForm /RichMedia /EmbeddedFiles /EF`;
  banned action `/S` subtypes `/JavaScript /Launch`; banned `/Type`/`/Subtype`
  values `/EmbeddedFile /Filespec /RichMedia /Screen /Movie`. Names are normalised
  (`#xx` hex-escapes decoded), so an escaped or indirect reference cannot bypass the
  policy, while ordinary page text mentioning a keyword is accepted.
- **Bounds:** input ≤ 15 MB (size checked before parse); traversal bounded by
  ≤ 4000 pages, ≤ 60000 resolved objects, depth ≤ 60; stream data is never decoded
  (no decompression), no action executed, no external access, original bytes never
  rewritten. Applied at binding **and** re-applied on the current bytes at
  verification under the source-row lock.
- **Error handling:** expected malformed-document failures (`PdfReadError`,
  `ValueError`/`KeyError`/`IndexError`/`AssertionError`/`EOFError`/`RecursionError`/
  `OverflowError`/`struct.error`) become business validation errors;
  `AttributeError`/`TypeError`/`NameError` are deliberately **not** caught, so a
  defect is not disguised as a rejection.
- **Fixtures replaced:** the earlier structurally-invalid stub PDFs are gone;
  `tests/pdf_fixtures.py` builds genuinely valid PDFs (one/multi-page, image-based,
  keyword-in-text) with real xref tables, verified against PyPDF2 1.26.0, plus
  negatives (fake header, truncated, broken reference, indirect JS, hex-escaped
  action, AcroForm, embedded file, rich-media/screen, Launch, /AA, incremental
  update that redefines the catalog, encrypted). `TestPdfValidation` and HTTP
  **B16** exercise accept + reject over model and authenticated RPC.

**Retained limitation:** PyPDF2 1.26.0's own xref/page-tree parse is not separately
time-sandboxed. Consumption is bounded by the 15 MB input cap plus the object/
reference/depth/page budgets on our traversal; a subprocess time-sandbox was not
added (out of scope for this local synthetic increment) and is recorded here.

## 5. Verification-race schedule and final-state assertions

`TestVerificationRace` uses two independent committed connections
(`registry().cursor()`) under REPEATABLE READ, ordered by `threading.Event`s (no
sleeps): (1) the editor — a compliance reviewer with genuine pre-approval write
permission on the not-yet-approved draft's file — reads the credential to pin its
snapshot (`observed_ever_verified` asserted `False`); (2) the reviewer verifies and
commits; (3) the editor then attempts its mutation and commits. Final state is
asserted from a **fresh** transaction comparing source id and **SHA-256** byte
hash, not just the verified flag: the credential still references the exact
validated source, its bytes are unchanged, and it is neither deleted, rebound nor
published.

| Mutation after approval | Result | Closed by |
|---|---|---|
| overwrite bytes (`raw`) | serialization abort | source-row bump |
| publish/tokenise | serialization abort | source-row bump |
| unbind source (`res_model/res_id`) | serialization abort | source-row bump |
| delete source | serialization abort | row lock + delete-vs-committed |
| repoint credential pointer | serialization abort | credential-row conflict |

Also verified: the **reverse ordering** (a valid edit committed *before*
verification) succeeds and verification validates the committed replacement bytes
(final state matches a safe serial order); and **retry** — the losing editor, on a
fresh transaction, is cleanly refused by the durable freeze with a business
`AccessError` (not another serialization), bytes still approved. No manual commit
in business methods, no isolation change, no `sudo` business-boundary bypass; the
attachment lock is taken before the credential/subject locks, consistent with the
existing checkout/resource lock order.

## 6. Migration proof (genuine old → new)

`fleetflow/migrate_drill/` runs a disposable database populated under the **old**
module (16.0.1.1.0) and upgraded to the **new** module (16.0.1.2.0). Seeded old
data: standalone verified (with file), a precise superseded chain, a revoked/
rejected record (with file), a draft future-renewal, and an *ambiguous legacy*
chain (imprecise successor date — only creatable under the old code). After
`-u fleetflow_operations` (log: `module fleetflow_operations: Running migration
[16.0.1.2.0>] post-migrate`) the assertions hold (`ASSERT_OK`, `nulls_remaining=0`):
ids, supersession links, verification/revocation attribution and source-byte
hashes unchanged; the legacy superseded predecessor's authority now ends at its
cutover (no fall-back), pre-cutover and successor-window coverage correct; the
ambiguous legacy chain grants no coverage (surfaced for review, not guessed);
untouched records still behave. The only schema change is the additive nullable
`ir_attachment.ff_source_lock`; the cutover is derived (no fabricated historical
approval/effective facts), and the post-migrate only initialises the new column —
safe to repeat. A fresh install + same-version update is **not** used as the proof.

## 7. Reproduced pre-fix failures (measured)

In an isolated copy of the tree with **only** the two fixes reverted (the
source-lock bump and the superseded-cutover bound), the model suite was re-run:
**9 targeted tests failed** and pass with the fix —

- cutover (5): `test_synthetic_no_fallback_to_predecessor_after_cutover`,
  `test_synthetic_continuous_interval_spans_cutover`,
  `test_revoking_successor_after_activation_does_not_restore_predecessor`,
  `test_successor_revoked_before_future_start_keeps_recorded_cutoff`,
  `test_ambiguous_legacy_cutover_surfaces_for_review`;
- race (4): `test_replace_bytes_after_approval_is_blocked`,
  `test_publish_source_after_approval_is_blocked`,
  `test_rebind_source_after_approval_is_blocked`,
  `test_losing_editor_is_cleanly_refused_on_retry`.

The user's worktree was not touched (an isolated copy was used). `delete`/`repoint`
were already protected by the existing row/credential-row locks, so they pass on
both sides — labelled preventive, not reproduced.

## 8. Completion matrix

| Item | Status | Evidence |
|---|---|---|
| **Effective-dated replacement** — no fall-back past cutover; chain across cutover; boundaries/gaps/competing/ambiguous | **Reproduced & fixed** | `TestEffectiveCutover` (5 fail pre-fix), HTTP **B05/B17**, migration assert |
| **Structural PDF validation** — real parser, semantic prohibited-feature policy, valid positives accepted | **Fixed (strengthening) + regression** | `TestPdfValidation`, HTTP **B16**, fixtures verified vs PyPDF2 1.26.0 |
| **Verification vs. mutation race** — overwrite/publish/unbind paths | **Reproduced & fixed** | `TestVerificationRace` (4 fail pre-fix), fresh-txn hash assertions |
| Race: delete / repoint paths | **Regression/preventive** (already protected) | `TestVerificationRace` (pass both sides) |
| Reverse ordering + retry after serialization | **Regression** | `TestVerificationRace` reverse/retry tests |
| Old-data migration | **Proven** | `fleetflow/migrate_drill/` (SEED_OK → migration → ASSERT_OK) |
| Existing OPS-1 coverage (E01–E07, allocation, boundary, ownership, HTTP) | **Preserved** | `test` 0/0, `test-http` 0/0, `check_static` PASS |

## 9. Remaining limitations / explicitly deferred

- PyPDF2 1.26.0 parse-time is not separately sandboxed (bounded by size + traversal
  budgets; §4).
- A hand-authored compressed **object-stream** fixture was not added; object streams
  are resolved transparently by the parser during traversal (via `getObject`), and
  incremental-update effective-document inspection is covered by a fixture.
- Everything outside these three corrections remains open: handover/custody redesign,
  live eligibility exceptions, Today/mobile, rental contracts/billing/integrations,
  tenant provisioning/hosting, and all HOST/TEN gates. This patch does **not** mark
  the OPS-1 milestone or any production-readiness gate complete.
