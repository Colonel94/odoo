# -*- coding: utf-8 -*-
"""Upgrade to 16.0.1.4.0 (accurate handover capture + effective corrections).

Checkout and return now carry their OWN reported unit. Before this version a single
allocation `odometer_unit` was the (shared) capture unit for both handovers. The new
`return_odometer_unit` column is added by the ORM before this script runs; here we
backfill it from the existing `odometer_unit` for every allocation that already has a
return, so a historical return recorded in miles is not relabelled as kilometres.

Nothing else changes: the immutable custody events already store their own per-event
unit, and no event id, physical timestamp, actor, measurement, correction link or
maintenance provenance is altered. `checkout_notes` is a new free-text capture with no
historical value to reconstruct (we never fabricate one).
"""


def migrate(cr, version):
    # Backfill the return unit from the previously-shared checkout/return unit for
    # allocations that have actually been returned.
    cr.execute(
        "UPDATE fleetflow_allocation SET return_odometer_unit = odometer_unit "
        "WHERE custody_in_at IS NOT NULL "
        "AND (return_odometer_unit IS NULL OR return_odometer_unit = 'km') "
        "AND odometer_unit IS NOT NULL")
    # Any remaining NULLs (never-returned rows) take the conservative km default.
    cr.execute(
        "UPDATE fleetflow_allocation SET return_odometer_unit = 'km' "
        "WHERE return_odometer_unit IS NULL")
