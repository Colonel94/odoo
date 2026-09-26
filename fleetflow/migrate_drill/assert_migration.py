# Assert the old->new upgrade preserved data and activated the new semantics.
# Runs under the NEW (1.2.0) module via `odoo shell`.
import hashlib
import json
from datetime import datetime

import pytz

TZ = pytz.timezone("Asia/Dubai")
d = json.load(open("/var/lib/odoo/migration_seed.json"))
Cred = env["fleetflow.credential"]


def rec(key):
    return Cred.browse(d[key])


def iv(y, m, dd, h1=8, h2=18):
    return (TZ.localize(datetime(y, m, dd, h1)), TZ.localize(datetime(y, m, dd, h2)))


# -- schema + migration executed ------------------------------------------
assert "ff_source_lock" in env["ir.attachment"]._fields, "ff_source_lock column missing"
env.cr.execute("SELECT count(*) FROM ir_attachment WHERE ff_source_lock IS NULL")
nulls = env.cr.fetchone()[0]
assert nulls == 0, "migration did not initialise ff_source_lock (%s NULLs)" % nulls

# -- data / relationships / attribution / source bytes preserved ----------
cp, cs = rec("chain_pred"), rec("chain_succ")
assert cp.state == "superseded" and cp.superseded_by_id.id == d["chain_succ"], "chain link lost"
assert cs.supersedes_id.id == d["chain_pred"], "reverse chain link lost"
assert str(cp.replaced_on) == d["chain_pred_replaced_on"], "replaced_on changed"
rj = rec("rejected")
assert rj.state == "rejected", rj.state
assert rj.verified_by.id == d["rejected_verified_by"], "original verifier lost"
assert rj.revoked_by.id == d["rejected_revoked_by"], "revoker lost"
assert rj.ever_verified, "durable marker lost"
assert hashlib.sha256(rec("pred_verified").attachment_id.raw).hexdigest() == d["hashes"]["pred_verified"]
assert hashlib.sha256(rj.attachment_id.raw).hexdigest() == d["hashes"]["rejected"], "revoked source bytes changed"

# -- NEW effective-cutover semantics now apply to LEGACY data --------------
# The legacy superseded predecessor's authority ends at the successor's cutover
# (1 Oct 2026), NOT at its own printed expiry (31 Dec 2026).
s, e = iv(2026, 11, 1)
assert cp._validity(s, e, TZ) == "expired", "legacy predecessor still falls back past cutover: %s" % cp._validity(s, e, TZ)
assert cp._cutover(TZ) == TZ.localize(datetime(2026, 10, 1)), cp._cutover(TZ)
assert not Cred._resolve_coverage(cp + cs, *iv(2026, 11, 15), TZ), "no-fallback broken after successor expiry"
assert Cred._resolve_coverage(cp + cs, *iv(2026, 9, 15), TZ) == cp, "pre-cutover predecessor coverage lost"
assert Cred._resolve_coverage(cp + cs, *iv(2026, 10, 15), TZ) == cs, "successor window coverage lost"

# Ambiguous legacy (imprecise successor date) -> surfaced for review, no coverage.
ap = rec("amb_pred")
assert ap._cutover(TZ) is None, "ambiguous cutover was guessed"
assert not Cred._resolve_coverage(ap + rec("amb_succ"), *iv(2026, 6, 1), TZ), "ambiguous legacy granted coverage"

# Untouched records keep behaving: standalone verified still covers; a draft
# renewal never dropped its predecessor's coverage.
pv = rec("pred_verified")
assert Cred._resolve_coverage(pv, *iv(2026, 6, 1), TZ) == pv, "standalone verified coverage lost"
fp = rec("future_pred")
assert Cred._resolve_coverage(fp + rec("future_renewal"), *iv(2026, 6, 1), TZ) == fp, "draft renewal dropped coverage"

print("ASSERT_OK all migration invariants held; nulls_remaining=%s" % nulls)
