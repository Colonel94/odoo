# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants


class FleetflowOperatingAuthorization(models.Model):
    """A legal operating permission held by an operating company.

    This is the company/activity-level permit (trade licence + activity permit
    + traffic file context), distinct from vehicle registration, driver permits
    and platform channel approvals. Readiness checks that a request's operator,
    activity and mode are covered by a verified, in-date authorization.

    An uploaded permit is 'pending' until a compliance reviewer verifies it; it
    is never automatically valid. The verified state is set server-side only.
    """
    _name = "fleetflow.operating.authorization"
    _description = "FleetFlow Operating Authorization"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "date_end desc, id desc"

    name = fields.Char(
        string="Reference", required=True, tracking=True,
        help="Permit / licence reference.",
    )
    company_id = fields.Many2one(
        "res.company", string="Operating company", required=True,
        default=lambda self: self.env.company, index=True,
    )
    jurisdiction = fields.Char(default="Dubai", required=True)
    operating_mode = fields.Selection(
        constants.OPERATING_MODES, string="Permitted mode", required=True,
        default="chauffeur",
    )
    activity = fields.Char(string="Licensed activity")
    date_start = fields.Date(string="Valid from")
    date_end = fields.Date(string="Valid until")
    state = fields.Selection(
        [("draft", "Draft"), ("pending", "Pending verification"),
         ("verified", "Verified"), ("rejected", "Rejected"), ("expired", "Expired")],
        default="draft", required=True, tracking=True, copy=False,
    )
    verified_by = fields.Many2one("res.users", readonly=True, copy=False)
    verified_on = fields.Datetime(readonly=True, copy=False)
    evidence_id = fields.Many2one(
        "fleetflow.credential", string="Supporting evidence",
        help="Linked verified evidence document for this authorization.",
    )

    # Verification state and its attribution move only through the review
    # actions; a direct write (even by a compliance user) cannot forge them, and
    # a verified permit's scope/dates are frozen (corrections re-verify).
    _PROTECTED = {"verified_by", "verified_on"}
    _FROZEN = {"operating_mode", "jurisdiction", "activity", "date_start", "date_end"}

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("Authorization %s ends before it starts.") % rec.name)

    def write(self, vals):
        if self._PROTECTED & set(vals):
            raise AccessError(_(
                "An authorization's verification history is set by the review "
                "actions, not a direct write."))
        if vals.get("state") in ("verified", "rejected", "expired"):
            raise AccessError(_(
                "An authorization's verified/rejected state is set through the "
                "review actions, not a direct write."))
        if self._FROZEN & set(vals):
            for rec in self:
                if rec.state == "verified":
                    raise UserError(_(
                        "Verified authorization %s is locked. Re-verify a "
                        "correction rather than editing it in place.") % rec.name)
        return super().write(vals)

    def _apply(self, vals):
        return super().write(vals)

    def _require_compliance(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance")
                or self.env.su):
            raise AccessError(_("Only a compliance reviewer can verify or reject an authorization."))

    def action_submit(self):
        self.filtered(lambda r: r.state == "draft").write({"state": "pending"})

    def action_verify(self):
        self._require_compliance()
        for rec in self:
            if rec.state not in ("draft", "pending"):
                raise UserError(_("Only draft/pending authorizations can be verified (%s).") % rec.name)
        self._apply({
            "state": "verified",
            "verified_by": self.env.uid,
            "verified_on": fields.Datetime.now(),
        })

    def action_reject(self):
        self._require_compliance()
        self._apply({"state": "rejected", "verified_by": self.env.uid,
                     "verified_on": fields.Datetime.now()})

    def _is_valid_for(self, at_date):
        """True if verified and in-date at the given date (date object)."""
        self.ensure_one()
        if self.state != "verified":
            return False
        if self.date_start and at_date < self.date_start:
            return False
        if self.date_end and at_date > self.date_end:
            return False
        return True
