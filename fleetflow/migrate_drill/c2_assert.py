# Assert, under the NEW code (OPS-2A), that the pre-custody-event data seeded by
# c2_seed.py under the old code is migrated safely: allocation ids/states/timestamps/
# mileage/defect flags and existing hold/work-order links are preserved, and legacy
# custody events are reconstructed with explicit provenance (recorded timestamps
# kept, unknown actor left empty, is_legacy set). Run via `odoo` `drill` mode.
import json

d = json.load(open("/var/lib/odoo/c2_seed.json"))
Alloc = env["fleetflow.allocation"]
Event = env["fleetflow.custody.event"]


def events(alloc_id, event_type):
    return Event.search([("allocation_id", "=", alloc_id), ("event_type", "=", event_type)])


# --- 1) CONFIRMED: preserved, and NO custody events (never handed over) ------
conf = Alloc.browse(d["confirmed"]["id"])
assert conf.state == d["confirmed"]["state"] == "confirmed", "confirmed state changed"
assert not conf.custody_event_ids, "confirmed allocation should have no custody events"

# --- 2) CHECKED-OUT: one legacy checkout event, still open, actor unknown ----
out = Alloc.browse(d["checked_out"]["id"])
assert out.state == "checked_out", "checked-out state changed"
out_ev = events(out.id, "checkout")
assert len(out_ev) == 1, "expected exactly one legacy checkout event"
assert out_ev.is_legacy and not out_ev.performed_by, "legacy checkout actor must be unknown"
assert str(out_ev.event_time) == d["checked_out"]["custody_out_at"], "checkout time not preserved"
assert out_ev.odometer == d["checked_out"]["checkout_odometer"], "checkout odometer not preserved"
assert out.checkout_event_id == out_ev, "checkout mirror not linked"
assert not out.return_event_id, "open custody must have no return event"

# --- 3) RETURNED clean: paired legacy events; times/mileage preserved --------
ret = Alloc.browse(d["returned"]["id"])
assert ret.state == "returned", "returned state changed"
r_out, r_in = events(ret.id, "checkout"), events(ret.id, "return")
assert len(r_out) == 1 and len(r_in) == 1, "returned allocation needs paired events"
assert r_in.is_legacy and not r_in.performed_by, "legacy return actor must be unknown"
assert str(r_in.event_time) == d["returned"]["custody_in_at"], "return time not preserved"
assert r_out.odometer == d["returned"]["checkout_odometer"], "checkout odometer not preserved"
assert r_in.odometer == d["returned"]["return_odometer"], "return odometer not preserved"
assert abs(ret.distance_travelled_km - (r_in.odometer_km - r_out.odometer_km)) < 1e-6, "distance wrong"

# --- 4) RETURNED with defect: event flags defect; existing hold preserved ----
dfa = Alloc.browse(d["returned_defect"]["id"])
assert dfa.state == "returned", "defect-returned state changed"
df_in = events(dfa.id, "return")
assert df_in.defect, "legacy return defect flag not preserved"
hold = env["fleetflow.vehicle.hold"].browse(d["returned_defect"]["hold"])
assert hold.exists() and hold.state == d["returned_defect"]["hold_state"], "defect hold not preserved"
assert hold.source_allocation_id.id == dfa.id, "hold provenance changed"
assert hold.source_work_order_id.id == d["returned_defect"]["hold_work_order"], "work-order link changed"

# --- 5) Vehicle trusted mileage seeded from legacy readings (canonical km) ---
v_ret = env["fleet.vehicle"].browse(d["returned"]["vehicle"])
assert v_ret.ff_last_odometer_km >= d["returned"]["return_odometer"], "trusted mileage not seeded"

# --- 6) 1.4.0 backfill: a miles return keeps its unit (not relabelled as km) -
mi = Alloc.browse(d["mi"]["id"])
assert d["mi"]["unit"] == "mi", "seed sanity: expected a miles allocation"
assert mi.odometer_unit == "mi", "checkout unit changed"
assert mi.return_odometer_unit == "mi", "return_odometer_unit not backfilled from odometer_unit"
mi_ret = events(mi.id, "return")
assert mi_ret.odometer_unit == "mi", "legacy return event unit not preserved"
# Canonical km derived from miles (200 mi ~ 321.87 km), so distance is unit-correct.
assert abs(mi_ret.odometer_km - 200 * 1.609344) < 1e-3, "canonical km not derived from miles"

print("C2_ASSERT_OK legacy custody events reconstructed (times preserved, actor unknown, "
      "is_legacy set); allocation states/mileage/defect/hold links preserved; vehicle "
      "trusted mileage seeded")
