# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from . import constants


class FleetflowChannelEnrolment(models.Model):
    """A per-city, per-product platform enrolment (Uber/Careem/rental).

    A channel approval is NOT a legal operating permit and does not substitute
    for one. One vehicle or driver may hold several compatible channel approvals
    (e.g. Uber and Careem) at once; those are not conflicting physical bookings.
    A valid RTA document does not by itself establish platform acceptance, and a
    missing Careem profile must never be filled with Uber assumptions.
    """
    _name = "fleetflow.channel.enrolment"
    _description = "FleetFlow Channel Enrolment"
    _inherit = ["mail.thread"]
    _check_company_auto = True
    _order = "channel, product, id"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", string="Operator", required=True,
        default=lambda self: self.env.company, index=True,
    )
    city = fields.Char(default="Dubai", required=True)
    channel = fields.Selection(constants.CHANNELS, required=True)
    product = fields.Char(string="Platform product", required=True,
                          help="e.g. UberX, Careem Business. Product-specific.")
    vehicle_id = fields.Many2one("fleet.vehicle", check_company=True)
    driver_id = fields.Many2one("fleetflow.driver", check_company=True)
    external_id = fields.Char(string="External ID")
    state = fields.Selection(
        [("pending", "Pending"), ("approved", "Approved"),
         ("suspended", "Suspended"), ("rejected", "Rejected")],
        default="pending", required=True, tracking=True,
    )
    evidence_id = fields.Many2one("fleetflow.credential", string="Approval evidence")
    verified_as_of = fields.Datetime(string="Status verified as of", copy=False)
    recheck_date = fields.Date(string="Next recheck")

    @api.depends("channel", "product", "city")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s / %s (%s)" % (
                dict(constants.CHANNELS).get(rec.channel, rec.channel or "?"),
                rec.product or "?", rec.city or "?",
            )

    @api.constrains("vehicle_id", "driver_id")
    def _check_subject(self):
        for rec in self:
            if not (rec.vehicle_id or rec.driver_id):
                raise ValidationError(_("A channel enrolment needs a vehicle or driver subject."))

    def action_approve(self):
        self.write({"state": "approved", "verified_as_of": fields.Datetime.now()})

    def action_suspend(self):
        self.write({"state": "suspended", "verified_as_of": fields.Datetime.now()})

    def _is_fresh(self, at_dt, max_age_days):
        """True if the platform status was verified recently enough per policy."""
        self.ensure_one()
        if not self.verified_as_of:
            return False
        if not max_age_days:
            return True
        from datetime import timedelta
        return (at_dt - self.verified_as_of) <= timedelta(days=max_age_days)
