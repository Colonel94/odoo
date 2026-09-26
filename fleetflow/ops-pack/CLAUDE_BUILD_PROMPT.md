# Claude Code — Build FleetFlow OPS-1: real fleet readiness and allocation

Act as a senior Odoo Community engineer with fleet-operations and security experience. Work in `Colonel94/odoo`. **Implement the bounded operational increment below; do not return only another plan or redesign the dashboard.**

## Read first; preserve the existing work

1. Read `FLEETFLOW_DUBAI_OPERATIONS_RESEARCH.md`, `SOURCE_REGISTER.json` and `OPS_BACKLOG_AND_ACCEPTANCE.md` supplied with this prompt.
2. Read the current repository addon, deployment, tests, tenant ADR/matrix and review/handoff files. Read the companion `fleetflow-github-review-and-claude-prompt.md` if available. The latest independently rechecked branch was `feat/fleetflow-workflow-platform` at `59bfb037ffa2c3b51f96c2f665029c1e7dab44d0` on 21 September 2026; draft PR #1 and 14 passing integration tests are previous review evidence, not permission to reset newer work.
3. Inspect current branch, worktree, remote commits and CI. Preserve unrelated files, uncommitted work, credentials and databases. Use a dedicated feature branch or an appropriate continuation branch after inspection. Do not merge, force-push or discard work. Keep the current UI and maintenance workflow.
4. Map existing `fleet.vehicle` fields and `fleetflow.order` behavior before adding models. Do not duplicate the vehicle register, confuse acquisition with first-registration date or treat a workshop technician as a driver.

**Product direction:** evolve FleetFlow into Dubai rental/limousine operations, not a maintenance-only app. The operations specification expands business scope; the existing customer isolation, branding, safety, backup and production gates remain mandatory.

## Deliverable for this execution

Build **OPS-1 only**, with small reviewable commits/diffs for: foundations, master/evidence data, readiness service, assignment/custody/hold actions, UI and tests. Produce a working local demonstration and evidence report. Defer later increments explicitly; do not implement all products, onboarding, payments and integrations in one change.

The complete slice is:

> create/import minimal vehicle and driver records → record and verify required authorization evidence → check a proposed shift → confirm only when eligible and conflict-free → check out with a fresh check → record return → see the actual availability and blocking reasons.

Retain compatible channel enrolments and a provisional rental reservation **capacity block**, but do not call this a completed rental agreement, renter-compliance, billing or TARS integration. Full rental checkout belongs to OPS-3.

## 1. Foundation corrections without losing momentum

Run current structural/integration checks and record results. Address the earlier review findings that affect this change: restrict demo helpers to explicitly disposable environments, refuse collisions with real users, target only identified demo records, use server-generated timestamps/domains for time-sensitive dashboard drill-through, and correct stale setup/status text. Add regressions; never weaken the original 14 tests.

The current compatible local runtime may be used with synthetic data. Document the Odoo baseline decision and a reproducible image/update proposal separately. Do not silently change major version or call Odoo 16 production-maintained without evidence. A missing production-version approval blocks real hosting, not writing the scoped local feature. If the runtime genuinely cannot be started, still deliver executable source/tests and label runtime validation blocked rather than pretending it passed.

## 2. Models and minimum data

Use a companion Community addon such as `fleetflow_operations` depending on `fleetflow`, or a similarly bounded extension justified in a short ADR. Keep Odoo core untouched. Add the new addon to local installation, upgrade, static checks and CI explicitly; tests that install only `fleetflow` are insufficient.

Recommended model responsibilities (reuse equivalent current models if present):

- **Vehicle extension:** current legal operator, owner/lease context, emirate and plate-code history, manufacture date plus precision, model year, first registration, acquisition/source category, powertrain, evidence-backed official classification and individual authorized end-of-use when available. Existing vehicles start operationally unreviewed; migration must not approve them by default.
- **Driver:** employer company, operational identifier/name, active status, optional app-user link, availability context. Keep identity numbers, documents and clearance evidence in restricted records. A driver app-user must not inherit workshop, dispatcher or system-administrator permissions merely to see their shift.
- **Operating authorization:** legal operator/activity, jurisdiction, reference and validity, linked verified evidence, and permitted mode. An external owner/lender is a partner, not a fabricated internal company or a cross-tenant foreign key.
- **Credential/evidence:** exactly one explicit subject (operator, vehicle or driver), document kind, issuer/reference, issue/start/end date precision, verification state, reviewer/time, protected attachment and supersession link. Constrain subject/company consistency. Keep lifecycle changes server-side and prevent forged verified states through create/write/import/context.
- **Channel enrolment:** operator, city, channel AND product, driver or vehicle subject, external ID, pending/approved/suspended/rejected status, evidence, verified-as-of and recheck date. A channel approval does not substitute for an operating permit; one vehicle may have several compatible channel approvals.
- **Operational profile / bounded rules:** explicitly selected requirements and versioned approved policy for a mode/company/product. Required checks may not vanish because no policy was configured. Missing, draft, ambiguous or expired policy coverage is Needs review. Finite built-in check types only; no arbitrary expressions or code evaluation.
- **Allocation:** operating company, mode, intended channel/product selections, vehicle, optional driver as applicable, planned interval, state, actual custody times, readiness snapshot/version, confirmation actor and return evidence. Do not overload `fleetflow.order.assignee_id` or `fleet.vehicle.driver_id` as the historical allocation ledger.
- **Vehicle hold:** reason/type, source work order or incident/reference, active interval/state, whether dispatch-blocking, creation/clearance actor/time/evidence. Separate holds remain independent.

Temporary operating-authority evidence must be scoped to named parties, vehicle, activity and interval. Unknown/unreviewed cross-company permission blocks use. For OPS-1, the UI may capture a reviewed external authorization; the full Takamul application/payment workflow is deferred. Never infer authority from shared ownership alone.

Use explicit company ownership, `_check_company_auto` where applicable, ACLs and record rules. Test referential constraints with forged IDs. Retain historical values after plate changes, employment changes, document replacement and retirement.

## 3. Readiness evaluation: the actual product logic

Implement one reusable server-side service for:

`evaluate_readiness(company, vehicle, driver/context, operating_mode, channel_products, starts_at, ends_at)`

Return structured status, reasons with stable codes, required next actions, checked interval, server evaluation time, rule versions and non-sensitive evidence references. Never return private identity or medical attachments just to explain a dispatch blocker.

Required checks for the selected and reviewed profile:

- Asset/driver exists, is active, and belongs to or has explicit authority for the operator; allowed-company context is respected.
- Operator/activity/vehicle-use permission covers the request.
- Required registration, insurance use scope, professional permit, licence and other applicable evidence is verified and valid for the **whole requested interval**, not only today.
- Driver employer/operator and channel enrolments match; requested products have verified approvals and acceptable freshness. Missing Careem-specific policy coverage must not reuse Uber rules.
- Known authorized end-of-use is not exceeded; unresolved category/age applicability is Needs review.
- No dispatch-blocking hold, incompatible allocation, unreturned custody or inactive/retired asset.
- Applicable driver availability and reviewed shift/rest policy passes; this is an operator policy unless an authoritative rule has been validated.

Semantics: Ready may confirm; Warning may confirm only with authorized acknowledgement of **non-blocking** items; Blocked and Needs review may not confirm/check out. There is no generic manager “ignore RTA/expired insurance” override. Correct evidence or policy through the audited review process instead.

Store document-expiry precision correctly. Date-only validity must use a documented local-time boundary, not an accidental UTC midnight. Do not assume every permit ends at 23:59 unless its semantics are confirmed. Handle an interval crossing an expiry and exact boundary tests; never fabricate a January 1 manufacture date from a year.

Read `SOURCE_REGISTER.json`: source observations are not pre-approved production rules. Load any reference rules as draft with provenance. Activate clearly labelled synthetic test profiles only in disposable fixtures. Do not seed a universal legal vehicle-age limit or a fabricated grace period. A compliance reviewer can publish a reviewed profile and explicit permit dates with evidence; mandatory baseline checks cannot be disabled by a dispatcher.

## 4. Allocation, checkout, return and concurrency

Allocation actions: draft → confirmed/reserved → checked out → returned/closed; cancellation before checkout and exception handling are explicit. Do not overwrite a completed custody event. Record operational allocation separately from actual Uber/Careem trip acceptance.

Use half-open planned intervals `[start, end)` so non-overlapping back-to-back plans are possible. Actual unresolved custody independently blocks a later checkout. A planned finish time or cancelled workshop task does not prove a car was returned. A future rental capacity block conflicts with a chauffeur shift; full rental customer checkout is not enabled in OPS-1.

Confirm and checkout must recompute readiness inside the same transaction used for resource conflict protection. Lock persistent vehicle/driver resource rows in deterministic order, or use another proven concurrency-safe design. Locking only existing allocation rows is insufficient when the conflict query is empty. Schedule/assignment edits and authoritative evidence/hold mutations must use compatible locking/version checks. Exercise separate database connections, not only sequential calls in one test transaction.

Handle two allocations for the same car, two cars for the same driver, checkout racing with hold creation, document revocation racing with dispatch, rescheduling and cancellation. Exactly one competing reservation should succeed; no partial state or stale green approval may survive an unsuccessful operation. Use normal ORM permissions; no broad `sudo()` to force actions through.

Freeze the decision/evidence snapshot for audit, but keep current readiness separate. After a relevant document expires or is revoked, flag affected active/future allocations and create a deduplicated in-app exception for the dispatcher. Do not silently mark them returned, disable a real engine, or claim an external platform account was suspended.

Minimal checkout/return records: actual timestamp, odometer with units/source, fuel or charge, condition notes and controlled defect flag. Reject negative/impossible readings; a decrease requires a reviewed correction/meter-change path, not silent acceptance. Serious reported defects create a hold and an existing FleetFlow work order through valid actions. A full photo/checklist driver portal is OPS-2 unless safely included within this scope.

## 5. Bridge maintenance to operations

Reuse the maintenance workflow and its existing protected approval/release state machine. A work order can create a linked dispatch-blocking hold according to an explicit operator policy. Do not make every cosmetic/service request an automatic legal grounding.

Completing a work order does NOT clear all vehicle holds or override expired documents. Clear only the specific resolved hold through an authorized action with evidence and then re-evaluate readiness. Cancelling a job does not clear its safety hold. Preserve multi-job holds and existing release/rework checks.

If operation fields are added to an existing maintenance form, ensure current `write()` guards, chatter, attachments and lifecycle hooks remain functional. Prefer narrow extension hooks over copying or bypassing the entire state machine.

## 6. Roles and private data

Define and test the minimum role matrix: dispatcher manages allocations and sees non-sensitive readiness; compliance reviewer verifies authorization/policy evidence; driver sees only permitted own assignments; workshop technician sees assigned repair work and relevant vehicle context; fleet manager handles allowed holds; finance role is reserved for later reporting.

Do not give all dispatchers unrestricted document downloads. File access, report/export routes, related-record name reads, chatter notifications, avatars and public attachment tokens must respect the same restrictions. Whitelist file types/size and reject active content; do not build unsafe arbitrary-URL downloaders. No health diagnoses in logs or dispatch reasons. Avoid collecting medical/psychological reports when a minimum clearance reference/status suffices.

Company isolation inside one tenant remains necessary but is not customer isolation. Existing TEN-01…06 requirements remain: separate runtime/database/filestore/secrets, trusted-host routing, private backups, own branding, isolated optional addons and shared automatic/manual provisioning. Do not mark those Verified through multi-company tests. No real-customer hosting in this increment.

## 7. UI: preserve the look, add real actions

Add operations navigation: **Today, Vehicles, Drivers, Assignments, Compliance, Maintenance**. Integrate with the existing FleetFlow experience rather than creating a second disconnected dashboard.

Today shows selected company/date interval, eligible resources, current custody, upcoming allocations, blocked work and expiring evidence with direct next actions. Vehicle/driver detail shows eligibility by mode/product and a timeline. Assignment form runs readiness and explains precise blockers before server-confirmed reservation/checkout. Compliance users have a verification/expiry queue; no fake RTA button or external live status.

Use server-provided cutoffs and domains for metrics/drill-through. Show as-of times and import/manual provenance. Test ordinary bundled assets and relevant debug mode, desktop at 1440 px and mobile at 390 px, keyboard focus and error/empty/loading states. End-user labels distinguish “internally verified evidence” from “authority issued.”

## 8. Required automated acceptance tests

Implement relevant model tests and HTTP/browser tests for the exposed paths. Preserve every original lifecycle test. Use synthetic data and ordinary users, with tests for at least:

1. Valid vehicle/driver/operator/profile/channel confirms and checks out.
2. Expired document prevents allocation; document expiring mid-interval also prevents it.
3. Required missing/unverified evidence, missing policy, unknown age category or partial manufacture date produces Needs review, never Ready.
4. A verified renewal supersedes history, re-evaluates the proposal and permits it only if all other checks pass.
5. Wrong employer/operator, vehicle ownership without operating authority, wrong city or missing channel product approval is rejected.
6. Suspended/stale platform status is treated according to the approved freshness policy; Uber eligibility does not silently approve Careem.
7. Temporary authorization must cover both parties, vehicle, mode and full interval; pending/expired permission cannot enable use.
8. Two incompatible allocations cannot share a driver or car. Two independent database connections cannot both win a conflicting reservation.
9. Adjacent planned intervals can be booked; late physical return blocks the second checkout.
10. Compatible multiple channel enrolments on one shift are not incorrectly rejected as duplicate vehicle assignments.
11. Rental capacity block conflicts with a shift; adding a reservation does not claim a legal rental/TARS contract exists.
12. Active maintenance hold blocks checkout; release of one job does not clear another hold; cancellation does not clear safety holds.
13. Checkout racing with hold creation/revocation cannot use stale readiness; resulting active exceptions are visible.
14. Driver cannot approve their own evidence, access others' assignments/documents or gain technician/manager privileges.
15. Direct RPC/create/write/import/default-context attempts cannot forge verified, confirmed, returned or cleared states.
16. Cross-company relation injection fails; exports, report paths and attachments follow permissions where exposed.
17. Date/time boundaries use the approved local semantics; skewed browser time does not change dashboard filter meaning.
18. Negative/stale/contradictory odometer inputs are handled explicitly; silent decreases do not corrupt history.
19. Restart and module update preserve allocations, evidence versions and original work orders.
20. Demo setup cannot reset normal users or reassign ordinary orders; repeated fixture loading and reminder jobs do not duplicate effects.

Make any unexecuted HTTP/browser/concurrency test explicit in the report. Do not call an in-memory mock a demonstrated database isolation boundary.

## 9. Required outputs and stop condition

Deliver source, migrations where needed, role matrix, tests, synthetic fixtures and `OPS1_IMPLEMENTATION_EVIDENCE.md`. Include exact commands, commit, runtime versions, test counts, real UI captures, skipped/failed checks and remaining gaps. Update the backlog with Implemented/Verified/Blocked distinctions; a file's existence is not proof it ran.

Demonstrate three fictional scenarios in the running application: ready chauffeur shift; blocked expiry/employer/channel mismatch with corrective action; workshop hold blocking a second dispatch until properly resolved. Keep the original UI's design language.

STOP after this end-to-end OPS-1 gate. Leave OPS-2…5 and HOST tasks tracked. Do not merge, deploy publicly, spend money, process real customer identities, delete working databases or silently upgrade Odoo. Do not implement actual platform dispatch, automatic licence renewal, payments, telematics or regulatory certification. If a decision is genuinely missing, use Needs review and keep building the local demonstrable mechanics rather than inventing a rule.
