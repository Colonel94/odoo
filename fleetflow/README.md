# FleetFlow — fleet maintenance workflow platform

A Community-only, local-first operational workspace for rental and commercial transport fleets. It replaces the scattered handover between a reported vehicle issue, dispatch, workshop repair, inspection and an explicit manager release decision.

## What is implemented

- Custom responsive Owl workspace: live permission-filtered metrics, priority queue, workflow distribution, retry/empty/loading states and working navigation.
- Work-order board, searchable list, detailed order form, technician queue, scheduling calendar, vehicle register and volume reports.
- Fixed workflow: **Intake → Scheduled → In progress → Release review → Released**, with controlled cancellation and rework.
- Scope approval, assignment, deadlines, estimated/actual costs, repair evidence, five inspection checks and named/timestamped release decisions.
- Odoo chatter, tracked workflow/evidence changes and activities. No paid messaging provider is required or configured.
- Server-side permissions, assigned-work rules for technicians, selected-company isolation, immutable approved scope, protected audit fields and row locking around transitions.
- Local Compose setup, generated secrets, dedicated non-superuser database role, fictional sample data and 14 Odoo integration tests.

## Verification status

**Delivery status:** this source package has not been committed to GitHub. Branch creation succeeded, but the connector blocked the code-upload request. The remote `feat/fleetflow-workflow-platform` branch therefore still has the original code. Extract this package into a local checkout before using the commands below.

This is a first implementation for local evaluation, not a production-certified release. Structural checks were run during creation. The authoring environment could not download/start Odoo and PostgreSQL; therefore the real Odoo installation, integration tests, asset compilation and live application browser tests were **not executed there**. The supplied CI and local test command must pass before merging for operational use.

The repository's baseline is Odoo 16.0 commit `7d63cda14808a1b3e363f66a21ee133b4a41a3a6`, dated May 2023. The module intentionally does not alter or silently upgrade that core. Review security updates and migrate to a currently maintained Odoo release before internet-facing deployment. The development container tags are major-version tags, not immutable production digest pins.

## Start locally

Prerequisites: this complete Odoo repository, Python 3.9 or newer on the host, and running Docker with Compose v2 supporting `up --wait`. The container supplies the Odoo Python dependencies. Initial image downloads require internet access; the custom application does not use remote fonts, CDNs, paid APIs or an Enterprise addon.

From the repository root:

```sh
python3 fleetflow/check_static.py
python3 fleetflow/manage.py init
```

On Windows, use `py` in place of `python3`.

Open `http://localhost:8069`. Sign in as `admin` using `FLEETFLOW_ADMIN_PASSWORD` from `fleetflow/.env`. Setup generates independent database, database-superuser, Odoo-master and administrator secrets. It initializes the database and replaces the bootstrap administrator password **before starting the published web service**. The `.env` file is ignored by Git; do not commit it, paste it into prompts or discard it while retaining the database volumes.

Only `127.0.0.1:8069` is published; PostgreSQL has no host port. The Compose containers run the source in this repository through `/workspace/odoo-bin`, not the image's bundled application code. They write persistent data to named volumes, never into the source checkout.

Open **FleetFlow → Overview**. The bootstrap administrator's home action is also set to this workspace.

Optional fictional data:

```sh
python3 fleetflow/manage.py demo
```

This creates six clearly marked fictional vehicles/orders using the same workflow actions as the application, and is idempotent. No extra login accounts are created. Use it only in a disposable evaluation database, not a real fleet database.

Other commands:

```sh
python3 fleetflow/manage.py start
python3 fleetflow/manage.py stop
python3 fleetflow/manage.py logs
python3 fleetflow/manage.py test
```

`stop` retains data. `test` uses the separate `fleetflow-test` Compose project and removes **only that test project's volumes** afterward. Do not manually run an unrelated `docker compose down -v` against the main project unless you intend to delete that database and filestore.

## Operating roles

| FleetFlow role | Access |
| --- | --- |
| Technician | Reads assigned orders and the company vehicle register. Starts assigned scheduled work, records repair evidence and submits it for release review. Cannot create orders, change scope or approve/release. |
| Dispatcher | Inherits technician capabilities. Sees company work, creates requests, prepares estimates and dispatch, and manages the vehicle register. Can record workshop evidence on a technician's behalf. Cannot approve, release or cancel. |
| Operations manager | Inherits dispatcher capabilities. Approves scoped work, records release, returns work for re-inspection or cancels with a reason. Only unapproved intake drafts can be deleted. |

Create internal users in Odoo Settings and select the appropriate **FleetFlow** access level and allowed companies. Do not give technicians Operations manager/System Administration privileges. Existing access granted by other Odoo modules remains additive; this addon does not revoke unrelated core Fleet permissions. Use a non-administrator technician account for acceptance testing, not superuser mode. Configure company name, currency and user timezone before real entry; costs use that company's currency and reports do not aggregate unlike currencies into a monetary grand total.

The manager role includes dispatch capabilities, so the product does **not** enforce independent two-person inspection. Release is an attributable human decision, not proof of mechanical safety, roadworthiness or regulatory approval.

## Workflow rules

1. A dispatcher records the vehicle, issue, priority, estimate rationale, technician, planned start and target completion.
2. A manager approves. The vehicle, service scope and estimate are then locked. The technician and schedule may be changed while still Scheduled, but cannot be cleared.
3. The assigned technician or dispatcher starts work, records diagnosis, work performed, actual cost and all five checks.
4. Submission freezes that evidence for review. A manager records release, or provides a reason and returns the order for rework; returning resets all inspection checks.
5. Released/cancelled order fields cannot be edited or deleted. Standard chatter and audit history remain available subject to Odoo's permissions. To change approved scope, cancel with a reason and create a new order.

The checklist is deliberately conservative and fixed in this version. It is not a configurable legal inspection standard. Technicians must never tick an unperformed check merely to advance a job.

## Test and acceptance gate

Run `python3 fleetflow/manage.py test`. Tests cover the main lifecycle, forged state/audit writes, role gates, assignment visibility, dashboard isolation, cross-company access, frozen scope, required dispatch, repair/rework gates, closed history, cancellation, costs/dates, overdue counts and ineligible assignment. SQL row locks are implemented, but a multi-connection race test is still a required additional hardening task.

The package includes `.github/workflows/fleetflow.yml`; it becomes available in the repository after the package is applied and committed. GitHub may require Actions to be enabled on an existing fork. A workflow file is not evidence that CI passed; inspect the actual run.

Then perform real Odoo browser acceptance at desktop and mobile widths: sign in as manager/dispatcher/technician, create a vehicle/order, approve, start, complete evidence, reject for rework, repeat checks, release, test forbidden direct RPC writes, switch companies, follow each dashboard metric/navigation item, and verify empty/error states and keyboard focus. Check both bundled asset mode and `?debug=assets` for console errors.

## Boundaries of this first release

This is a vertical workflow application, not a general visual BPMN/no-code workflow designer. It does not implement inventory consumption, procurement, invoicing, rental reservations, telematics, preventive auto-generation, customer/driver portals, offline mobile synchronization, SLA escalation notifications, SSO or tenant provisioning. Core Odoo navigation and unrelated apps are not globally reskinned. The custom workspace and order views are intentionally isolated so core upgrades remain feasible.

Before a real pilot: pass runtime and browser testing, inspect performance with realistic records, agree the inspection policy, back up and restore the database **and filestore**, harden deployment, define monitoring and update ownership, and review module/core licenses and any industry obligations. A local working prototype is not an internet-ready multi-tenant SaaS.

## Source map

- `custom_addons/fleetflow/models.py`: workflow, validations, access guards and dashboard data.
- `custom_addons/fleetflow/security/`: model permissions and record rules.
- `custom_addons/fleetflow/views/views.xml`: native operating screens and navigation.
- `custom_addons/fleetflow/static/src/`: Owl interface and scoped visual system.
- `custom_addons/fleetflow/tests/`: Odoo integration tests.
- `fleetflow/`: local startup, fictional data and static checks.

No Odoo core files are modified. The new addon is LGPL-3. Keep the repository's existing license notices; FleetFlow is a working product name, not a claim of trademark clearance.
