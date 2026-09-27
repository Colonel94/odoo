# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # FleetFlow OPERATIONAL rule (not an RTA/legal rule): how many minutes before a
    # reservation's planned start a vehicle may be physically handed over. The
    # default is 0 -- conservative: with no configured tolerance, checkout before
    # planned_start is refused and is only allowed from planned_start until
    # planned_end. An operator may set a small tolerance (e.g. 15-30 minutes) for
    # usability. A large early-handover window is never invented silently.
    ff_checkout_early_tolerance_minutes = fields.Integer(
        string="Early handover tolerance (minutes)", default=0,
        help="FleetFlow operational rule: minutes before planned start that a "
             "vehicle may be checked out. 0 = no early handover (checkout only from "
             "planned start until planned end). This is not a legal/RTA rule.")
