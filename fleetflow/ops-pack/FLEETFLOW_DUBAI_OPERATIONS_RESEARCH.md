# FleetFlow — Dubai fleet operations: researched processes and product requirements

**Research date:** 21 September 2026  
**Market boundary:** Dubai rental-without-driver and licensed limousine/chauffeur fleet operations using approved distribution channels. Other emirates, taxi franchises, hourly rental and delivery require separate profiles.  
**Commercial model:** monthly subscriptions hosted by Omar, with isolated customers and customer-specific branding.  
**Status:** researched product specification, not implemented functionality, legal certification or evidence of production readiness.

## 1. The product we should build

FleetFlow should become the operator's system for deciding what can operate, recording who has each vehicle, preventing conflicting allocations, coordinating maintenance, and reconciling the money. It should not pretend to replace Uber/Careem dispatch, TARS, RTA licensing or an approved tracking provider.

Its main question is:

> Can this vehicle and this driver operate for this legal company, in this service/channel, for the entire requested period—and what must happen if they cannot?

The attractive maintenance workspace is the starting point, not the complete product. The feature branch was rechecked at `59bfb037ffa2c3b51f96c2f665029c1e7dab44d0`. The previous review records a tested maintenance addon and local deployment, not tenant hosting, platform integrations or the wider processes below. [S15, S16]

Everything labelled **Design** below is a proposed product control. Public-source observations describe the source's stated requirements, not a claim that every circular, franchise amendment and exception has been found. A Dubai transport compliance specialist/operator should confirm the applicable requirements before real-customer use.

## 2. Research findings that change the design

### A. Rental and limousine operations are not interchangeable

**Source observation:** RTA's car-rental activity card covers rentals without drivers for at least one day. It distinguishes that activity from hourly rental and luxury passenger transport. The card also addresses insurance, TARS and approved tracking. [S01]

**Design:** maintain four separate concepts: licensed activity, operating company, vehicle-use mode, and distribution channel. “Uber,” “Careem” and a rental marketplace are channels/products, not substitutes for a legal activity permit. A customer may manage multiple legal entities inside its own tenant, but that never authorizes unrestricted vehicle/driver transfer between them.

### B. Company authorization comes before a fleet dashboard

**Source observation:** RTA's setup FAQ describes a luxury-transport contracting process after trade licensing/traffic-file creation, followed by vehicle and driver registration. Its TARS activation FAQ requires a traffic file and activity permit. [S02] Corporate vehicle registration includes a specific luxury/franchise pathway. [S06]

**Design:** company onboarding captures trade licence, activity permissions, traffic file, relevant contract/franchise evidence, authorized representatives and renewal tasks. An uploaded licence is initially “pending verification,” not automatically valid. Record external application references and issued evidence separately from internal tasks.

### C. Drivers need their own compliance lifecycle

**Source observation:** RTA's taxi/luxury driver service describes training/testing and permit issuance, a one-year permit, a renewal window starting 30 days before expiry, identity/clearance/fitness-related evidence and service restricted to the company under which the driver is registered. [S03] Uber's Dubai requirements additionally specify matching employer details across its required records. [S04]

**Design:** a driver is not an Odoo workshop technician. Track employer, licence, professional permit, permitted category, platform enrolments, availability and document verification. Store only a fitness-clearance status/reference/expiry where sufficient—not medical diagnoses or psychological report contents in dispatch screens. Changes of employer need a fresh authorization review; multiple app accounts do not imply multiple lawful employers.

### D. Each channel has a separate eligibility decision

**Source observation:** Uber distinguishes Dubai limousine eligibility from other emirates, limits acceptance to the registered city, and publishes product-specific vehicle conditions that can change. [S05] Careem's public Captain overview supplies general onboarding information, but the complete current Dubai limousine fleet checklist was not established in this research. [S12]

**Design:** record city, platform product, vehicle/driver external IDs, approval evidence, status, verification time and next review. A valid RTA document does not by itself establish Uber/Careem acceptance. Careem-specific unknowns must stay “Needs review”; do not copy Uber's rules into a Careem profile. Software branding is separate from restrictions on physical vehicle branding.

### E. Vehicle age requires the correct category and date basis

**Source observation:** S01 differentiates replacement limits. New ordinary-category/EV rental vehicles are described with four/six years from registration; used/imported equivalents use manufacture date. Approved-list elite/luxury rental categories have ten/seven-year replacement limits with corresponding new-versus-used date bases. Separate admission/registration rules also appear in the card. [S01]

**Design:** retain manufacture date, date precision, model year, first registration, acquisition/source type, powertrain, official category evidence and any individually approved retirement/extension date. Do not infer a manufacture day from model year. Do not identify an official luxury category from price or badge. “Vehicle age,” “eligible to enter this activity,” “must leave this activity,” and “accepted by this platform” are different calculations.

The English card's wording and entry-date rules need clarification before automatic enforcement. Limousine-specific retirement rules and current eligible-model lists were not comprehensively verified. No generic four-, five- or seven-year rule should be applied to all cars. Unknown classification or policy applicability produces **Needs review**, not green.

### F. Renewals and extensions are real workflows

**Source observation:** RTA offers a commercial-lifespan extension process involving inspection and approval. Its generic code-5 wording mentions a maximum number of extensions, but does not reconcile every category in S01. [S08] RTA separately states that a technical inspection certificate is valid for 30 days. [S07]

**Design:** track prepare → appointment → inspected → submitted → approved/rejected → issued evidence. A request or passed internal workshop checklist does not extend legal validity. Use the authority-issued end date; never grant automatic extra years. Distinguish an inspection report's transaction-validity window from current registration validity and the next required inspection.

### G. Takamul is a controlled temporary pathway, not a switch

**Source observation:** RTA's current FAQ describes common-member eligibility, the rental company's response within 24 hours, payment and an issued permit valid for 30 days. [S02] Its official announcement describes the rental/luxury collaboration. [S11]

**Design:** use an authorization record linking lender, operator, exact vehicle, agreement, verified relationship evidence and actual issued start/end. Application, counterparty approval, payment and active permit are different states. Pending or expired authorization cannot enable an allocation. Platform and driver requirements still apply. Do not treat Takamul as automatic approval to operate on Uber or Careem, or assume the prior 2023 terms are current.

### H. External systems remain external authorities

**Source observation:** TARS was introduced to digitize rental contracts; current RTA material still references its use. [S10, S01, S02] SIRA describes Secure Path as a tracking/fleet service. [S09] Uber publishes supplier-integration documentation, but production access has not been established for this project. [S13]

**Design:** start with verified manual records and authorized file imports. Keep official submission state/reference distinct from FleetFlow state. No stored customer portal passwords, scraping behind logins, invented API endpoints, or fictional “live” badges. A map cannot certify tracking compliance. Treat Salik's current official rate page as a verification pointer, not a hardcoded rate source; direct retrieval was blocked. [S14]

## 3. End-to-end operating processes

The following workflows are proposed operating designs derived from the distinctions above. They are not claims that FleetFlow already performs them.

| Process | Responsible role | Proposed workflow and operational output |
|---|---|---|
| Establish an operator | Customer administrator + compliance reviewer | Create legal company, activity profile, traffic-file/contract evidence, permitted operating modes and renewal owners. Unverified permissions remain unavailable for allocation. |
| Acquire/onboard a car | Fleet manager + compliance reviewer | Record VIN and plate history; ownership/lease; manufacture/registration/source; official category; registration, insurance/use scope, inspection and tracking evidence; platform applications. Produce a reasoned readiness result. |
| Recruit/onboard a driver | Driver administrator + compliance reviewer | Record identity reference and employer, licence and permit scope, approval evidence and training/renewal tasks. Link platform accounts only after review. Produce an eligible-driver list, not an automatic government permit. |
| Plan shifts | Dispatcher | Pick company, time window, mode, vehicle, driver and intended channels. Check eligibility for the whole interval, resource conflicts, maintenance and custody. Confirm atomically or explain blockers. |
| Hand over a vehicle | Dispatcher + driver | Record actual custody, odometer, fuel/charge, timestamp, photos, defects and acknowledgement. Recheck before checkout. A refused handover stays blocked and creates an exception. |
| Operate through apps | Driver + dispatcher | Record approved channel assignment; later import activity/earnings with freshness markers. One driver's compatible channel enrolments may coexist, but the same driver/car cannot have two conflicting physical allocations. |
| Rent without a driver | Rental agent | Validate renter/authorized-driver eligibility using the confirmed rental profile; quote/reserve; agreement and deposit workflow; official contract-registration state; checkout; extension or swap; return; settlement and refund. |
| Service/repair a car | Driver + workshop + fleet manager | Report defect; set hold; diagnose/estimate; approve; repair; inspect; resolve the appropriate hold; re-evaluate dispatch readiness. Existing FleetFlow work orders are reused. |
| Manage an accident | Driver + dispatcher + claims handler | Record safe incident notification, linked custody, police/insurer references and evidence; immobilization/replacement workflow; repair and claim tracking. Record official liability decisions, do not infer fault. |
| Renew permission | Compliance reviewer | Due queue, owner, required evidence, appointment/application, outcome, new document version, recheck of upcoming/live allocations. Pending renewal is not renewed. |
| Reconcile operations | Finance operator | Import statements, validate matching keys, map trips/costs, review exceptions, reconcile payouts and cash, approve driver/renter settlements, retain source lineage. |
| Replace/retire a car | Fleet manager + finance + compliance | Forecast official end-of-use and costs; compare documented scenarios; approve replacement, remove channel authorizations, settle leases/contracts, reconcile disposal and preserve history. |

### Custody and availability must be real

A future reservation, driver shift and vehicle physically out with a renter are not the same state. A planned end time does not prove a return. Late returns continue to block checkout, even when the original reservation interval has ended. Future bookings can be planned conditionally, but cannot be handed over while custody is unresolved.

Use a unified resource-calendar service for exclusive vehicle/driver reservations. Check both resources in one transaction. A driver may use multiple approved apps during one compatible shift; do not model each app login as a separate overlapping physical booking. A confirmed direct chauffeur job conflicts with the relevant busy interval, not automatically with every app enrolment.

Shifts/rest thresholds are configurable operator policies pending verified applicable rules. Never encourage excessive driving with productivity targets or equate online hours with safe/paid working hours.

### Rental workflow must not become a misleading booking screen

Internal booking lifecycle: enquiry → quote → provisional reservation → confirmed reservation → checkout → active → return inspection → settlement → closed; cancellation/no-show/dispute are explicit branches. A vehicle swap closes the old custody segment and opens a new one; it does not rewrite history. An extension rechecks availability, documents, insurance and official-contract requirements.

Record renter, permitted additional drivers, document review and relevant insurance eligibility separately from employed limousine drivers. Non-resident licence eligibility requires its own confirmed rules. Do not apply an employee professional-permit rule to every tourist renter. A deposit is not earned revenue; refund and disputed charge decisions require their own permissions and audit trail.

Official TARS lifecycle: not submitted → operator reports submission → accepted/rejected → amended/closed as evidenced by the authority. Store reference and evidence. Do not label an internal signature as a verified statutory e-signature or a successful TARS submission.

## 4. Proposed functional architecture

### Vehicle and driver records

Extend `fleet.vehicle` rather than duplicating it. Map existing Odoo fields first, because acquisition date is not necessarily first registration. Keep plate identifiers as strings and preserve emirate, plate category/code and history. VIN is the durable matching key where available; missing/duplicate VIN needs controlled resolution.

Create a separate driver record with an optional link to an application user; many drivers initially need no paid/privileged staff login. Private documents do not belong on a globally visible contact or public attachment. Keep employer changes effective-dated and keep operational identity separate from medical, identity and HR evidence.

### Evidence and rule catalog

Evidence records identify their subject, operating company, document type, issuer/reference, validity bounds, review state, reviewer and source attachment. Superseding a document retains the old version and re-evaluates affected future work. Store who verified what, not just a user-editable green checkbox.

Rules have jurisdiction, activity/product, applicable subject/category, effective dates, source/version, verification owner, status and severity. Publish only bounded predicates, such as “required document valid for interval,” “operator identity matches,” or “approved retirement date not exceeded.” Never evaluate user-supplied Python/JavaScript/SQL. Draft research rules cannot silently count as satisfied or simply disappear from a readiness profile.

Separate policy publication from evidence verification. For uncertain age rules, use an individually documented authorized date or a reviewed policy; otherwise require review. Preserve the policy/evidence snapshot behind every confirmed allocation while separately re-evaluating current readiness after changes.

### Readiness output

Inputs: company + vehicle + driver/renter context + mode + channel/product + requested interval.

Output: **Ready / Warning / Blocked / Needs review**, with rule IDs, reason codes, non-sensitive explanation, next action, evidence references and evaluation time. Known-invalid requirements produce Blocked; missing/ambiguous mandatory evidence produces Needs review. Both prevent confirmation and checkout. Warnings are only for explicitly non-blocking conditions, such as a later renewal outside the requested period, and require acknowledgement when configured.

The dispatch board should say “Driver permit expires during this shift; shorten the allocation or verify the renewed permit,” not show an unexplained red dot. A stale platform verification must be labelled stale. “Ready” means the reviewed profile passes using the available evidence, not that RTA or a platform has issued a new clearance.

When validity changes during an active shift, flag the allocation, notify the responsible dispatcher and record a response/replacement task. The system cannot physically stop a car or remotely deactivate an external app without an actual authorized integration.

### Maintenance and age planning

Add preventive plans by manufacturer/operator-approved calendar and/or kilometre thresholds, whichever is reached first. Each plan has a service baseline and provenance; no universal service interval is invented. Odometer readings include time, origin, units and correction history. Missing/stale readings create uncertainty; meter replacement uses a documented adjustment, not deletion of prior readings.

Generate one work order per due occurrence, even under retry or concurrent scheduler runs. Separate “service due,” “car blocked from dispatch,” and “work completed.” Repairing one fault does not clear other holds; a cancelled job does not prove the vehicle safe. For each hold record cause, scope, source, authority to clear, timestamps and evidence.

A replacement board should combine confirmed end-of-use date, upcoming authorizations, workshop downtime, mileage and documented operating costs. Its recommendation is a scenario, not an automatically executed sale or a guarantee of resale value.

### Revenue and cost reconciliation

Use normalized source imports with provider/account IDs, stable external references, trip/statement periods, currency, vehicle/driver identifiers, earning components, deductions, toll reimbursements, cash collections and payout lines. Preserve the original file and import mapping version under restricted access. Never add statement totals and their underlying trip lines together.

Re-importing the same source is idempotent. Overlapping exports, corrections and refunds need version/adjustment handling, not blind deduplication by date and amount. Unmatched vehicle IDs, switched cars, shared names and totals-only files go to an exception queue; do not silently allocate money to a convenient driver.

Proposed reports separate gross activity, platform deductions, cash collected, settled payout and operating contribution. Treat depreciation, financing interest, loan principal, tax, customer deposits and pass-through reimbursements distinctly; obtain accountant sign-off on classifications. Missing expenses must visibly qualify the result as partial, not “net profit.” No automated payroll deduction or fine assignment without reviewed contracts, attribution and authorization.

Salik/parking/fines/charging/fuel inputs match a timestamp to plate history and actual custody. This creates a proposed attribution for review, not automatic legal liability. A toll refunded through an app must not be treated as new trip income and then counted again in the payout.

## 5. User journeys and screens worth building

**Dispatcher — Today:** eligible cars and drivers; actual custody; planned/current shifts; expiring permissions; blocked assignments; replacement actions. Main actions are check readiness, assign, check out, return, record defect and arrange replacement.

**Driver — My shift:** assigned car, approved channels, pickup instructions, checklist/odometer capture, report defect, acknowledge return. Show only their own assignments and permitted data; no fleet finance or colleagues' documents.

**Fleet/workshop — Vehicle:** full timeline of custody, inspections, maintenance, holds, mileage and eligibility. Main actions are create work order, record diagnosis, authorize cost and clear a specific resolved hold.

**Compliance — Renewals:** evidence gaps, deadlines, applications, rejected items and source review dates. Main actions are verify, reject, supersede, arrange an appointment and recheck affected work.

**Rental agent — Reservations and returns:** capacity, agreement, official-registration status, deposits, additional drivers, swaps, late return, damage evidence and settlement exception queue.

**Owner/finance — Performance:** utilization with defined denominators, downtime, reconciled earnings, operating contribution, outstanding cash, renewal exposure and replacement scenarios. Every number has drill-through, period, source coverage and as-of timestamp.

**UI rule:** preserve the current visual identity. Do not spend the first build reskinning generic Odoo, adding decorative charts or faking live telemetry. Mobile operational tasks, errors and server-enforced next steps come first.

## 6. Delivery sequence and the first build

This introduces an operations workstream alongside the existing phased/hosted plan. It supersedes the old maintenance-only product boundary, but does not relax security or launch gates.

| Increment | Business result | Scope boundary |
|---|---|---|
| OPS-1 — Resource readiness and allocation | Staff can register a vehicle/driver, verify evidence, see eligibility and confirm/check out a non-conflicting shift, including maintenance blocks. | Actual next implementation. Local synthetic data; manual platform status; no financial or government API. |
| OPS-2 — Workshop, handover and incident loop | Full pre/post checks, preventive maintenance by time/km, incidents, replacement and controlled hold release. | Reuses the existing work-order lifecycle; no roadworthiness certification. |
| OPS-3 — Rental lifecycle and TARS tracking | Reservation, renter/additional-driver review, agreement, custody, extensions/swaps, returns, deposits and official status evidence. | Manual official-system handoff until approved integration exists. |
| OPS-4 — Statements, costs and settlements | Idempotent imports, matching exceptions, cash/payout reconciliation and qualified contribution reporting. | Start with one verified operator export format; no invented schemas presented as real provider files. |
| OPS-5 — Lifecycle and compliance depth | Validated category rules, renewal/extension workflows, versioned source updates and replacement forecasts. | OPS-1 already uses explicit expiry/retirement dates; this adds researched category automation and wider renewals. |
| HOST workstream — Customer service delivery | Separate tenants, safe routing, branding, optional addons, recovery, onboarding and subscription lifecycle. | All relevant TEN-01…06 gates before real hosting; local multi-company tests do not satisfy tenant-isolation tests. |

**First useful demonstration:** an eligible driver/vehicle shift confirms; an incompatible operator, missing platform approval, expired document, overlapping allocation or active maintenance hold prevents it and explains why. Adding verified renewal evidence changes the decision. A later return does not magically clear custody. This should be a working product flow, not merely a new requirements document.

### Existing foundation work is retained

Read the earlier review, not just the current README. Correct the unsafe evaluation-user helper, server/browser cutoff inconsistency and misleading status documents as appropriate. Keep existing tests. Add concurrent-resource tests. Record the unresolved runtime-version/patch policy; do not silently migrate major versions. Local development may remain on the current compatible baseline, but that is not production approval. [S16]

Hosted design remains one runtime, database, filestore and secret set per customer. Ensure explicit cross-database connection restrictions, not just different database owners; never mount a directory containing all customers' secrets into each runtime. Tenant branding is configurable and sanitized; customer-specific addons deploy only to the relevant tenant. Owner-assisted and automatic onboarding eventually use the same provisioning path. These are requirements, not implemented claims. [S16]

## 7. Evidence still needed before a real pilot

Obtain redacted examples through the intended fleet operator, without blocking synthetic development: actual activity permits and franchise terms; vehicle categories/approved models and retirement/extension records; driver onboarding/renewal and employer evidence; Careem Dubai product approval requirements; insurance-use restrictions; current TARS/Takamul terms; approved tracking certificate; a representative Uber/Careem/rental export and toll statement; service schedules and odometer sources; shift/rest, incident and settlement policies.

Confirm data handling, retention, operator support access and jurisdictional privacy obligations with the appropriate adviser. No universal retention duration, payroll deduction policy, tax treatment, regulatory grace period, limo age cutoff or platform API entitlement is assumed here. A public-page refresh date is not the effective date of a regulation.

## 8. Source register

`SOURCE_REGISTER.json` contains URLs, retrieval date, inspected sections and limitations. The concise references below can be followed by the implementer. Statements linked to these sources are observations; screens, model structures and safeguards above are our proposed design.

**[S01] RTA — Car Rental activity description card.** Not shown in the document inspected. Pages 1–3; activity scope, operating conditions, replacement and registration controls.
https://www.rta.ae/wps/wcm/connect/rta/c89901f3-cc12-4223-a601-0b09ba16bd33/Car-Rental-en.pdf?MOD=AJPERES
Limitation: Public undated activity card, not a complete consolidated legal opinion. English wording and category/date applicability need operator/RTA confirmation.

**[S02] RTA — NOC for a New Trade Licence — activity setup and TARS/Takamul FAQs.** Page update: 2026-06-04. FAQs 1, 2 and 7.
https://www.rta.ae/wps/portal/rta/ae/home/rta-services/service-details?serviceId=496
Limitation: Confirm the issued permit conditions and current portal terms; the page does not establish platform acceptance.

**[S03] RTA — Request or Renew a Professional Driver Permit — Taxi or Luxury Vehicle Driver.** Search result page update: 2026-08-07. Output; new/renewal steps; Important to Know; Service Requirements; FAQs.
https://www.rta.ae/wps/portal/rta/ae/home/rta-services/service-details?serviceId=629
Limitation: Taxi/luxury permit category only. Not the separate tourist, bus or delivery category. Obtain current employer/permit evidence and review exceptional cases.

**[S04] Uber — Driver requirements in the UAE.** Undated public page. Dubai driver documentation and matching employer details.
https://www.uber.com/ae/en/drive/requirements/
Limitation: Do not import Abu Dhabi or Sharjah rules into Dubai; platform confirmation for each driver remains necessary.

**[S05] Uber — Vehicle requirements in the UAE.** Undated public page. Dubai expatriates; registered city; product-specific vehicle eligibility.
https://www.uber.com/ae/en/drive/requirements/vehicle-requirements/
Limitation: Requirements can change; accepted-model/category lists and operator approval matter. The Abu Dhabi five-year wording is NOT a general Dubai cutoff.

**[S06] RTA — Register a New Vehicle — corporate / luxury vehicle process.** Page update: 2026-09-03. Corporate and luxury-vehicle registration process, franchise prerequisites, insurance and inspection.
https://www.rta.ae/wps/portal/rta/ae/home/rta-services/service-details?serviceId=519
Limitation: Activity-specific prerequisites differ. The term extended vehicle can mean stretched bodywork, not a lifespan extension.

**[S07] RTA — Renew Vehicle Ownership — corporate.** Undated in excerpt used. Renewal process; FAQ on Technical Inspection Certificate validity.
https://www.rta.ae/wps/portal/rta/ae/home/rta-services/service-details?serviceId=586
Limitation: Certificate validity for a renewal transaction is not the same as the vehicle registration expiry or next inspection due date.

**[S08] RTA — Lifespan Extension for Commercial Vehicles.** Undated in excerpt used. Steps and Important to Know.
https://rta.ae/wps/portal/rta/ae/home/rta-services/service-details?serviceId=589
Limitation: Generic code-5/four-year wording must be reconciled with differentiated category rules in S01. No blanket extension should be granted by software.

**[S09] SIRA — Secure Path.** Undated public page. Service overview.
https://www.sira.gov.ae/en/more/security%20partners%20servicres/secure-path
Limitation: A FleetFlow map or third-party GPS device is not proof of the required approved tracking installation.

**[S10] Government of Dubai Media Office / RTA — RTA launches online Transportation Activities Rental System.** 2021-10-30. Rental contract digitisation and system launch.
https://mediaoffice.ae/en/news/2021/October/30-10/RTA-launches-online-Transportation-Activities-Rental-System
Limitation: Historical process context, not proof of present API access. Current activity/activation evidence is S01/S02.

**[S11] RTA — Introducing Takamul permit to enhance integration between luxury transport and car rental sectors.** 2025-03-07. Temporary collaboration and common-member requirement.
https://www.rta.ae/wps/portal/rta/ae/home/news-and-media/all-news/NewsDetails/introducing-takamul-permit-to-enhance-integration-between-luxury-transport-and-car-rental-sectors
Limitation: Use current S02 and the actual issued permit for operative dates, not an inferred rolling monthly permission.

**[S12] Careem — Become a Captain.** Undated public page. Onboarding overview and general document list.
https://www.careem.com/en-AE/captains/
Limitation: Does not establish a complete Dubai limousine fleet checklist or an accessible fleet integration API. Confirm city/product-specific terms with the operator and Careem.

**[S13] Uber Developers — Supplier Platform introduction and getting started.** Undated public developer pages. High-level supplier integration capabilities and onboarding.
https://developer.uber.com/docs/vehicles/introduction
https://developer.uber.com/docs/vehicles/getting-started
Limitation: Pages warn the design is under development and contain access/confidentiality notices. No endpoint specifications reproduced here; do not assume the customer has production scopes or Dubai access.

**[S14] Salik — Variable Toll Rates.** Current search result; full page not retrieved. Official rate-page search result.
https://www.salik.ae/en/Toll-Gates/variable-toll-rates
Limitation: Use as a pointer only. No tax or exact price is implemented from a snippet. Import official transaction amounts and verify current tariff/tax treatment separately.

**[S15] GitHub / project repository — Current FleetFlow branch and code.** Branch rechecked: 2026-09-21. Feature branch; custom_addons/fleetflow; fleetflow deployment and tenant documents.
https://github.com/Colonel94/odoo/tree/59bfb037ffa2c3b51f96c2f665029c1e7dab44d0
https://api.github.com/repos/Colonel94/odoo/branches?per_page=100
Limitation: Current task did not rerun Odoo or CI. Prior detailed source/CI review remains the baseline; recheck before implementing.

**[S16] Prior FleetFlow review supplied in this conversation — GitHub review and Claude prompt.** 2026-09-21. Companion file fleetflow-github-review-and-claude-prompt.md; findings R1–R6.
https://github.com/Colonel94/odoo/pull/1
Limitation: Historical execution evidence, not a new runtime test. Preserve fixes, test gaps and unresolved baseline decision.
