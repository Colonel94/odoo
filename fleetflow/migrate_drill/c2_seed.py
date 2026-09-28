# Seed pre-OPS-2A allocation/custody data under the OLD code (736752af), which had
# NO custody events -- custody lived only in editable allocation fields. Run via
# `odoo` `drill` mode with FF_DRILL pointing here. Writes ids/states/timestamps/
# mileage/defect/hold links to the shared volume so the post-upgrade assertion can
# prove they are preserved and that legacy custody events are reconstructed with
# explicit provenance.
import json
from datetime import date, datetime, timedelta

company = env.company
Cred = env["fleetflow.credential"]
Veh = env["fleet.vehicle"]
Alloc = env["fleetflow.allocation"]
brand = env["fleet.vehicle.model.brand"].create({"name": "c2 brand"})
model = env["fleet.vehicle.model"].create({"name": "c2 model", "brand_id": brand.id})


def car(plate):
    return Veh.create({"model_id": model.id, "license_plate": plate, "company_id": company.id,
                       "ff_operator_company_id": company.id, "ff_operational_state": "reviewed"})


def driver(name, ref):
    return env["fleetflow.driver"].create({"name": name, "employee_ref": ref, "company_id": company.id})


def verify_cred(kind, field, subj):
    c = Cred.create({"name": "%s-%s" % (kind, subj.id), "doc_kind": kind, "company_id": company.id,
                     field: subj.id, "date_start": date.today() - timedelta(days=10),
                     "date_end": date.today() + timedelta(days=365)})
    c.action_verify()
    return c


def enrol(field, subj):
    e = env["fleetflow.channel.enrolment"].create({
        "company_id": company.id, "channel": "uber", "product": "UberX", "city": "Dubai",
        field: subj.id})
    e.action_approve()
    return e


profile = env["fleetflow.operating.profile"].create({
    "name": "c2 chauffeur", "company_id": company.id, "operating_mode": "chauffeur",
    "require_operating_authorization": False, "require_vehicle_registration": True,
    "require_insurance": True, "require_driver_licence": True,
    "require_professional_permit": False, "require_channel_approval": True,
    "enforce_end_of_use": False})
profile.action_publish()

now = datetime.utcnow()


def make(veh, drv, plate_start_offset_h, end_offset_h):
    verify_cred("vehicle_registration", "vehicle_id", veh)
    verify_cred("insurance", "vehicle_id", veh)
    verify_cred("driver_licence", "driver_id", drv)
    ev = enrol("vehicle_id", veh)
    ed = enrol("driver_id", drv)
    a = Alloc.create({
        "company_id": company.id, "operating_mode": "chauffeur", "city": "Dubai",
        "vehicle_id": veh.id, "driver_id": drv.id,
        "planned_start": now + timedelta(hours=plate_start_offset_h),
        "planned_end": now + timedelta(hours=end_offset_h),
        "channel_enrolment_ids": [(6, 0, [ev.id, ed.id])]})
    a.action_confirm()
    return a


# 1) CONFIRMED only (never handed over).
v1, d1 = car("C2-CONF"), driver("c2 d1", "C2-D1")
a_conf = make(v1, d1, -1, 8)

# 2) CHECKED-OUT (physically out, not returned).
v2, d2 = car("C2-OUT"), driver("c2 d2", "C2-D2")
a_out = make(v2, d2, -1, 8)
a_out.action_checkout(odometer=1200)

# 3) RETURNED clean.
v3, d3 = car("C2-RET"), driver("c2 d3", "C2-D3")
a_ret = make(v3, d3, -1, 8)
a_ret.action_checkout(odometer=500)
a_ret.action_return(odometer=780, fuel="full", condition="clean")

# 4) RETURNED with a defect (old code created a hold + work order).
v4, d4 = car("C2-DEF"), driver("c2 d4", "C2-D4")
a_def = make(v4, d4, -1, 8)
a_def.action_checkout(odometer=9000)
a_def.action_return(odometer=9120, defect=True, condition="warning light")

hold = env["fleetflow.vehicle.hold"].search([("source_allocation_id", "=", a_def.id)], limit=1)

# 5) RETURNED recorded in MILES (old code had a single shared odometer_unit). The
#    1.4.0 migration must backfill the new return_odometer_unit from it, so the
#    historical miles reading is not relabelled as kilometres.
v5, d5 = car("C2-MI"), driver("c2 d5", "C2-D5")
a_mi = make(v5, d5, -1, 8)
a_mi.write({"odometer_unit": "mi"})
a_mi.action_checkout(odometer=100)
a_mi.action_return(odometer=200)

data = {
    "confirmed": {"id": a_conf.id, "state": a_conf.state, "vehicle": v1.id},
    "checked_out": {"id": a_out.id, "state": a_out.state, "vehicle": v2.id,
                    "custody_out_at": str(a_out.custody_out_at), "checkout_odometer": a_out.checkout_odometer},
    "returned": {"id": a_ret.id, "state": a_ret.state, "vehicle": v3.id,
                 "custody_out_at": str(a_ret.custody_out_at), "custody_in_at": str(a_ret.custody_in_at),
                 "checkout_odometer": a_ret.checkout_odometer, "return_odometer": a_ret.return_odometer},
    "returned_defect": {"id": a_def.id, "state": a_def.state, "vehicle": v4.id,
                        "custody_out_at": str(a_def.custody_out_at), "custody_in_at": str(a_def.custody_in_at),
                        "checkout_odometer": a_def.checkout_odometer, "return_odometer": a_def.return_odometer,
                        "return_defect": a_def.return_defect,
                        "hold": hold.id, "hold_state": hold.state, "hold_type": hold.hold_type,
                        "hold_work_order": hold.source_work_order_id.id},
    "mi": {"id": a_mi.id, "vehicle": v5.id, "unit": a_mi.odometer_unit,
           "checkout_odometer": a_mi.checkout_odometer, "return_odometer": a_mi.return_odometer},
}
with open("/var/lib/odoo/c2_seed.json", "w") as fh:
    fh.write(json.dumps(data))
env.cr.commit()
print("C2_SEED_OK", json.dumps(data))
