# Assert, under the NEW code, that the inconsistent legacy chain seeded by
# c1_seed.py is handled safely: stored identities and the replacement link are
# PRESERVED (never silently rewritten), and the chain grants NO coverage (it is
# flagged for review, not trusted). Run via `odoo` `drill` mode.
import json
from datetime import datetime

import pytz

TZ = pytz.timezone("Asia/Dubai")
d = json.load(open("/var/lib/odoo/c1_seed.json"))
Cred = env["fleetflow.credential"]
pred = Cred.browse(d["pred"])
renewal = Cred.browse(d["renewal"])

# Historical identities and the replacement link are unchanged (not rewritten).
assert pred.vehicle_id.id == d["pred_vehicle"] == d["car_a"], "predecessor identity rewritten"
assert renewal.vehicle_id.id == d["renewal_vehicle"] == d["car_b"], "renewal identity rewritten"
assert pred.superseded_by_id.id == d["renewal"], "replacement link changed"
assert pred.state == "superseded" and renewal.state == "verified", "states changed"

# The inconsistent chain is flagged: no cutover, and no coverage is granted.
assert pred._cutover(TZ) is None, "inconsistent legacy cutover was trusted"


def iv(y, m, dd):
    return (TZ.localize(datetime(y, m, dd, 8)), TZ.localize(datetime(y, m, dd, 18)))


assert not Cred._resolve_coverage(pred, *iv(2026, 6, 1), TZ), "inconsistent legacy chain granted coverage"
print("C1_ASSERT_OK identities preserved, replacement link intact, chain flagged, no coverage")
