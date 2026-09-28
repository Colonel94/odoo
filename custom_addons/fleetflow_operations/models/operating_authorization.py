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
    open_ended = fields.Boolean(
        string="Reviewed non-expiring",
        help="A reviewer has confirmed this permit genuinely has no expiry. A "
             "blank 'valid until' is NOT the same: it is unknown validity.")
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
    # Once verified, the whole reviewed claim is frozen: operator/company, scope,
    # dates AND the supporting evidence link/provenance. A correction re-verifies
    # a new record; it never mutates a verified one in place.
    _FROZEN = {"company_id", "operating_mode", "jurisdiction", "activity",
               "date_start", "date_end", "open_ended", "evidence_id"}

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("Authorization %s ends before it starts.") % rec.name)

    @api.constrains("evidence_id", "company_id", "operating_mode")
    def _check_evidence_scope(self):
        """When supporting evidence is linked it must be an operator credential of
        the SAME company -- an authorization cannot borrow another company's or a
        vehicle/driver document as its proof. Evidence is not required here (that
        stays open), but a wrong-scope link is rejected."""
        for rec in self:
            ev = rec.evidence_id
            if not ev:
                continue
            if ev.company_id != rec.company_id:
                raise ValidationError(_(
                    "Supporting evidence for %s must belong to the same company.") % rec.name)
            if ev.subject_kind not in ("operator", False):
                raise ValidationError(_(
                    "Supporting evidence for %s must be an operator/company document.") % rec.name)

    def unlink(self):
        # Only a genuinely unused draft/pending authorization may be deleted; a
        # once-reviewed one is history and is withdrawn, not erased. Superuser
        # (fixtures/migration) is exempt.
        if not self.env.su:
            for rec in self:
                if rec.state not in ("draft", "pending"):
                    raise UserError(_(
                        "Authorization %s is %s and is retained as history; it "
                        "cannot be deleted. Reject/withdraw it instead."
                    ) % (rec.name, rec.state))
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # A new authorization never starts verified and carries no verification
            # attribution, whatever the caller or default_* context supplies.
            vals["verified_by"] = False
            vals["verified_on"] = False
            if vals.get("state") not in ("draft", "pending"):
                vals["state"] = "draft"
        return super().create(vals_list)

    def write(self, vals):
        if self._PROTECTED & set(vals):
            raise AccessError(_(
                "An authorization's verification history is set by the review "
                "actions, not a direct write."))
        if vals.get("state") in ("verified", "rejected", "expired"):
            raise AccessError(_(
                "An authorization's verified/rejected state is set through the "
                "review actions, not a direct write."))
        # A verified/rejected/expired authorization is historical: it cannot be
        # downgraded to draft/pending by a direct write and re-verified in place.
        # A correction is a new record re-verified afresh. Superuser is exempt.
        if "state" in vals and not self.env.su:
            for rec in self:
                if rec.state in ("verified", "rejected", "expired"):
                    raise AccessError(_(
                        "Authorization %s is %s; its state cannot change by a "
                        "direct write. Re-verify a correction as a new record."
                    ) % (rec.name, rec.state))
        if self._FROZEN & set(vals):
            for rec in self:
                if rec.state in ("verified", "rejected", "expired"):
                    raise UserError(_(
                        "Authorization %s is %s and locked. Re-verify a correction "
                        "as a new record rather than editing it in place.") % (rec.name, rec.state))
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
