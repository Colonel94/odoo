# -*- coding: utf-8 -*-
"""Shared vocabularies for FleetFlow Operations.

These are deliberately finite. The readiness engine evaluates only built-in,
named predicates over these values -- never user-supplied expressions or code.
Nothing here encodes an assumed RTA/platform rule as fact; concrete validity
dates and category classifications live on reviewed evidence records, and
anything unknown resolves to NEEDS_REVIEW rather than a green result.
"""

# Licensed activities / vehicle-use modes (kept separate from channels).
OPERATING_MODES = [
    ("chauffeur", "Chauffeur / limousine (with driver)"),
    ("rental", "Rental without driver"),
]

# Distribution channels are NOT a legal activity permit.
CHANNELS = [
    ("uber", "Uber"),
    ("careem", "Careem"),
    ("rental_marketplace", "Rental marketplace"),
    ("direct", "Direct / walk-in"),
    ("other", "Other"),
]

# Date precision: never fabricate a day (e.g. 1 January) from a bare year.
DATE_PRECISION = [
    ("day", "Exact day"),
    ("month", "Month"),
    ("year", "Year only"),
    ("unknown", "Unknown"),
]

# How a vehicle entered the fleet (drives which age date-basis applies).
SOURCE_CATEGORY = [
    ("new", "New (from registration date)"),
    ("used_local", "Used, locally registered"),
    ("imported", "Imported / used (from manufacture date)"),
    ("unknown", "Unknown"),
]

POWERTRAIN = [
    ("ice", "Internal combustion"),
    ("hybrid", "Hybrid"),
    ("ev", "Electric"),
    ("unknown", "Unknown"),
]

# Official category is evidence-backed, never inferred from price or badge.
OFFICIAL_CATEGORY = [
    ("ordinary", "Ordinary / standard"),
    ("elite_luxury", "Approved elite / luxury list"),
    ("unknown", "Unknown / not classified"),
]

# Kinds of compliance evidence. Each credential has exactly one subject.
DOC_KINDS = [
    ("trade_licence", "Trade licence"),
    ("activity_permit", "Activity / operating permit"),
    ("vehicle_registration", "Vehicle registration (Mulkiya)"),
    ("insurance", "Insurance (with use scope)"),
    ("inspection", "Technical inspection certificate"),
    ("tracking_cert", "Approved tracking certificate"),
    ("driver_licence", "Driving licence"),
    ("professional_permit", "Professional driver permit"),
    ("fitness_clearance", "Fitness clearance (status only)"),
    ("category_classification", "Official vehicle category classification"),
    ("channel_approval", "Channel / platform approval"),
    ("temp_authority", "Temporary operating authority (Takamul)"),
    ("other", "Other"),
]

# Readiness verdicts. Blocked and Needs review both forbid confirm/checkout.
READY = "ready"
WARNING = "warning"
BLOCKED = "blocked"
NEEDS_REVIEW = "needs_review"
READINESS_STATES = [
    (READY, "Ready"),
    (WARNING, "Warning"),
    (BLOCKED, "Blocked"),
    (NEEDS_REVIEW, "Needs review"),
]
# Severity ordering for combining per-check results into an overall verdict.
_SEVERITY = {READY: 0, WARNING: 1, NEEDS_REVIEW: 2, BLOCKED: 3}


def worst(states):
    """Return the most severe readiness state in an iterable (default READY)."""
    result = READY
    for state in states:
        if _SEVERITY.get(state, 0) > _SEVERITY.get(result, 0):
            result = state
    return result


def bump_resource_locks(env, vehicle_ids=(), driver_ids=()):
    """Serialise dispatch-affecting changes on the persistent resource rows.

    Confirm/checkout/reschedule already bump a lock counter on the vehicle and
    driver rows so competing reservations serialise (Postgres first-updater-wins
    under REPEATABLE READ). ANY other mutation that can invalidate a dispatch
    decision -- a hold, an evidence verification/revocation, a channel status
    change -- must bump the SAME counter, so a concurrent checkout and such a
    change cannot both succeed on stale snapshots. Vehicles are updated before
    drivers, both in id order, so two transactions cannot deadlock.
    """
    vehicle_ids = tuple(sorted({i for i in vehicle_ids if i}))
    driver_ids = tuple(sorted({i for i in driver_ids if i}))
    if vehicle_ids:
        env.cr.execute(
            "UPDATE fleet_vehicle SET ff_alloc_lock = COALESCE(ff_alloc_lock, 0) + 1 "
            "WHERE id IN %s", (vehicle_ids,))
    if driver_ids:
        env.cr.execute(
            "UPDATE fleetflow_driver SET ff_alloc_lock = COALESCE(ff_alloc_lock, 0) + 1 "
            "WHERE id IN %s", (driver_ids,))
