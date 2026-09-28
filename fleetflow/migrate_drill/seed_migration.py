# Seed representative records under the OLD (1.1.0) module, via `odoo shell`.
# Runs as SUPERUSER; uses real verify/supersede/reject actions. Writes the ids,
# relationships, attribution and source hashes to the shared odoo-data volume.
import hashlib
import json
from datetime import date


def build_pdf(objects, root_ref="1 0 R"):
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offs = {}
    for n, body in objects:
        offs[n] = len(out)
        out += ("%d 0 obj\n" % n).encode() + body + b"\nendobj\n"
    xref = len(out)
    size = len(objects) + 1
    out += ("xref\n0 %d\n" % size).encode() + b"0000000000 65535 f \n"
    for n, _ in objects:
        out += ("%010d 00000 n \n" % offs[n]).encode()
    out += b"trailer\n" + ("<< /Size %d /Root %s >>\n" % (size, root_ref)).encode()
    out += b"startxref\n" + ("%d\n" % xref).encode() + b"%%EOF\n"
    return bytes(out)


PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"),
])

company = env.company
Cred = env["fleetflow.credential"]
brand = env["fleet.vehicle.model.brand"].create({"name": "mig brand"})
model = env["fleet.vehicle.model"].create({"name": "mig model", "brand_id": brand.id})
vehicle = env["fleet.vehicle"].create({
    "model_id": model.id, "license_plate": "MIG-1", "company_id": company.id,
    "ff_operator_company_id": company.id})
driver = env["fleetflow.driver"].create({
    "name": "mig driver", "employee_ref": "MIG-D", "company_id": company.id})


def mk(kind, field, subj, s, e, precision="day", attach=False):
    vals = {"name": "%s-mig" % kind, "doc_kind": kind, "company_id": company.id,
            field: subj.id, "date_start": s, "date_end": e, "date_precision": precision}
    if attach:
        att = env["ir.attachment"].create({"name": "%s.pdf" % kind, "raw": PDF})
        vals["attachment_id"] = att.id
    cred = Cred.create(vals)
    cred.action_verify()
    return cred


# 1) standalone verified (with a source file)
pred_verified = mk("insurance", "vehicle_id", vehicle, date(2026, 1, 1), date(2026, 12, 31), attach=True)
# 2) precise superseded chain (legacy): predecessor -> future-effective successor
chain_pred = mk("vehicle_registration", "vehicle_id", vehicle, date(2026, 1, 1), date(2026, 12, 31))
chain_succ = Cred.browse(chain_pred.action_supersede({
    "name": "chain-succ", "date_start": date(2026, 10, 1), "date_end": date(2026, 10, 31),
    "date_precision": "day"}))
chain_succ.action_verify()
# 3) rejected/revoked (with file): attribution must survive
rej = mk("driver_licence", "driver_id", driver, date(2026, 1, 1), date(2026, 12, 31), attach=True)
rej.action_reject(reason="legacy revoke")
# 4) future renewal still a draft: predecessor coverage must be preserved
future_pred = mk("inspection", "vehicle_id", vehicle, date(2026, 1, 1), date(2026, 12, 31))
future_renewal = Cred.browse(future_pred.action_supersede({
    "name": "future-renewal", "date_start": date(2026, 11, 1), "date_end": date(2027, 10, 31),
    "date_precision": "day"}))
# 5) ambiguous legacy: successor with an IMPRECISE effective date (only creatable
#    under the OLD code, which had no precise-date guard) -> must surface for review
amb_pred = mk("tracking_cert", "vehicle_id", vehicle, date(2026, 1, 1), date(2026, 12, 31))
amb_succ = Cred.browse(amb_pred.action_supersede({
    "name": "amb-succ", "date_start": date(2026, 10, 1), "date_end": date(2027, 9, 30),
    "date_precision": "year"}))
amb_succ.action_verify()


def h(cred):
    return hashlib.sha256(cred.attachment_id.raw).hexdigest() if cred.attachment_id else None


data = {
    "vehicle": vehicle.id, "driver": driver.id,
    "pred_verified": pred_verified.id,
    "chain_pred": chain_pred.id, "chain_succ": chain_succ.id,
    "rejected": rej.id,
    "future_pred": future_pred.id, "future_renewal": future_renewal.id,
    "amb_pred": amb_pred.id, "amb_succ": amb_succ.id,
    "hashes": {"pred_verified": h(pred_verified), "rejected": h(rej)},
    "rejected_verified_by": rej.verified_by.id, "rejected_revoked_by": rej.revoked_by.id,
    "chain_pred_replaced_on": str(chain_pred.replaced_on),
}
with open("/var/lib/odoo/migration_seed.json", "w") as fh:
    fh.write(json.dumps(data))
env.cr.commit()
print("SEED_OK", json.dumps(data))
