# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from . import constants


class FleetflowDriver(models.Model):
    """A limousine/chauffeur driver.

    A driver is NOT an Odoo workshop technician and NOT merely a fleet.vehicle
    driver_id partner. It has its own employer, permit scope, platform
    enrolments and verification lifecycle. The optional app-user link lets a
    driver see only their own shift without inheriting staff privileges;
    identity/clearance evidence lives on restricted credential records, never
    on a globally visible contact.
    """
    _name = "fleetflow.driver"
    _description = "FleetFlow Driver"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    employee_ref = fields.Char(
        string="Operational identifier",
        help="Internal reference; keep government ID numbers on restricted "
             "credential records, not here.",
    )
    company_id = fields.Many2one(
        "res.company", string="Employer", required=True,
        default=lambda self: self.env.company, index=True,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Contact", check_company=True,
        help="Optional contact record.",
    )
    user_id = fields.Many2one(
        "res.users", string="App user", domain="[('share', '=', False)]",
        help="Optional login for the driver's own shift view. A driver app-user "
             "must not inherit dispatcher/workshop/admin permissions.",
    )
    active = fields.Boolean(default=True)
    available = fields.Boolean(
        string="Available", default=True,
        help="Operational availability flag (leave/suspension). This is not a "
             "shift/rest-hours ruling.",
    )
    permitted_mode = fields.Selection(
        constants.OPERATING_MODES, string="Permitted mode", default="chauffeur",
    )
    # Driver evidence relation (credential_ids) is added in the evidence commit.

    _sql_constraints = [
        ("employee_ref_company_uniq",
         "unique(employee_ref, company_id)",
         "A driver with this operational identifier already exists for this employer."),
    ]

    @api.constrains("user_id")
    def _check_user_not_privileged(self):
        risky = [
            "fleetflow.group_manager",
            "fleetflow.group_dispatcher",
            "fleetflow_operations.group_ops_dispatcher",
            "fleetflow_operations.group_ops_compliance",
            "fleetflow_operations.group_ops_fleet_manager",
            "base.group_system",
        ]
        for driver in self:
            user = driver.user_id
            if not user:
                continue
            for xmlid in risky:
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group and group in user.groups_id:
                    raise ValidationError(_(
                        "The app user for driver %s has elevated permissions (%s). "
                        "A driver login must only see its own shift."
                    ) % (driver.name, group.name))
