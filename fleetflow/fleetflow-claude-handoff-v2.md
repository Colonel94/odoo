# FleetFlow implementation and verification handoff

**Revision 2 — 21 September 2026.** Documentation update: adds the hosted subscription, customer-isolation, branding and dual-onboarding requirements. It does not change application code or certify runtime readiness. Supersedes the original handoff on delivery-model decisions.

Use this file with `fleetflow-phased-delivery-plan-v2.md` and `fleetflow-claude-next-review.md`.

Work in the user's `Colonel94/odoo` repository. Use the provided `fleetflow-source.zip` as the starting implementation, not a new brief to redesign from scratch.

## Last recorded implementation state — verify in the next review

Build FleetFlow, an Odoo Community 16.0 workflow platform for rental/commercial-fleet maintenance. A complete first-source implementation is provided as an addon plus local deployment utilities. Its structural checks passed. Its actual Odoo runtime and database tests have not been executed. A sample-data design preview was rendered at 1440 px and 390 px without page-level horizontal overflow; that is not an Odoo browser test.

The remote branch `feat/fleetflow-workflow-platform` was created from commit `7d63cda14808a1b3e363f66a21ee133b4a41a3a6`, but the connector blocked the code upload. The earlier implementation session reported no implementation commits or pull requests. This documentation update did not recheck GitHub. Do not assume the addon is already in the repository.

## Mandatory hosted-customer requirements for the next review

**Decision recorded on 21 September 2026.** Omar will charge monthly and always host FleetFlow. Support both automatic signup/onboarding for standard customers and owner-assisted onboarding for customers who need customization. Customers receive browser access; customer-hosted installations are not the commercial delivery model. Local installations remain for development and validation.

These are target requirements and review criteria, not claims that the source package already implements them. This revision does not authorize paid infrastructure, live payment processing, public deployment, real customer-data import or execution of every phase at once.

### TEN-01 — Separate each customer's environment and data

Use one standard FleetFlow codebase, deployed as a separate Odoo runtime, database and filestore for each unrelated customer. Shared server hardware is permitted; document the shared-host trust boundary, resource limits and operator access rather than promising absolute isolation.

Give each application runtime credentials restricted to its own database. Verify actual database connection, role, ownership and privilege restrictions; distinct database names alone do not pass. Keep cross-customer provisioning privileges outside tenant application processes. Tenant runtimes must not have other tenants' volumes, secrets, database-management capabilities or host-management interfaces mounted into them. Separate backup access and restore targets too.

Do not use Odoo multi-company as the boundary between unrelated paying customers. Multiple companies inside one customer's own environment are a separate intra-customer authorization concern.

Route an allowlisted customer hostname to its assigned environment. Reject unknown or manipulated hosts rather than falling back to another customer. Configure a fixed/strict database selection for each runtime and block public database listing/management and database-selection bypasses. Validate reverse-proxy trust and session/cookie isolation. Keep databases off the public network. Check version-specific settings against the actual approved Odoo baseline.

### TEN-02 — Customer-specific branding

Provide per-customer company name, logo and validated theme colors for the login screen, FleetFlow workspace and customer-facing reports. Apply the same identity to outgoing email templates when email is enabled. Use a customer subdomain such as `alpha.example.com`; customer-owned domains are an optional later extension, not a first-release promise.

Resolve the correct branding before login from the trusted hostname/environment mapping, not an arbitrary browser-supplied customer identifier. Store settings and logo files in the relevant tenant environment. Restrict edits to an authorized customer administrator or authorized platform operator. Validate logo uploads and theme values; do not accept executable HTML, JavaScript or unrestricted CSS as branding. Test cached assets, logout/login, mobile screens and report generation for cross-customer branding leakage.

### TEN-03 — Standard core, isolated customizations

Keep shared FleetFlow behavior in versioned standard addons. Implement customer-specific requests as reviewed, versioned optional addons enabled/deployed only in the intended customer's runtime. Do not fork the entire product per customer or patch Odoo core for individual requests.

Record each tenant's core version, addon versions and enabled features in an operator-controlled deployment manifest. Test standard and customized upgrade paths with backup and rollback procedures. A change for Customer A must not silently alter Customer B. Hiding a menu is not access control. Customers must not upload or execute arbitrary server code through onboarding or customization screens.

### TEN-04 — Two onboarding paths, one provisioning process

Automatic signup and owner-assisted setup must use the same controlled provisioning service/workflow and security defaults. Manual setup adds reviewed branding/configuration and approved customer-specific addons; it must not bypass isolation checks.

Define provisioning states, a unique tenant identity and hostname, retry/idempotency rules, health checks and failure cleanup limited to resources created by that provisioning attempt. A partially configured tenant must not become publicly usable. Repeated or concurrent signup requests must not create duplicate subscriptions/environments or reuse another customer's database, files or secrets.

Keep account verification, invitations and secrets out of logs. Track monthly subscription/access status separately from provisioning status. Record payment-provider selection and payment integration as explicit later work; do not invent a configured gateway. Automatic billing, retries and suspension policies need their own reviewed rules and tests. Suspension must not delete customer data as an incidental side effect. Manually onboarded customers still use the same subscription and environment records.

### TEN-05 — Per-customer operation and recovery

Define backup schedules, database/filestore consistency, protected backup storage, health monitoring, deployment inventory, staged updates and rollback. Rehearse a restore into an isolated target before handling live customer data. Restoring Customer A must not overwrite or expose Customer B.

Record authorized platform-operator/support access and its audit trail; distinguish this from customer-admin permissions. Do not claim customers' data is inaccessible to the hosting owner. Define export, suspension, offboarding and deletion procedures before using them; destructive actions require explicit authorization. Choose retention, recovery objectives, infrastructure budget and service commitments through separate owner decisions rather than fabricated defaults.

### TEN-06 — Launch-blocking acceptance evidence

Use at least two separate synthetic customer environments with different branding, users, orders and attachments. Test as ordinary users AND customer administrators. Cover overlapping record IDs and the same email address in both environments. A second company in one database does not substitute for a second tenant.

Required evidence includes:

- Customer A cannot authenticate into or retrieve/modify Customer B's data using A's credentials/session. Test direct URLs/RPC calls, database-selection parameters, exports, reports, guessed attachment identifiers, session reuse and manipulated host/forwarded-host inputs.
- Tenant A's application database credentials cannot access tenant B's database. Tenant A's runtime cannot read B's filestore, secrets or backups. Audit public database-management routes and any background job paths too.
- Each hostname shows only its own permitted branding before and after login, including cached assets, mobile views, reports and enabled email flows. Unknown hosts fail closed.
- A customer-specific addon and branding change for A does not affect B. Standard and customized tenants retain working upgrade/rollback paths.
- Both provisioning entry points use the same implementation. Retry, concurrency and failed-setup tests show no duplicate or mixed-up environments. Unbuilt automatic billing/onboarding is explicitly marked missing, not passed by a manual demo.
- Backup/restore and a staged update for A preserve B's records, availability and identity. Log/support outputs do not disclose another customer's content or secrets.

For each requirement, report **Verified / Present but unverified / Partial / Missing / Blocked**, with file references, exact tests run, evidence and remaining risk. Failed tenant-isolation checks block ALL real-customer hosting, including a manually onboarded pilot. Full self-service/payment automation can follow a controlled manual pilot; the common isolation, branding, access and recovery gates cannot.

## Apply and run — bounded implementation after review

1. Inspect the local working tree. Preserve unrelated changes and do not overwrite the user's files. Fetch the named branch, or create a local work branch from the stated baseline if the remote branch is unavailable.
2. Extract the package at repository root. It adds `custom_addons/fleetflow/`, `fleetflow/` and `.github/workflows/fleetflow.yml`; it must not replace Odoo core files.
3. Read `fleetflow/README.md`, run `python3 fleetflow/check_static.py`, then `python3 fleetflow/manage.py test` with Docker Compose available.
4. Resolve genuine Odoo 16 installation, model/view, ORM, asset and test failures. Do not remove permission checks or weaken tests merely to get a green result. Keep improvements in the custom addon/deployment layer, not core Odoo.
5. Run `python3 fleetflow/manage.py init`, then optionally `python3 fleetflow/manage.py demo` only in a disposable local evaluation database. Secrets are generated into the ignored `fleetflow/.env`; do not print them in logs, reports or commits.
6. Use a real browser against Odoo. Validate the live Owl workspace and all navigation, filtered metrics, kanban/list/form/calendar/report screens, and empty/error states. Use 1440 px and 390 px viewports and keyboard navigation; fix actual overflow, contrast, focus and console errors.
7. Create real manager, dispatcher and technician test users. Complete the entire workflow, reject for rework, re-complete inspections and release. Verify technician assignment rules, manager-only decisions, locked scope, immutable closed records, cross-company restrictions and forged direct RPC writes. Test from ordinary user sessions, not superuser mode.
8. Add a multi-connection concurrency regression for competing transitions. Confirm there is no stale-state bypass or double release. Also validate chatter/activity/attachment interactions with the write guards.
9. Review the deployment images against this old Odoo source. Resolve dependency compatibility rather than claiming the major-version image tags are immutable or production hardened. Keep the development server bound only to localhost.
10. Report exactly which checks ran and which passed or failed. Prepare a reviewable implementation commit and a draft PR only after local tests run; do not merge or deploy publicly without the user's approval.

## Product constraints

Use Community-compatible modules and existing local infrastructure for development. Keep the core workflow free of required paid APIs, Enterprise modules, external runtime fonts/CDNs, arbitrary workflow evaluators or core-wide monkey patches. Hosted infrastructure and an optional payment service are separate approved operating dependencies; agreeing to a hosted subscription product is not authorization to incur costs. Keep the fixed vertical workflow: Intake → Scheduled → In progress → Release review → Released, plus cancellation/rework. Preserve server-side role checks, company isolation, audit protections and locking.

Do not market the current release as a general no-code workflow engine, regulatory inspection certification, rental booking platform, inventory/procurement system or production-ready multi-tenant SaaS. The manager role currently includes dispatch capabilities; independent two-person inspection is not enforced. Do not silently upgrade Odoo 16 to another major version. A supported-core migration and deployment hardening should be a separate explicitly reviewed task.

## Next review execution

Use the accompanying `fleetflow-claude-next-review.md` as the next review prompt. Complete that review before starting another implementation phase. Preserve TEN-01 through TEN-06 in the requirement matrix and subsequent phase prompts.

## Decision provenance

The hosted monthly model, automatic plus manual onboarding, separate customer environments, customer branding and customer-specific addon approach come from Omar’s decisions in this conversation. The detailed controls above turn that agreed direction into proposed acceptance requirements; they are not new execution evidence.
