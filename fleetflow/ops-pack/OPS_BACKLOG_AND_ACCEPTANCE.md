# Operations backlog and acceptance map

**Date:** 21 September 2026. **All new operations functionality below is proposed.** Existing maintenance capabilities and historical test evidence are the baseline, not proof these requirements are complete.

## OPS-1 — Build now: resource readiness and controlled allocation

| ID | Requirement | Acceptance |
|---|---|---|
| O1.01 | Operator/activity, vehicle and driver master records | Correct subject/company relations; no duplicate vehicle system or driver-as-technician shortcut. |
| O1.02 | Restricted versioned evidence | Pending upload cannot self-approve; valid renewal retains history; private documents inaccessible to unrelated users. |
| O1.03 | Per-city/product channel enrolments | Legal authorization and platform approval both checked; missing Careem profile is not filled with Uber assumptions. |
| O1.04 | Bounded readiness profiles | Finite predicates and explicit source/version; mandatory unknowns fail closed as Needs review. |
| O1.05 | Whole-interval evaluation | Mid-shift expiry/end-of-use fails; future warning outside requested interval is distinct. |
| O1.06 | Vehicle/driver allocation and actual custody | Concurrent conflicts prevented; late return blocks checkout; back-to-back plans and compatible app enrolments supported. |
| O1.07 | Maintenance holds | Specific clear action; cancelling/releasing one job cannot clear unrelated holds or expired documents. |
| O1.08 | Today/assignment/compliance screens | Working ordinary-user workflow; blockers have next actions; server-time metrics and no fake live status. |
| O1.09 | Foundation regression fixes | Safe synthetic seeding, existing tests retained, truthful runtime/status docs and version decision recorded. |
| O1.10 | Evidence report | Real test commands, results, screenshots and unexecuted checks; no production-readiness claim. |

## OPS-2 — Close the maintenance and handover loop

Add driver-scoped pre/post-shift forms, photos, acknowledgement, defective handover, planned service by date/km, authoritative odometer correction, workshop estimates/overruns, parts/labour detail, incident/police/insurer references and replacement allocation. Do not store medical diagnoses or infer accident blame.

Gate: repeated due jobs are idempotent; concurrent schedulers create one occurrence; resolved work does not clear other holds; late return/replacement preserves custody segments; inspection policy and human release responsibility are explicit. Manufacturer service intervals and shift/rest policies are configurable verified inputs, not guessed legal values.

## OPS-3 — Operate rental-without-driver

Add booking and authorized renter/driver records, quote, availability, agreement, deposit authorization/receipt, official TARS evidence, checkout, extension, swap, return inspection, charges/disputes, settlement and refund. Separate tourists' licence/insurance eligibility from employed limousine-driver permits. Keep optional hourly/taxi modes disabled until separately specified and confirmed.

Gate: extension/swap rechecks eligibility and conflicts; physical return drives custody; deposits are not earnings; internal signature/submission never pretends to be official acceptance; charge liability and release/refund need authorized approval.

## OPS-4 — Reconcile the money

Obtain one redacted real operator export format before claiming a working named-provider importer. Build generic CSV/XLSX mapping/import validation, source hashes/references, duplicate and correction handling, external-ID mapping, event-time attribution, exceptions, reconciled earnings/payouts/cash and operating-cost reports. Use import libraries safely and defend exported spreadsheet formulas. A synthetic sample is explicitly not an official Uber/Careem file.

Gate: duplicate/overlapping import cannot double earnings; statements and trips are not both counted as income; adjustments reconcile; mismatched IDs stay unresolved; toll reimbursements/cash/deposits/currencies are distinct; incomplete cost coverage visibly qualifies contribution. Obtain accountant approval before automated settlements/payroll/tax treatment.

## OPS-5 — Advance lifecycle/compliance

Validate activity/category-specific entry and replacement policies; implement versioned rule publication, official permitted end dates, extension cases, expiry/renewal task queues, platform eligibility updates, tracking-certificate renewals, TARS failure tasks and replacement forecast. Public research is the starting evidence, not all exceptions.

Gate: effective-dated policy updates identify affected work without rewriting history; draft/ambiguous rules never auto-approve; official application/payment/inspection milestones do not extend a permit until issued evidence exists. Confirm limo-specific cutoffs and approved model categories first.

## HOST — Non-negotiable customer-launch workstream

Retain TEN-01 separate runtime/database/filestore/secrets; TEN-02 individual sanitized branding across login/workspace/reports; TEN-03 shared standard code and isolated optional addons; TEN-04 one provisioning path for self-service and owner-assisted onboarding; TEN-05 private backup/restore/update/support/offboarding; TEN-06 two-tenant acceptance evidence.

Public hosting requires the appropriate maintained-core/version decision, explicit database connection restrictions, isolated secrets/mounts, trusted-host routing, negative HTTP/session/attachment/export tests, recovery drill and release review. Two companies in one local database are not two tenants. Paywall/signup success is not evidence isolation works. Manual assisted pilots do not bypass these gates.

## Data relationships to preserve across increments

Tenant → legal operator/company → approved activity profile. Vehicle has an owner and potentially separately authorized operator. Driver has an employer and product-specific enrolments. Allocation links the reviewed operator/vehicle/driver/mode/time; multiple compatible channel products are not multiple physical custody events. Holds and official evidence influence readiness independently of a work-order stage. Imported money references the event and historical custody/operator, not merely today's assigned driver.

## Current unknowns that must not be guessed

Complete Careem Dubai fleet/product checklist and access arrangements; activity-specific limousine retirement/entry limits; English rental-card ambiguities and current approved-class lists; individual franchise/insurance exceptions; production privacy/retention and support-access policy; real provider export schemas; official integration credentials/contracts; company shift/rest and settlement rules. Track each with owner and evidence needed. Missing knowledge must not be silently converted into approval.
