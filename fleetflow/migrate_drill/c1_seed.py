# Seed an INCONSISTENT (redirected) renewal chain under the OLD code
# (d0486a74), which allowed a linked renewal's subject to be changed after
# supersession and did not re-check identity at verification. Also seed two
# CONTROLS that must keep working under the new code: a valid same-identity
# renewal chain, and an independent verified credential. Run via `odoo` `drill`
# mode with FF_DRILL pointing here. Writes ids, identities, attribution and
# source-byte hashes to the shared volume so the post-upgrade assertion can prove
# they were preserved (not rewritten) and that only the inconsistent chain now
# grants no coverage.
import base64
import hashlib
import json
from datetime import date

# A small, genuinely-structured PDF (one page, valid xref/trailer/%%EOF) so the
# credentials carry real source files whose bytes can be hash-checked across the
# upgrade. Embedded to keep the drill self-contained (no test-package import).
ONE_PAGE_PDF = base64.b64decode(
    "JVBERi0xLjUKJeLjz9MKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4K"
    "ZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4K"
    "ZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAg"
    "MCA2MTIgNzkyXSAvUmVzb3VyY2VzIDw8ID4+ID4+CmVuZG9iagp4cmVmCjAgNAowMDAwMDAwMDAw"
    "IDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAw"
    "MTIxIDAwMDAwIG4gCnRyYWlsZXIKPDwgL1NpemUgNCAvUm9vdCAxIDAgUiA+PgpzdGFydHhyZWYK"
    "MjA5CiUlRU9GCg==")

company = env.company
Cred = env["fleetflow.credential"]
Veh = env["fleet.vehicle"]
Att = env["ir.attachment"]
brand = env["fleet.vehicle.model.brand"].create({"name": "c1 brand"})
model = env["fleet.vehicle.model"].create({"name": "c1 model", "brand_id": brand.id})


def car(plate):
    return Veh.create({"model_id": model.id, "license_plate": plate,
                       "company_id": company.id, "ff_operator_company_id": company.id})


def att(name):
    return Att.create({"name": name, "raw": ONE_PAGE_PDF})


def sha(attachment):
    return hashlib.sha256(attachment.raw).hexdigest()


car_a = car("C1-A")
car_b = car("C1-B")
car_c = car("C1-C")
car_d = car("C1-D")

# 1) INCONSISTENT redirected chain (the old bug): predecessor for Car A, then a
#    linked renewal REDIRECTED to Car B and verified.
att_pred = att("c1-pred.pdf")
pred = Cred.create({
    "name": "c1-pred", "doc_kind": "vehicle_registration", "company_id": company.id,
    "vehicle_id": car_a.id, "attachment_id": att_pred.id,
    "date_start": date(2026, 1, 1), "date_end": date(2026, 12, 31)})
pred.action_verify()
att_ren = att("c1-renewal.pdf")
renewal = Cred.browse(pred.action_supersede({
    "name": "c1-renewal", "date_start": date(2026, 10, 1), "date_end": date(2027, 9, 30)}))
renewal.write({"vehicle_id": car_b.id, "attachment_id": att_ren.id})  # old code permitted this
renewal.action_verify()                                              # old code did not re-check

# 2) VALID same-identity chain (control): predecessor and renewal both for Car C.
att_pc = att("c1-pred-c.pdf")
pred_c = Cred.create({
    "name": "c1-pred-c", "doc_kind": "vehicle_registration", "company_id": company.id,
    "vehicle_id": car_c.id, "attachment_id": att_pc.id,
    "date_start": date(2026, 1, 1), "date_end": date(2026, 12, 31)})
pred_c.action_verify()
att_rc = att("c1-renewal-c.pdf")
renewal_c = Cred.browse(pred_c.action_supersede({
    "name": "c1-renewal-c", "date_start": date(2026, 10, 1), "date_end": date(2027, 9, 30)}))
renewal_c.write({"attachment_id": att_rc.id})
renewal_c.action_verify()

# 3) INDEPENDENT verified credential (control): Car D, no supersession link.
att_d = att("c1-indep.pdf")
indep = Cred.create({
    "name": "c1-indep", "doc_kind": "vehicle_registration", "company_id": company.id,
    "vehicle_id": car_d.id, "attachment_id": att_d.id,
    "date_start": date(2026, 1, 1), "date_end": date(2026, 12, 31)})
indep.action_verify()

data = {
    "cars": {"a": car_a.id, "b": car_b.id, "c": car_c.id, "d": car_d.id},
    # Inconsistent chain
    "pred": pred.id, "renewal": renewal.id,
    "pred_vehicle": pred.vehicle_id.id, "renewal_vehicle": renewal.vehicle_id.id,
    "pred_company": pred.company_id.id, "renewal_company": renewal.company_id.id,
    "pred_doc_kind": pred.doc_kind, "renewal_doc_kind": renewal.doc_kind,
    "pred_superseded_by": pred.superseded_by_id.id, "renewal_supersedes": renewal.supersedes_id.id,
    "pred_state": pred.state, "renewal_state": renewal.state,
    "pred_verified_by": pred.verified_by.id, "renewal_verified_by": renewal.verified_by.id,
    "pred_att": att_pred.id, "renewal_att": att_ren.id,
    "pred_sha": sha(att_pred), "renewal_sha": sha(att_ren),
    # Valid same-identity control
    "pred_c": pred_c.id, "renewal_c": renewal_c.id,
    "pred_c_state": pred_c.state, "renewal_c_state": renewal_c.state,
    "pred_c_superseded_by": pred_c.superseded_by_id.id,
    "pred_c_att": att_pc.id, "renewal_c_att": att_rc.id,
    "pred_c_sha": sha(att_pc), "renewal_c_sha": sha(att_rc),
    # Independent control
    "indep": indep.id, "indep_state": indep.state,
    "indep_att": att_d.id, "indep_sha": sha(att_d),
}
with open("/var/lib/odoo/c1_seed.json", "w") as fh:
    fh.write(json.dumps(data))
env.cr.commit()
print("C1_SEED_OK", json.dumps(data))
