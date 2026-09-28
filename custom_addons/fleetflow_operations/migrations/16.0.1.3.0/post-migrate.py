# -*- coding: utf-8 -*-
"""Upgrade to 16.0.1.3.0 (OPS-2A physical custody).

Custody is now represented by immutable fleetflow.custody.event records instead of
only editable allocation fields. This migration reconstructs custody history for
allocations created before this version, WITHOUT inventing precision that was never
recorded:

- For every allocation physically handed out (state checked_out or returned, with a
  recorded custody_out_at), a legacy CHECKOUT event is created at that recorded
  time, with the recorded odometer/unit.
- For every returned allocation with a recorded custody_in_at, a legacy RETURN event
  is created at that time, with the recorded odometer/fuel/condition/defect.
- The recorded TIMESTAMP is preserved (it was real data); the handover ACTOR was
  never captured before OPS-2A, so performed_by is left empty and the event is marked
  is_legacy with an explicit legacy_source -- unknown data is flagged, never faked.
- The vehicle's trusted odometer (ff_last_odometer_km) is seeded from the highest
  legacy reading, in canonical km.
- The allocation's checkout_event_id/return_event_id mirrors are linked back.

Nothing else is altered: allocation ids, states, planned/actual timestamps, mileage
fields, defect flags, chatter and existing hold/work-order links are preserved. New
columns are added by the ORM before this script runs. Existing companies get the
conservative default early-handover tolerance (0 = no early handover).
"""
from odoo import api, SUPERUSER_ID
from odoo.addons.fleetflow_operations.models import constants


def _km(value, unit):
    if value is None:
        return 0.0
    return value * constants.MI_TO_KM if unit == "mi" else float(value)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Conservative default tolerance for pre-existing companies (0 = no early handover).
    cr.execute("UPDATE res_company SET ff_checkout_early_tolerance_minutes = 0 "
               "WHERE ff_checkout_early_tolerance_minutes IS NULL")

    Event = env["fleetflow.custody.event"].sudo()
    Alloc = env["fleetflow.allocation"].sudo()
    allocs = Alloc.search([("state", "in", ("checked_out", "returned")),
                           ("custody_out_at", "!=", False)])
    vehicle_max = {}  # vehicle id -> highest canonical km seen
    for alloc in allocs:
        unit = alloc.odometer_unit or "km"
        checkout_ev = return_ev = False
        # Legacy CHECKOUT event (skip if one already exists, so re-running is safe).
        existing = Event.search([("allocation_id", "=", alloc.id),
                                 ("event_type", "=", "checkout")], limit=1)
        if existing:
            checkout_ev = existing
        elif alloc.custody_out_at:
            out_km = _km(alloc.checkout_odometer, unit)
            checkout_ev = Event.create({
                "allocation_id": alloc.id, "vehicle_id": alloc.vehicle_id.id,
                "driver_id": alloc.driver_id.id or False, "company_id": alloc.company_id.id,
                "event_type": "checkout", "event_time": alloc.custody_out_at,
                "performed_by": False, "is_legacy": True,
                "legacy_source": "Imported from allocation %s (pre-OPS-2A); "
                                 "handover actor not recorded." % alloc.name,
                "odometer": alloc.checkout_odometer, "odometer_unit": unit,
                "odometer_km": out_km, "condition": "acceptable", "defect": False,
            })
            vehicle_max[alloc.vehicle_id.id] = max(
                vehicle_max.get(alloc.vehicle_id.id, 0.0), out_km)
        # Legacy RETURN event for returned allocations.
        if alloc.state == "returned" and alloc.custody_in_at:
            existing_ret = Event.search([("allocation_id", "=", alloc.id),
                                         ("event_type", "=", "return")], limit=1)
            if existing_ret:
                return_ev = existing_ret
            else:
                in_km = _km(alloc.return_odometer, unit)
                return_ev = Event.create({
                    "allocation_id": alloc.id, "vehicle_id": alloc.vehicle_id.id,
                    "driver_id": alloc.driver_id.id or False, "company_id": alloc.company_id.id,
                    "event_type": "return", "event_time": alloc.custody_in_at,
                    "performed_by": False, "is_legacy": True,
                    "legacy_source": "Imported from allocation %s (pre-OPS-2A); "
                                     "handover actor not recorded." % alloc.name,
                    "odometer": alloc.return_odometer, "odometer_unit": unit,
                    "odometer_km": in_km, "fuel_note": alloc.return_fuel or False,
                    "condition": "damage_noted" if alloc.return_defect else "acceptable",
                    "defect": bool(alloc.return_defect),
                    "notes": alloc.return_condition or False,
                })
                vehicle_max[alloc.vehicle_id.id] = max(
                    vehicle_max.get(alloc.vehicle_id.id, 0.0), in_km)
        # Link the mirrors back without touching any other allocation fact.
        link = {}
        if checkout_ev and not alloc.checkout_event_id:
            link["checkout_event_id"] = checkout_ev.id
        if return_ev and not alloc.return_event_id:
            link["return_event_id"] = return_ev.id
        if link:
            alloc._apply(link)

    # Seed each vehicle's trusted odometer from the highest legacy reading, in km,
    # only where it advances the (currently unset) value.
    for vehicle_id, km in vehicle_max.items():
        if km:
            env["fleet.vehicle"].browse(vehicle_id)._ff_record_odometer(km, km, "km")
