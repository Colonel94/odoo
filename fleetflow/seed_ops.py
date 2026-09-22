"""Synthetic Dubai-operations demo: three scenarios + role users. Local eval only.

Idempotent and clearly fictional. Refuses to run where real operations data
exists unless FLEETFLOW_ALLOW_DEMO is set. Creates:
  Scenario A - a fully eligible chauffeur shift (confirmable / checkoutable).
  Scenario B - a blocked shift (expired insurance + missing Careem approval).
  Scenario C - a vehicle with an active maintenance hold blocking dispatch.
Plus one user per operations role (password: fleetflow).
"""
import json
import os
from datetime import date, datetime, time, timedelta

from odoo import fields

MARK = "SYNTHETIC OPS DEMO"
PASSWORD = "fleetflow"
ROLE_USERS = [
    ("ff_ops_dispatcher", "Ops Dispatcher (eval)", "fleetflow_operations.group_ops_dispatcher"),
    ("ff_ops_compliance", "Ops Compliance (eval)", "fleetflow_operations.group_ops_compliance"),
    ("ff_ops_manager", "Ops Fleet Manager (eval)", "fleetflow_operations.group_ops_fleet_manager"),
]


def _cred(env, company, kind, field, subject, start, end, verify=True):
    cred = env["fleetflow.credential"].create({
        "name": "%s %s" % (MARK, kind), "doc_kind": kind, "company_id": company.id,
        field: subject.id, "date_start": start, "date_end": end,
    })
    if verify:
        cred.action_verify()
    return cred


def seed(env):
    params = env["ir.config_parameter"].sudo()
    if params.get_param("fleetflow_ops.demo_seeded"):
        print("Ops demo already present; nothing added.")
        return
    if not os.environ.get("FLEETFLOW_ALLOW_DEMO"):
        real = env["fleetflow.allocation"].search_count([("name", "not ilike", MARK)])
        if real:
            print("Refusing: real allocations present. Set FLEETFLOW_ALLOW_DEMO=1 on a disposable DB.")
            return
    company = env.ref("base.user_admin").company_id
    env = env(context=dict(env.context, allowed_company_ids=[company.id]))

    # Role users (refuse to clobber pre-existing non-seeded logins).
    managed = set(json.loads(params.get_param("fleetflow.ops_user_ids", "[]")))
    # Ops users land on the operations Assignments board, not the maintenance
    # Owl workspace (which is technician-scoped).
    home = env.ref("fleetflow_operations.action_allocations")
    driver_user = None
    for login, name, group in ROLE_USERS + [("ff_ops_driver", "Ops Driver (eval)", "fleetflow_operations.group_ops_driver")]:
        existing = env["res.users"].search([("login", "=", login)], limit=1)
        if existing and existing.id not in managed:
            print("Skipping existing non-seeded user %r." % login)
            continue
        vals = {"name": name, "login": login, "password": PASSWORD, "email": login + "@example.com",
                "company_id": company.id, "company_ids": [(6, 0, [company.id])],
                "groups_id": [(4, env.ref(group).id)], "action_id": home.id}
        user = existing and (existing.write(vals) or existing) or env["res.users"].create(vals)
        managed.add(user.id)
        if login == "ff_ops_driver":
            driver_user = user
    params.set_param("fleetflow.ops_user_ids", json.dumps(sorted(managed)))

    brand = env["fleet.vehicle.model.brand"].create({"name": MARK + " brand"})
    model = env["fleet.vehicle.model"].create({"name": "Demo Saloon", "brand_id": brand.id})

    def vehicle(plate):
        return env["fleet.vehicle"].create({
            "model_id": model.id, "license_plate": plate, "company_id": company.id,
            "ff_operator_company_id": company.id, "ff_operational_state": "reviewed",
            "ff_official_category": "ordinary", "location": "Fictional demo yard"})

    def driver(name, ref, user=None):
        return env["fleetflow.driver"].create({
            "name": name, "employee_ref": ref, "company_id": company.id,
            "user_id": user.id if user else False})

    # Shared policy + operating permit.
    profile = env["fleetflow.operating.profile"].create({
        "name": MARK + " chauffeur", "company_id": company.id, "operating_mode": "chauffeur",
        "source_ref": "synthetic", "require_operating_authorization": True,
        "require_vehicle_registration": True, "require_insurance": True,
        "require_driver_licence": True, "require_professional_permit": True,
        "require_channel_approval": True, "enforce_end_of_use": False})
    profile.action_publish()
    env["fleetflow.operating.authorization"].create({
        "name": MARK + " permit", "company_id": company.id, "operating_mode": "chauffeur",
        "date_start": date.today() - timedelta(days=30), "date_end": date.today() + timedelta(days=300),
        "state": "verified"}).write({"verified_on": fields.Datetime.now()})

    today = date.today()
    far = today + timedelta(days=300)
    day = today + timedelta(days=1)

    def shift(v, d, hours=(9, 17)):
        return datetime.combine(day, time(hours[0])), datetime.combine(day, time(hours[1]))

    # --- Scenario A: eligible chauffeur shift -------------------------------
    va, da = vehicle("DEMO-OPS-1"), driver("Aisha (demo)", "OPS-D1", driver_user)
    _cred(env, company, "vehicle_registration", "vehicle_id", va, today - timedelta(days=30), far)
    _cred(env, company, "insurance", "vehicle_id", va, today - timedelta(days=30), far)
    _cred(env, company, "driver_licence", "driver_id", da, today - timedelta(days=30), far)
    _cred(env, company, "professional_permit", "driver_id", da, today - timedelta(days=30), far)
    enr_a = env["fleetflow.channel.enrolment"].create({
        "company_id": company.id, "channel": "uber", "product": "UberX", "driver_id": da.id,
        "state": "approved", "verified_as_of": fields.Datetime.now()})
    s, e = shift(va, da)
    env["fleetflow.allocation"].create({
        "name": MARK + " A-ready", "company_id": company.id, "operating_mode": "chauffeur",
        "vehicle_id": va.id, "driver_id": da.id, "planned_start": s, "planned_end": e,
        "channel_enrolment_ids": [(6, 0, [enr_a.id])]})

    # --- Scenario B: blocked (expired insurance + missing Careem) -----------
    vb, db = vehicle("DEMO-OPS-2"), driver("Bilal (demo)", "OPS-D2")
    _cred(env, company, "vehicle_registration", "vehicle_id", vb, today - timedelta(days=30), far)
    _cred(env, company, "insurance", "vehicle_id", vb, today - timedelta(days=60), today - timedelta(days=1))
    _cred(env, company, "driver_licence", "driver_id", db, today - timedelta(days=30), far)
    _cred(env, company, "professional_permit", "driver_id", db, today - timedelta(days=30), far)
    enr_b = env["fleetflow.channel.enrolment"].create({
        "company_id": company.id, "channel": "uber", "product": "UberX", "driver_id": db.id,
        "state": "approved", "verified_as_of": fields.Datetime.now()})
    s, e = shift(vb, db, (10, 18))
    env["fleetflow.allocation"].create({
        "name": MARK + " B-blocked", "company_id": company.id, "operating_mode": "chauffeur",
        "vehicle_id": vb.id, "driver_id": db.id, "planned_start": s, "planned_end": e,
        "channel_enrolment_ids": [(6, 0, [enr_b.id])]})

    # --- Scenario C: active maintenance hold blocking dispatch --------------
    vc, dc = vehicle("DEMO-OPS-3"), driver("Chen (demo)", "OPS-D3")
    for k in ("vehicle_registration", "insurance"):
        _cred(env, company, k, "vehicle_id", vc, today - timedelta(days=30), far)
    for k in ("driver_licence", "professional_permit"):
        _cred(env, company, k, "driver_id", dc, today - timedelta(days=30), far)
    env["fleetflow.channel.enrolment"].create({
        "company_id": company.id, "channel": "uber", "product": "UberX", "driver_id": dc.id,
        "state": "approved", "verified_as_of": fields.Datetime.now()})
    env["fleetflow.vehicle.hold"].create({
        "vehicle_id": vc.id, "hold_type": "safety", "reason": MARK + " brake inspection required",
        "dispatch_blocking": True})

    params.set_param("fleetflow_ops.demo_seeded", "1")
    print("Ops demo ready: 3 scenarios (A ready, B blocked, C on hold). "
          "Users ff_ops_dispatcher / ff_ops_compliance / ff_ops_manager / ff_ops_driver (pw: %s)." % PASSWORD)
