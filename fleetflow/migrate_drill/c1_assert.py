# Assert, under the NEW code, that the inconsistent legacy chain seeded by
# c1_seed.py is handled safely and that the two controls still work. Run via
# `odoo` `drill` mode.
#
# Proven here:
#  - stored identities, replacement links, states, verification attribution and
#    source-byte hashes are PRESERVED (never silently rewritten), for the
#    inconsistent chain AND both controls;
#  - the inconsistent chain grants NO trusted coverage from EITHER side: the
#    predecessor (superseded, ambiguous cutover) AND the redirected successor
#    (evaluated on itself), alone and together in both record orders, and through
#    the actual readiness document check for BOTH affected subjects, over an
#    interval INSIDE the successor's own validity window;
#  - a valid same-identity renewal chain still covers on both sides of its
#    cutover, and an independent verified credential is evaluated normally.
import json
from datetime import datetime

import pytz

from odoo.addons.fleetflow_operations.models import constants

TZ = pytz.timezone("Asia/Dubai")
d = json.load(open("/var/lib/odoo/c1_seed.json"))
Cred = env["fleetflow.credential"]
Readiness = env["fleetflow.readiness"]

pred = Cred.browse(d["pred"])
renewal = Cred.browse(d["renewal"])
pred_c = Cred.browse(d["pred_c"])
renewal_c = Cred.browse(d["renewal_c"])
indep = Cred.browse(d["indep"])
Att = env["ir.attachment"]


def iv(y, m, dd, h1=8, h2=18):
    return (TZ.localize(datetime(y, m, dd, h1)), TZ.localize(datetime(y, m, dd, h2)))


def sha(att_id):
    import hashlib
    return hashlib.sha256(Att.browse(att_id).raw).hexdigest()


# --- 1) Stored identity / links / states / attribution PRESERVED -----------
assert pred.vehicle_id.id == d["pred_vehicle"] == d["cars"]["a"], "predecessor identity rewritten"
assert renewal.vehicle_id.id == d["renewal_vehicle"] == d["cars"]["b"], "renewal identity rewritten"
assert pred.company_id.id == d["pred_company"], "predecessor company rewritten"
assert renewal.company_id.id == d["renewal_company"], "renewal company rewritten"
assert pred.doc_kind == d["pred_doc_kind"], "predecessor doc_kind rewritten"
assert renewal.doc_kind == d["renewal_doc_kind"], "renewal doc_kind rewritten"
assert pred.superseded_by_id.id == d["pred_superseded_by"] == d["renewal"], "replacement link changed"
assert renewal.supersedes_id.id == d["renewal_supersedes"] == d["pred"], "supersedes link changed"
assert pred.state == d["pred_state"] == "superseded", "predecessor state changed"
assert renewal.state == d["renewal_state"] == "verified", "renewal state changed"
assert pred.verified_by.id == d["pred_verified_by"], "predecessor verification attribution changed"
assert renewal.verified_by.id == d["renewal_verified_by"], "renewal verification attribution changed"

# --- 2) Source-byte hashes UNCHANGED (inconsistent chain + controls) --------
assert sha(d["pred_att"]) == d["pred_sha"], "predecessor source bytes changed"
assert sha(d["renewal_att"]) == d["renewal_sha"], "renewal source bytes changed"
assert sha(d["pred_c_att"]) == d["pred_c_sha"], "control predecessor source bytes changed"
assert sha(d["renewal_c_att"]) == d["renewal_c_sha"], "control renewal source bytes changed"
assert sha(d["indep_att"]) == d["indep_sha"], "independent source bytes changed"

# --- 3) Inconsistent chain grants NO coverage from EITHER side --------------
# Interval INSIDE the redirected successor's own validity window (Oct 2026-Sep
# 2027); testing only a date before it starts would hide the successor-side defect.
inside = iv(2026, 11, 1)
assert pred._cutover(TZ) is None, "inconsistent legacy cutover was trusted"
assert not renewal._effective_interval(TZ)[2], "redirected successor treated as reliable"
assert renewal._validity(*inside, TZ) == "unknown", "redirected successor validity trusted"
assert not Cred._resolve_coverage(renewal, *inside, TZ), "redirected successor granted coverage alone"
assert not Cred._resolve_coverage(pred, *inside, TZ), "predecessor granted coverage alone"
assert not Cred._resolve_coverage(pred + renewal, *inside, TZ), "inconsistent chain covered (pred+succ)"
assert not Cred._resolve_coverage(renewal + pred, *inside, TZ), "inconsistent chain covered (succ+pred)"

# Actual readiness document check for BOTH affected subjects. Assert the affected
# reason's status/code specifically (not merely overall non-green).
for car_key, label in (("a", "predecessor subject"), ("b", "successor subject")):
    veh = env["fleet.vehicle"].browse(d["cars"][car_key])
    reason = Readiness._check_document("vehicle_id", veh, "vehicle_registration", *inside, TZ)
    assert reason["status"] == constants.NEEDS_REVIEW, "%s not needs-review: %s" % (label, reason)
    assert reason["code"] == "doc_validity_unknown", "%s wrong code: %s" % (label, reason)

# --- 4) Controls: valid same-identity chain and independent credential -------
assert pred_c.state == "superseded" and renewal_c.state == "verified", "control chain state changed"
assert pred_c.superseded_by_id.id == d["pred_c_superseded_by"] == d["renewal_c"], "control link changed"
# Valid chain covers on both sides of its cutover (1 Oct 2026).
assert Cred._resolve_coverage(pred_c + renewal_c, *iv(2026, 6, 1), TZ) == pred_c, "control pre-cutover lost"
assert Cred._resolve_coverage(pred_c + renewal_c, *iv(2026, 11, 1), TZ) == renewal_c, "control post-cutover lost"
car_c = env["fleet.vehicle"].browse(d["cars"]["c"])
r_c_before = Readiness._check_document("vehicle_id", car_c, "vehicle_registration", *iv(2026, 6, 1), TZ)
assert r_c_before["status"] == constants.READY, "valid control not ready pre-cutover: %s" % r_c_before
# Independent credential is evaluated normally and still covers its own subject.
assert not indep.supersedes_id, "independent credential unexpectedly linked"
assert Cred._resolve_coverage(indep, *iv(2026, 6, 1), TZ) == indep, "independent credential lost coverage"
car_d = env["fleet.vehicle"].browse(d["cars"]["d"])
r_d = Readiness._check_document("vehicle_id", car_d, "vehicle_registration", *iv(2026, 6, 1), TZ)
assert r_d["status"] == constants.READY, "independent credential not ready: %s" % r_d

print("C1_ASSERT_OK identities/links/attribution/source-hashes preserved; inconsistent chain "
      "grants no coverage from either side (both subjects need review); valid chain and "
      "independent credential still covered")
