# -*- coding: utf-8 -*-
"""Backfill the durable ever_verified marker on upgrade to 16.0.1.1.0.

The column is added by the ORM before this script runs. We derive the marker only
from unambiguous recorded state -- a currently verified or superseded record was,
by definition, verified at some point, so its source file must stay protected.
We deliberately do NOT infer it for 'rejected' rows (older code also stamped a
verification timestamp on a plain rejection, so that column is ambiguous there):
those keep ever_verified=False and would surface for review rather than have a
prior verification fabricated. No document is deleted or altered.
"""


def migrate(cr, version):
    cr.execute(
        "UPDATE fleetflow_credential SET ever_verified = TRUE "
        "WHERE ever_verified IS NOT TRUE AND state IN ('verified', 'superseded')"
    )
