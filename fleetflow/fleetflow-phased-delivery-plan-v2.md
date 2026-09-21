# FleetFlow — Phased Delivery Plan

**Planning baseline:** 20 September 2026  
**Revision 2:** 21 September 2026 — hosted subscription decisions integrated  
**Product:** Fleet maintenance workflows for rental and commercial transport operators  
**Repository:** `Colonel94/odoo`  
**Starting package:** `fleetflow-source.zip`  
**Status:** Proposed roadmap. No phase is marked complete by this plan.

## 1. Product objective

Build a focused operational platform in which a dispatcher, technician and operations manager can move a vehicle issue from intake to an attributable release decision, without maintaining a parallel spreadsheet for the same job.

The commercial product is a monthly subscription always hosted by Omar, with both automatic standard onboarding and owner-assisted setup/customization. Customers access it through a browser and do not install or operate servers. The first development checkpoint remains one operator/workshop using synthetic data; that local checkpoint is not a hosted launch. A real-customer pilot must meet the tenant-isolation, branding, access and recovery gates below. Rental booking, a general-purpose workflow designer and regulatory certification remain outside the initial scope. [S3]

### Hosted-customer requirements carried into every review

The revised handoff defines **TEN-01** separate runtimes/databases/filestores/credentials; **TEN-02** individual branding and trusted host routing; **TEN-03** one standard core with customer-only addons; **TEN-04** automatic and manual onboarding using one provisioning process; **TEN-05** per-customer operation/recovery; and **TEN-06** two-tenant acceptance evidence. Read the full requirements in `fleetflow-claude-handoff-v2.md` and execute the review using `fleetflow-claude-next-review.md`.

Architecture belongs in Phase 0, two-tenant scaffolding in Phase 1, branding in Phase 2, customer-isolation/recovery launch gates in Phase 6, and both onboarding entry points in Phase 7. A manually onboarded hosted pilot may precede complete automatic signup/billing only after the common isolation, branding, access and recovery controls pass. Do not defer those controls to the first automated-signup release. The second tenant used for testing must be a separate environment, not merely another company in the same database.

These are requirements, not completed features. This documentation revision changes no source code or recorded test status.

### Starting point and evidence

The supplied handoff records an initial Odoo Community 16 addon, local deployment utilities and a design preview. It records structural checks, but not a successful Odoo installation, database-backed test run or live application browser validation. It also records that branch creation succeeded while the source upload did not. Treat those as the last recorded status, not a fresh inspection of GitHub. [S1]

The handoff explicitly identifies independent inspection, supported-core migration, concurrency testing and deployment validation as decisions or unfinished work. Preserve the implementation as a starting point; do not mistake the standalone HTML preview for the application. [S1]

### Planning assumptions

- Preserve unrelated work and Odoo core; keep custom behavior in addons and deployment utilities.
- Use Community-compatible dependencies. Require no paid APIs, Enterprise modules or external runtime fonts/CDNs.
- Use existing local infrastructure for development. Hardware capacity, power, storage, backups and existing subscriptions are not included in a claim of zero operating cost.
- Require explicit approval for a major-version change, public deployment, real operational data and paid services.
- Begin with synthetic data and ordinary test accounts. Administrator access is not a substitute for permission testing.
- Pilot scope assumption: one operator, one workshop, three primary roles. This is a product boundary, not demonstrated system capacity.
- Progress is controlled by evidence and acceptance gates, not dates or optimistic completion percentages.

## 2. Delivery overview

| Phase | Outcome | Main deliverables | Exit gate |
|---|---|---|---|
| 0 — Recover and verify | A reproducible development baseline and hosted architecture | Package applied safely, baseline results, version decision, TEN-01..06 gap matrix and tenancy ADR | Source is reproducible; blockers documented; runtime and hosting architecture decisions reviewed |
| 1 — Establish the maintained foundation | A live addon with two isolated local tenant fixtures | Compatible runtime, automated tests, role accounts, per-tenant runtime/database/filestore scaffolding | Lifecycle and workflow pass; tenant credentials and mounts do not cross boundaries |
| 2 — Complete the real UI/UX | A coherent branded customer workspace | Role screens, responsive views, accessible interactions, tenant branding before/after login | Real tasks succeed; each hostname displays only its own identity and assets |
| 3 — Complete workshop operations | A controlled operational MVP | Dispatch conflicts, maintenance holds, evidence, revision/rework rules, inspection policy | Happy paths and exceptions pass, including permissions and concurrent actions |
| 4 — Add repeatable workflows | A configurable fleet-workflow release | Versioned templates, SLA rules, preventive scheduling, deduplicated notifications | Configuration cannot bypass controls; repeated jobs and retries do not create duplicate effects |
| 5 — Add cost and performance visibility | A management release | Cost lines, timestamps, defined KPIs, reports and exports | Reports reconcile to underlying records and respect company/currency boundaries |
| 6 — Harden and run a controlled pilot | A reviewed hosted-pilot release | Two-tenant isolation tests, independent restore, monitored updates, operator acceptance | No isolation blockers; recovery works without affecting another tenant; operator accepts |
| 7 — Deliver subscription onboarding | An owner-hosted monthly product with two signup paths | Standard signup, assisted setup, one provisioning workflow, branding, tenant addon manifests | Both onboarding routes create isolated tenants; tested subscription/access lifecycle; no customer server installation |

**Dependency sequence:** 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7.

**First practical checkpoint:** phases 0–3 produce the local operational MVP. Perform an internal usability review then, before expanding scope. Do not confuse that checkpoint with permission to use the platform as the sole real-world fleet control.

A small controlled operational pilot can be brought forward after phase 3 only if the relevant phase 6 security, recovery and operator-acceptance requirements are completed first. Automation and advanced reports are not prerequisites for a useful pilot.

## 3. Phase 0 — Recover the source and verify the baseline

**Goal:** establish what actually exists and prevent additional development on an unverified foundation.

### Work packages

**P0.1 — Safely apply the source.** Inspect the local checkout and remote branch. Preserve unrelated changes. Locate `feat/fleetflow-workflow-platform` or create an explicitly named local working branch. Compare the ZIP contents before applying them. Do not overwrite Odoo core files.

**P0.2 — Validate the development setup.** Inspect the compose file, scripts, dependency versions, environment variables and secret exclusions. Confirm which Odoo code executes: the repository checkout or code bundled in an image. Do not assume a container with a matching major-version label guarantees compatibility.

**P0.3 — Attempt baseline tests.** Run the supplied structural and integration commands in a disposable local environment. Record exact commands, versions and results. Classify failures into environment, core compatibility, addon installation, frontend assets, permissions or workflow logic. Preserve failing evidence rather than weakening tests.

**P0.4 — Approve the version decision.** Odoo publishes a three-year standard-support lifecycle. [S2] Assess the old 16.0 starting point against a maintained stable Community release. My proposed direction is to move the addon to an agreed maintained baseline before substantial feature expansion. This is a separately reviewed change, not a silent upgrade or a claim that the existing addon is already compatible.

With synthetic data only, prefer a clean development database for the new baseline. If any real data exists, preserve it and define a separate migration/reconciliation task before proceeding. Do not reuse an older database against a newer major version without a validated migration path.

**P0.5 — Review hosted-customer architecture.** Inspect the actual code and configuration against TEN-01..TEN-06; classify each requirement with evidence and blockers. Design the trusted hostname-to-runtime-to-database mapping, per-tenant storage/secrets/backups, standard-versus-custom addon deployment, operator privileges and common onboarding lifecycle. Do not assume existing multi-company rules establish tenant isolation. Record the agreed monthly owner-hosted model; do not reopen customer self-hosting as the default distribution decision.

### Deliverables

`BASELINE_REPORT.md`, an architecture/version decision record, `ADR-HOSTED-TENANCY.md`, `TENANT_REQUIREMENTS_MATRIX.md`, a defect list and a reviewable source application diff. Reports should not contain credentials or personal data.

### Exit gate

The source can be reproduced from known files, environment dependencies are documented, test failures are visible, and the version decision is approved. Phase 0 may finish with runtime blockers only when those blockers are explicitly assigned to phase 1; it does not earn a “working application” label.

## 4. Phase 1 — Establish the maintained, running foundation

**Goal:** make the actual platform install and run reliably on the approved baseline.

### Work packages

**P1.1 — Port and fix compatibility.** Keep a separate port commit/PR. Update the addon manifest, server APIs, view definitions, Owl components, assets and deployment utilities as needed. Keep the old prototype recoverable. Do not rewrite the full Odoo repository or mix broad new features into the port.

**P1.2 — Verify lifecycle operations.** Test a fresh database, initial module install, server restart and module update. Record reproducible core and runtime versions, including image digests or equivalent reproducible dependency references, with a procedure to refresh them for security fixes.

**P1.3 — Establish continuous verification.** Run the supplied integration suite, then add missing regressions discovered during installation. Exercise normal users in all three roles and a second company. Keep test data and test-volume deletion isolated from working data.

**P1.4 — Verify the live frontend.** Compile and run the actual backend assets. Open the workspace and every linked screen in a browser; investigate console and server errors. Test both ordinary bundled assets and the relevant development asset mode.

**P1.5 — Establish two-tenant local scaffolding.** Add reproducible configurations for two separate synthetic customer runtimes, databases, filestores and restricted credentials. Use distinct local test hostnames and isolated session/storage boundaries. Keep privileged provisioning outside tenant runtimes. Verify database access denial and volume/secret separation. Record deployment versions and allowed addons. This is local validation infrastructure, not permission to publish the service.

### Deliverables

Working development environment, versioned addon, successful test logs, ordinary role accounts in the test database and an updated setup guide.

### Exit gate

From a clean setup, a dispatcher creates an order, a manager approves it, a technician performs and submits the work, and a manager releases it. Restart preserves the order. A module update succeeds. Unauthorized and cross-company operations are rejected. No unresolved installation or critical frontend errors remain.

## 5. Phase 2 — Complete the real UI/UX

**Goal:** make FleetFlow feel like a focused workshop application rather than a collection of disconnected Odoo screens.

### Work packages

**P2.1 — Role-specific starting screens.** Give dispatchers an intake/assignment queue, technicians “My work,” and managers approval/release exceptions. Make available actions depend on the user's actual permissions and the record state.

**P2.2 — Consistent workspace.** Apply the approved typography, spacing, status labels, navigation, buttons, forms and tables across FleetFlow-owned screens. Keep styles scoped so unrelated Odoo apps remain usable. Treat global navigation changes as a separately reviewed change, not a blanket CSS override.

**P2.3 — Guided task flows.** Make new intake short, with advanced planning details progressively disclosed. Show the current stage, next action, responsible person and missing prerequisites. Explain blocked actions clearly. Warn before discarding unsaved changes; guard against accidental duplicate submissions.

**P2.4 — Responsive and accessible operation.** Test live Odoo at 390 px and 1440 px widths, keyboard-only operation, visible focus, readable contrast, labelled fields and touch interactions. Status must not rely on color alone. Provide meaningful loading, empty, error, retry and success states. Do not add offline claims without an offline design and tests.

**P2.5 — Data-connected interaction.** Ensure each dashboard card opens the exact matching filtered records. Cover no records, no matching filters, insufficient permission, failed requests and stale records changed by another user.

**P2.6 — Add customer branding.** Implement tenant-local logo, name and validated theme settings for login, workspace and reports, plus email templates when enabled. Resolve identity before login from trusted hostname/environment routing. Give editing rights only to authorized customer admins/platform operators. Test both tenant identities, browser sessions, cached assets and report output without leakage. Customer-owned domains may be deferred; isolated customer subdomains are the baseline.

### Deliverables

Live application screenshots, a screen inventory, a small reusable UI specification and browser acceptance results. The original design preview remains reference material, not test evidence.

### Exit gate

All main tasks are possible without dead-end navigation, misleading controls, page-level horizontal overflow or critical accessibility defects. Metrics agree with the lists they open. All key flows work in real user sessions, not just as the administrator.

## 6. Phase 3 — Complete workshop operations

**Goal:** deliver the minimum coherent maintenance operation, including exceptions.

### Work packages

**P3.1 — Dispatch and conflicts.** Define technician availability, scheduled job duration and capacity. Block incompatible overlaps in the server, not just in the calendar. Use half-open time intervals so back-to-back jobs are allowed. Define the policy for multiple jobs on one vehicle; do not arbitrarily forbid legitimate parallel work.

**P3.2 — Maintenance holds and availability.** Add an explicit maintenance hold independent of workflow stage. Define who can place and clear it and when it takes effect. A vehicle with multiple unresolved blocking jobs must not become available merely because one job was released or cancelled. Clear holds only through the approved policy and record the decision. Do not describe this as an integration with an unbuilt rental dispatch system.

**P3.3 — Evidence and history.** Capture required photos/documents, diagnosis, work performed and inspection evidence. Validate attachment permissions, size limits and allowed types. Record transition events, actual start/completion timestamps and the due-date value used for performance reporting. Protect historical evidence from ordinary editing; distinguish application-level history from tamper-proof regulatory records.

**P3.4 — Scope changes and rework.** Keep approved scope locked. Define a linked replacement-order path for changed scope; preserve cancellation/rework reasons. Rework must invalidate the relevant previous inspection checks. Closing or cancelling a job must not silently remove independent safety/maintenance holds.

**P3.5 — Inspection policy.** Replace the assumption that every job can truthfully satisfy the same checklist with reviewed checks appropriate to repair, inspection and preventive work. Required checks cannot be silently skipped. Any permitted “not applicable” answer needs a defined reason and authorization. Decide whether release must be performed by a different person from the repairer. If that mode is enabled, enforce it on the server, including dispatcher/manager role overlap. The current handoff does not claim independent inspection. [S1]

**P3.6 — Security and concurrency.** Test direct remote calls, imports, copy/create defaults, company changes, attachment access and additive roles. Run competing transition requests using independent database connections. No double release, stale-state transition or unauthorized stage change may succeed.

### Deliverables

Operational rules, updated role matrix, regression tests, dispatch/vehicle views and a scripted local demonstration covering normal work, rejection and recovery.

### Exit gate

An intake-to-release job, rejected inspection, cancelled order, approved-scope change, conflicting assignment and multi-job vehicle hold all behave as specified. Ordinary users cannot bypass the rules through direct requests. Two simultaneous actions cannot corrupt workflow history.

**Checkpoint: local operational MVP.** Review the end-to-end experience here before adding new feature families.

## 7. Phase 4 — Add repeatable, configurable workflows

**Goal:** extend a validated fixed workflow into a bounded vertical workflow platform.

### Work packages

**P4.1 — Versioned templates.** Introduce templates for corrective repair, preventive service and inspection. Allow authorized administrators to configure approved checklists, target times, routing and cost-approval thresholds within a controlled set of actions. Do not allow arbitrary Python/JavaScript evaluation or removal of mandatory controls.

**P4.2 — Preserve in-flight rules.** Snapshot the template/version and relevant policy values when an order is approved. Editing a template must not silently change the obligations or history of active and completed work. Define who can publish a new version and how existing orders are handled.

**P4.3 — Target-time tracking and escalation.** Define when each timer starts, whether calendar or working hours apply, which waiting conditions pause it, and who is notified. Start with in-app activities. Add email only after configuration, permission and failure handling are verified. Do not make external messaging a required dependency.

**P4.4 — Preventive job generation.** Schedule by date first; add odometer-based triggers only with reading validation and provenance. Record a unique schedule occurrence for each generated job. Re-running the scheduler, retries or concurrent workers must not create duplicate orders or advance a maintenance schedule prematurely. Define cancellation and catch-up behavior explicitly.

**P4.5 — Automation observability.** Keep a visible history of generated work, notifications, retries and failures. Use idempotent operations and recoverable failures. Automated actions must respect company isolation and must never issue a mechanical-safety certification.

### Deliverables

Template administration, target-time settings, preventive schedules, automation logs and scheduler/retry tests.

### Exit gate

A manager can configure a permitted workflow without changing code. An active job retains its approved template version. Replaying a scheduler occurrence creates exactly one job and does not duplicate notifications. Automation cannot skip approvals or weaken inspection requirements.

## 8. Phase 5 — Add cost and performance visibility

**Goal:** make operational performance explainable and reconcilable.

### Work packages

**P5.1 — Structured costs.** Add labor, parts and external-service cost lines with quantities, units and company currency. Separate estimated, approved and actual amounts. Define overrun approvals and an append-only correction or linked-adjustment process for posted historical values; do not simply reopen released records.

**P5.2 — Precise metrics.** Define approval waiting time, active repair time, total cycle time, overdue rate, rework rate and maintenance downtime. Specify the population, period, timezone, treatment of cancelled orders and handling of rescheduled due dates. Use the event timestamps introduced in phase 3 instead of inferring all timings from final status.

**P5.3 — Verifiable reports.** Add vehicle history, cost variance, workload and overdue reports with drill-through. Keep monetary totals grouped by company/currency unless an explicitly defined conversion policy is implemented. Exports must respect the same access rules as screens.

**P5.4 — Optional stock/purchase integration.** Keep inventory movements, purchasing, supplier billing and accounting outside the mandatory first reporting release. If approved, integrate compatible Community modules in separate work packages, with returns/cancellation tests. Do not label manually entered part costs as live stock control.

### Deliverables

Cost-entry screens, a KPI dictionary, reconciliation fixtures and permission-tested reports/exports.

### Exit gate

Known sample orders reconcile from line items to totals and reports. Every headline KPI has a definition and drill-through. Cross-company data is isolated and different currencies are not misleadingly summed. Audit corrections remain traceable.

## 9. Phase 6 — Harden and run a controlled pilot

**Goal:** test operational readiness, not just feature completeness.

### Work packages

**P6.1 — Rehearse recovery.** Back up the database, filestore and required deployment configuration. Restore into a separate environment. Verify users, orders, workflow history and attachments. Agree recovery-point and recovery-time objectives, then measure the drill against them. Test rollback around addon updates.

**P6.2 — Establish deployment safeguards.** Review secrets, authentication, least privilege, database exposure, application/database selectors, network boundaries, dependency maintenance and log redaction. Any remote deployment requires a separate reviewed configuration, encrypted transport and explicit approval; local development defaults are not production settings.

**P6.3 — Measure performance.** Proposed test fixture: 100 vehicles, 5,000 historical orders and 10 concurrent user sessions. This is a test target, not a capacity claim. Proposed target: p95 common page loads under 2 seconds on documented pilot hardware after warm-up; measure background work separately. Reassess targets if the agreed pilot differs.

**P6.4 — Monitor and operate.** Add health checks, failed-scheduler visibility, error monitoring, backup verification and a documented update process. Name an operational owner for incidents, user access and maintenance. Keep sensitive data out of support exports.

**P6.5 — Controlled acceptance.** Have the designated operator validate its own inspection/checklist policy. Use a limited agreed dataset and rollout. Initially compare results with existing operating controls rather than assuming the application is the sole source of mechanical release authority. Capture issues and repeat the acceptance scenarios after fixes.

**P6.6 — Enforce hosted launch gates.** Execute TEN-06 using two separate environments, ordinary users and customer admins. Test direct RPC/URL/database-selector bypasses, sessions, hostile host inputs, attachments, exports, database credentials, filestore/backup boundaries, background jobs and branding caches. Verify changing/upgrading/restoring one customer's instance does not alter the other. Document shared-host/operator risks. Manual onboarding is not an exception to security or recovery requirements. Any failed isolation test blocks all real-customer hosting.

### Deliverables

Restore evidence, deployment checklist, performance report, operating runbook, known limitations and pilot sign-off.

### Exit gate

Recovery and rollback succeed; critical security/workflow defects are closed; performance targets are measured; an operator accepts the process and owns ongoing operation. A named human remains responsible for actual maintenance and release decisions. This gate does not establish regulatory certification.

## 10. Phase 7 — Deliver owner-hosted subscription onboarding

**Goal:** offer monthly browser access hosted by Omar, with both standard self-service signup and owner-assisted onboarding/customization. Customers do not install or administer FleetFlow servers.

### Work packages

**P7.1 — Build one provisioning workflow.** Automatic signup and owner-assisted creation must use the same controlled service/job. Define unique tenant identity, hostname mapping, separate runtime/database/filestore/secrets, deployment manifest, setup status, health checks and activation. Make retries and concurrent requests idempotent. Clean up only resources belonging to a failed creation attempt; do not expose partially initialized environments.

**P7.2 — Standard self-service onboarding.** Guide account verification/invitation, subscription selection, branding, company/currency/timezone, roles and initial data import. Validate imports with previews, duplicate handling and per-row errors. Keep the standard path free of arbitrary code/modules. Configure real payment processing only after a provider and operating budget are explicitly approved; report any stub or manual payment step honestly.

**P7.3 — Owner-assisted customization.** Give an authorized platform operator a controlled path to create the same type of environment, apply branding and deploy reviewed customer-only addons. Track scope, versions and acceptance. Do not create an unmaintainable fork or give the customer broad host/database privileges. A manual pilot may use this path before P7.2 is complete, but it must pass the common isolation, access, branding and recovery gates first.

**P7.4 — Subscription and operational lifecycle.** Track monthly subscription/access state independently from provisioning state. Define permitted activation, renewal, payment-failure handling, suspension, reactivation and offboarding transitions. Test replayed billing events when a payment integration is introduced. Suspension must not silently delete data. Agree hosting/support costs, service commitments, retention and destructive-action approvals separately; the product decision does not authorize actual spending or live deployment.

**P7.5 — Safe evaluation and discovery.** Provide clearly fictional, isolated demo data and a guided workflow. A public interactive demo requires reviewed reset/abuse controls. Prepare industry-specific product pages and documentation for evaluation, signup and customization enquiries. Measure completed onboarding and sample workflows without promising traffic or revenue.

**P7.6 — Release and operator packaging.** Maintain deployment manifests for standard and customized tenants, release notes, compatibility requirements and per-tenant backup/update/rollback instructions. Customer documentation explains browser login, configuration and use; server installation and operation are owner responsibilities. Include clean-provisioning, both-entry-point, retry/failure and cross-tenant regression tests.

### Deliverables

Standard signup, assisted provisioning, shared provisioning implementation, subscription/access-state model, tenant-branding configuration, approved addon manifests, customer help and operator runbooks. Record any payment or automation work still missing.

### Exit gate

Both entry points create the same securely isolated environment type. Standard customers reach their own branded workspace without installing software. Customized customers receive only their approved addons. Retry/failure handling, subscription/access transitions, two-tenant negative tests and independent restore/update tests pass. Advertised features match demonstrated evidence. Obtain separate approval before public deployment, actual charges or paid resources.

## 11. Delivery controls and ownership

| Responsibility | Owner |
|---|---|
| Scope, version changes, budget and operational acceptance | Product owner: Omar |
| Implementation, migration scripts and regression tests | Assigned coding agent/developer |
| Independent review of changes and evidence | Separate reviewer/QA role |
| Inspection policy, real-world maintenance decisions and pilot use | Designated fleet/workshop operator |
| Hosting/service accountability | Omar; technical operating responsibilities must be assigned before the pilot |
| Deployment, secrets, backups, patches and incidents | Named technical operator acting for Omar before the pilot |

No role is presumed staffed merely because it appears in this table.

Each work package should have a small reviewable commit or PR containing the change, tests, upgrade/rollback notes when relevant, and a status report. Use `Not started`, `In progress`, `Blocked` or `Verified`; do not mark a phase verified because files were generated.

Every completion report should identify the commit, environment, exact test commands, results, screenshots where relevant, remaining defects and the exit criteria met. Report unexecuted tests explicitly.

A phase ends only when its gate is satisfied or the product owner explicitly changes the scope in a recorded decision. Security and data-integrity failures are blockers, not items to hide in a later polish phase.

## 12. Next review and execution brief

Use `fleetflow-claude-next-review.md` with this revised plan, `fleetflow-claude-handoff-v2.md` and the current source. Its first task is to inspect current reality, not assume the initial source upload or test status is still current.

> Review the current FleetFlow checkout and the revised handoff. Preserve Omar's decision: monthly subscriptions, always hosted by Omar, with automatic and owner-assisted onboarding. Verify existing source/tests and assess TEN-01..TEN-06. Produce `NEXT_REVIEW.md`, `TENANT_REQUIREMENTS_MATRIX.md`, `ADR-HOSTED-TENANCY.md` and a phased gap backlog. Cover separate tenant runtimes/databases/filestores/credentials, trusted routing, pre-login and application branding, customer-only addons, common provisioning, independent recovery and two-tenant negative tests. Do not pass missing or unexecuted tests. Perform only safe local review tests and documentation updates in this pass. Finish with one bounded next implementation prompt; do not execute all phases, change major version, spend money, deploy publicly, merge or delete data.

Subsequent implementation prompts must name one work package, dependency evidence, applicable TEN requirement IDs and an acceptance gate. Add a durable pointer in existing agent/project instructions without replacing unrelated content. Tenant isolation, branding, access and recovery requirements remain mandatory even for a manually onboarded pilot.

## Sources and interpretation

**[S1]** Original `fleetflow-claude-handoff.md`, supplied with this conversation; particularly Goal and current state, Apply and run, and Product constraints. Supporting package: `fleetflow-source.zip` → `fleetflow/README.md`. These establish the recorded starting status and known limitations, not new execution evidence.

**[S2]** Odoo, *Standard and extended support — Odoo 19.0 documentation*. The official search result retrieved on 20 September 2026 states that major versions receive three years of standard support, including bug fixing and security updates. Full-page retrieval timed out; exact version end dates and Community maintenance arrangements must be checked as part of Phase 0 rather than inferred here. Source address: `https://www.odoo.com/documentation/19.0/administration/standard_extended_support.html`.

**[S3]** Omar’s decisions in this conversation, incorporated on 21 September 2026: monthly charging; always owner-hosted; both automatic and assisted onboarding; separate customer data/environments; individual branding; customer-specific addons; include these in the next Claude Code review and prompt. These update the delivery model, not implementation status.

All phases, work packages, acceptance criteria, pilot sizes and performance targets above are proposed planning decisions. They are not claims that functionality has already been built, tested, deployed or commercially validated.
