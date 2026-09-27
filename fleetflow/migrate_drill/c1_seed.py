# Seed an INCONSISTENT (redirected) renewal chain under the OLD code
# (d0486a74), which allowed a linked renewal's subject to be changed after
# supersession and did not re-check identity at verification. Run via `odoo`
# `drill` mode with FF_DRILL pointing here. Writes ids/identities to the shared
# volume so the post-upgrade assertion can prove they were preserved (not
# rewritten) and that the chain now grants no coverage.
import json
from datetime import date

company = env.company
Cred = env["fleetflow.credential"]
Veh = env["fleet.vehicle"]
brand = env["fleet.vehicle.model.brand"].create({"name": "c1 brand"})
model = env["fleet.vehicle.model"].create({"name": "c1 model", "brand_id": brand.id})
car_a = Veh.create({"model_id": model.id, "license_plate": "C1-A",
                    "company_id": company.id, "ff_operator_company_id": company.id})
car_b = Veh.create({"model_id": model.id, "license_plate": "C1-B",
                    "company_id": company.id, "ff_operator_company_id": company.id})

# Predecessor: a verified registration for Car A.
pred = Cred.create({
    "name": "c1-pred", "doc_kind": "vehicle_registration", "company_id": company.id,
    "vehicle_id": car_a.id, "date_start": date(2026, 1, 1), "date_end": date(2026, 12, 31)})
pred.action_verify()

# The OLD bug: draft the linked renewal, REDIRECT it to Car B, then verify it.
renewal = Cred.browse(pred.action_supersede({
    "name": "c1-renewal", "date_start": date(2026, 10, 1), "date_end": date(2027, 9, 30)}))
renewal.write({"vehicle_id": car_b.id})   # old code permitted this identity change
renewal.action_verify()                    # old code did not re-check continuity

data = {
    "pred": pred.id, "renewal": renewal.id, "car_a": car_a.id, "car_b": car_b.id,
    "pred_vehicle": pred.vehicle_id.id, "renewal_vehicle": renewal.vehicle_id.id,
    "pred_superseded_by": pred.superseded_by_id.id, "pred_state": pred.state,
    "renewal_state": renewal.state,
}
with open("/var/lib/odoo/c1_seed.json", "w") as fh:
    fh.write(json.dumps(data))
env.cr.commit()
print("C1_SEED_OK", json.dumps(data))
