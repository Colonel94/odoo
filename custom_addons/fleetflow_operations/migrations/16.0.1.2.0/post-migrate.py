# -*- coding: utf-8 -*-
"""Upgrade to 16.0.1.2.0.

Two corrections land in this version:

1. Effective-dated replacement. The cutover at which a superseded document hands
   over to its successor is now DERIVED from the linked successor's own effective
   start (see credential._cutover), so there is no new stored coverage column to
   backfill and no historical approval/effective fact is manufactured. Legacy
   superseded records therefore start honouring their successor's cutover
   immediately: coverage after the cutover no longer falls back to the
   predecessor. Where a legacy successor has no precise effective date the cutover
   is ambiguous and that predecessor is surfaced for review rather than silently
   granting its old full range -- ambiguous legacy records are preserved, not
   auto-resolved.

2. A source-lock counter (ir_attachment.ff_source_lock) added so evidence approval
   is a committed write on the source row, closing the verification-vs-mutation
   race. The column is added by the ORM before this script runs; we only make its
   default explicit on existing rows. No document bytes, ownership, attribution or
   supersession link is altered.
"""


def migrate(cr, version):
    cr.execute(
        "UPDATE ir_attachment SET ff_source_lock = 0 WHERE ff_source_lock IS NULL")
