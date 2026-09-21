# FleetFlow implementation and verification handoff

Work in the user's `Colonel94/odoo` repository. Use the provided `fleetflow-source.zip` as the starting implementation, not a new brief to redesign from scratch.

## Goal and current state

Build FleetFlow, an Odoo Community 16.0 workflow platform for rental/commercial-fleet maintenance. A complete first-source implementation is provided as an addon plus local deployment utilities. Its structural checks passed. Its actual Odoo runtime and database tests have not been executed. A sample-data design preview was rendered at 1440 px and 390 px without page-level horizontal overflow; that is not an Odoo browser test.

The remote branch `feat/fleetflow-workflow-platform` was created from commit `7d63cda14808a1b3e363f66a21ee133b4a41a3a6`, but the connector blocked the code upload. There are no implementation commits or pull requests from this session. Do not assume the addon is already in the repository.

## Apply and run

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

Use Community-only modules and existing local infrastructure. No paid APIs, SaaS dependencies, Enterprise modules, external runtime fonts/CDNs, arbitrary workflow evaluators or core-wide monkey patches. Keep the fixed vertical workflow: Intake → Scheduled → In progress → Release review → Released, plus cancellation/rework. Preserve server-side role checks, company isolation, audit protections and locking.

Do not market the current release as a general no-code workflow engine, regulatory inspection certification, rental booking platform, inventory/procurement system or production-ready multi-tenant SaaS. The manager role currently includes dispatch capabilities; independent two-person inspection is not enforced. Do not silently upgrade Odoo 16 to another major version. A supported-core migration and deployment hardening should be a separate explicitly reviewed task.

---

## SUPERSEDED — read the revised pack (21 September 2026)

This original handoff is superseded on delivery-model and hosting decisions by the
revised pack now in this folder. Read these before acting:

- `fleetflow-claude-handoff-v2.md` — revised handoff; adds hosted-subscription requirements **TEN-01…TEN-06**.
- `fleetflow-phased-delivery-plan-v2.md` — revised phased roadmap (Phases 0–7).
- `fleetflow-claude-next-review.md` — the review-pass prompt.

**Confirmed model:** monthly subscription, **always hosted by Omar** (multi-tenant SaaS), with automatic self-service signup and owner-assisted onboarding. Customer-installed software is **not** the delivery model.

**Verified current state (this repo, local):** the single-tenant app is installed, all 14 integration tests pass, and the live Owl workspace is browser-verified with correct role filtering — see `NEXT_REVIEW.md`. Runtime deviation from the delivered deploy design (image-core, not `/workspace/odoo-bin`) is documented in `entrypoint.py` and `IMPLEMENTATION_STATUS.md`.

**Review deliverables produced:** `NEXT_REVIEW.md`, `TENANT_REQUIREMENTS_MATRIX.md`, `ADR-HOSTED-TENANCY.md`, `PHASED_BACKLOG.md`, `NEXT_IMPLEMENTATION_PROMPT.md`.

**Next implementation (bounded):** P1.5 two isolated local tenants + trusted host routing — see `NEXT_IMPLEMENTATION_PROMPT.md`. Tenant isolation (TEN-06), branding (TEN-02), access and recovery (TEN-05) are launch gates for **any** real customer, including a manual pilot.
