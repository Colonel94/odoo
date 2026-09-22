{
    "name": "FleetFlow Operations",
    "version": "16.0.1.0.0",
    "category": "Operations/Fleet",
    "summary": "Dubai fleet operations: resource readiness, evidence, allocation and holds.",
    "description": """
FleetFlow Operations (OPS-1)
============================
Extends the FleetFlow maintenance workspace into a Dubai rental/limousine
operations product. It answers one question:

    Can this vehicle and this driver operate for this legal company, in this
    service/channel, for the entire requested period -- and if not, why?

Scope of this increment (OPS-1):
- Vehicle and driver master records (extends fleet.vehicle; does not duplicate).
- Restricted, versioned compliance evidence with a server-side verification
  lifecycle (a pending upload cannot self-approve).
- Per-city/product channel enrolments (Uber/Careem/rental), evaluated
  separately from the legal operating permit.
- Bounded, versioned operating profiles with a finite set of built-in checks;
  unknown mandatory requirements fail closed to "Needs review".
- Explainable readiness evaluation over the whole requested interval.
- Conflict-safe allocation, custody and maintenance holds.

This is a local, synthetic-data increment. It does NOT integrate with RTA,
TARS, Uber/Careem, SIRA or any payment/telematics system, and it does not
certify roadworthiness or legal compliance. See fleetflow/ops-pack/ for the
research and source register behind the design.
""",
    "author": "FleetFlow",
    "website": "https://github.com/Colonel94/odoo",
    "license": "LGPL-3",
    "depends": [
        "fleetflow",
        "fleet",
    ],
    "data": [
        "security/operations_groups.xml",
        "security/ir.model.access.csv",
        "security/operations_rules.xml",
    ],
    "application": True,
    "installable": True,
}
