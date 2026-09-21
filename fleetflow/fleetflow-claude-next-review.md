# FleetFlow — Next Claude Code review prompt

Read the revised `fleetflow-claude-handoff-v2.md` and `fleetflow-phased-delivery-plan-v2.md` alongside the current `Colonel94/odoo` checkout. When these files have been copied into the repository under the canonical names, read those revised copies instead. This is a review-and-planning pass; do not implement the full roadmap in one change.

Omar's confirmed delivery model is MONTHLY SUBSCRIPTIONS, ALWAYS HOSTED BY OMAR. Support both automatic standard signup and owner-assisted onboarding/customization. Do not revert to selling customer-installed software.

First inspect the actual repository, branch, source package and test evidence. Preserve unrelated changes. The earlier handoff recorded a created branch but a blocked implementation upload and unexecuted runtime tests; verify today's state rather than assuming that old status still holds. Apply the source package only when needed, after comparing it with the checkout. Do not overwrite newer implementation work.

Review the original maintenance workflow, UI/UX, role permissions and runtime readiness AND every requirement TEN-01 through TEN-06 in the revised handoff:

1. Separate customer runtime, database, filestore and restricted application credentials; isolated backup access. One standard codebase. No shared-database multi-company substitute for unrelated customers.
2. Trusted per-customer hostname routing, strict database selection, blocked public database-management routes and isolated sessions.
3. Per-customer logo, colors and name across pre-login/login, workspace and reports; email branding where enabled. Authorized configuration and no cross-tenant cache leakage.
4. Reviewed customer-specific addons deployed only to their intended tenant; version manifests, staged upgrades and tested rollback.
5. Automatic and manual onboarding through one idempotent provisioning path with common security defaults, safe failure cleanup and distinct monthly-subscription/access states. Identify missing payment integration honestly.
6. Two-tenant negative security tests, branding tests, customization separation, provisioning retry tests and independent backup/restore. Do not mark security verified from visual inspection or administrator-only demonstrations.

Use a disposable LOCAL test environment with synthetic data for safe tests. Inspect commands before running them. Reuse existing test commands where applicable and report exact results. Do not weaken assertions, role restrictions or isolation to obtain passing tests. Check version-specific APIs/settings against official documentation for the approved runtime; no silent major-version migration.

Produce:
- `NEXT_REVIEW.md`: current commit/environment, concise executive findings, defects, evidence and what was not tested.
- `TENANT_REQUIREMENTS_MATRIX.md`: TEN-01..TEN-06 mapped to code/configuration, Verified / Present but unverified / Partial / Missing / Blocked, exact tests, owner and phase/work-package IDs.
- `ADR-HOSTED-TENANCY.md`: customer boundary, trusted hostname-to-runtime-to-database mapping, secrets/filestore/backup boundaries, customization strategy, common onboarding workflow and shared-host/operator risks.
- A revised phased backlog placing architecture in Phase 0, two-tenant scaffolding in Phase 1, branding in Phase 2, isolation/recovery launch gates in Phase 6, and both commercial onboarding paths in Phase 7. Pull relevant gates forward before any live customer pilot.
- ONE bounded next implementation prompt, tied to unmet prerequisites and explicit acceptance criteria. Do not start that implementation in this review pass.

If the repository uses a durable agent instruction file, add or update a brief pointer to the revised handoff without overwriting unrelated instructions; otherwise record the requirement in project documentation. Keep the documentation changes reviewable. Preserve the agreed hosted model in every subsequent implementation prompt.

Do not merge, deploy publicly, process real payments, provision paid services, import live customer data, delete databases or make destructive changes without separate approval. Do not describe requirements as already implemented or a screenshot as isolation evidence. Tenant-isolation failures are launch blockers, not post-launch polish.
