# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

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

    # A dispatcher may create/edit a PENDING enrolment and its metadata, but the
    # approval status and its verification timestamp are set only through the
    # reviewer actions -- never a direct write/create (no context flag opts out).
    _PROTECTED = {"verified_as_of"}
    _REVIEWED_STATES = ("approved", "suspended", "rejected")
    # Once reviewed, the IDENTITY of the approval is frozen: the subject, the
    # operator and the city/channel/product scope and the backing evidence define
    # WHAT was reviewed. A correction is a new enrolment reviewed afresh, never an
    # in-place edit that keeps the old approval attached to new facts. (This is a
    # hard invariant -- not even superuser edits a reviewed enrolment's identity.)
    _SCOPE_FROZEN = {"channel", "product", "city", "company_id", "vehicle_id",
                     "driver_id", "evidence_id"}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # A new enrolment is ALWAYS pending with no verification attribution,
            # whatever the caller or default_* context supplies. Set explicitly
            # (not conditionally) so a default_state=approved/suspended/rejected
            # context key, or an omitted state relying on a forged default, cannot
            # produce a reviewed enrolment. Corrections are new pending revisions.
            vals["state"] = "pending"
            vals["verified_as_of"] = False
        return super().create(vals_list)

    def unlink(self):
        # A reviewed enrolment (approved/suspended/rejected) is decision history;
        # only a pending one may be deleted. Superuser (fixtures) is exempt.
        if not self.env.su:
            for rec in self:
                if rec.state in self._REVIEWED_STATES:
                    raise UserError(_(
                        "Enrolment %s is %s and is retained as history; it cannot "
                        "be deleted. Suspend/reject it instead."
                    ) % (rec.name, rec.state))
        return super().unlink()

    def write(self, vals):
        if self._PROTECTED & set(vals):
            raise AccessError(_(
                "The platform status verification timestamp is set by the review "
                "actions, not a direct edit."))
        # The approval status moves ONLY through the reviewer actions, in either
        # direction: a suspended enrolment cannot be quietly reset to pending, and
        # an approval cannot be forged, by a plain write. (Superuser fixtures and
        # migrations are exempt; the action methods write via _apply.)
        if "state" in vals and not self.env.su:
            raise AccessError(_(
                "A channel enrolment's approval status is set through the review "
                "actions (approve/suspend/reject), not a direct write."))
        if self._SCOPE_FROZEN & set(vals):
            for rec in self:
                if rec.state in self._REVIEWED_STATES:
                    raise AccessError(_(
                        "Enrolment %s is %s; its reviewed subject and scope are "
                        "frozen. Create a new enrolment for a change and have it "
                        "reviewed -- do not re-point an existing approval."
                    ) % (rec.name, rec.state))
        # The recheck date is a reviewer freshness control: on a reviewed
        # enrolment a dispatcher must not push it out to fake freshness. Only a
        # compliance reviewer (or superuser) may change it once reviewed.
        if "recheck_date" in vals and not self.env.su and not self.env.user.has_group(
                "fleetflow_operations.group_ops_compliance"):
            for rec in self:
                if rec.state in self._REVIEWED_STATES:
                    raise AccessError(_(
                        "The recheck date on a reviewed enrolment is set by a "
                        "compliance reviewer, not by a direct edit."))
        return super().write(vals)

    @api.constrains("evidence_id", "vehicle_id", "driver_id", "company_id")
    def _check_evidence_scope(self):
        """When approval evidence is linked, it must be evidence of the SAME
        subject and company -- an approval can never borrow another subject's or
        another company's document as its backing proof."""
        for rec in self:
            ev = rec.evidence_id
            if not ev:
                continue
            if ev.company_id != rec.company_id:
                raise ValidationError(_(
                    "Approval evidence for %s must belong to the same company.") % rec.name)
            if rec.vehicle_id and ev.vehicle_id != rec.vehicle_id:
                raise ValidationError(_(
                    "Approval evidence for %s must reference the same vehicle.") % rec.name)
            if rec.driver_id and ev.driver_id != rec.driver_id:
                raise ValidationError(_(
                    "Approval evidence for %s must reference the same driver.") % rec.name)

    def _apply(self, vals):
        return super().write(vals)

    def _require_reviewer(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance")
                or self.env.su):
            raise AccessError(_(
                "Only a compliance reviewer can change a channel enrolment's "
                "approval status."))

    def _bump_subject_locks(self):
        """A channel status change alters a subject's readiness: serialise on the
        shared vehicle/driver lock so a concurrent checkout cannot miss it."""
        constants.bump_resource_locks(
            self.env, self.mapped("vehicle_id").ids, self.mapped("driver_id").ids)

    def action_approve(self):
        self._require_reviewer()
        self._apply({"state": "approved", "verified_as_of": fields.Datetime.now()})
        self._bump_subject_locks()

    def action_suspend(self):
        self._require_reviewer()
        self._apply({"state": "suspended", "verified_as_of": fields.Datetime.now()})
        self._bump_subject_locks()

    def action_reject(self):
        self._require_reviewer()
        self._apply({"state": "rejected", "verified_as_of": fields.Datetime.now()})
        self._bump_subject_locks()

    def _is_fresh(self, at_dt, max_age_days):
        """True if the platform status was verified recently enough per policy."""
        self.ensure_one()
        if not self.verified_as_of:
            return False
        if not max_age_days:
            return True
        from datetime import timedelta
        return (at_dt - self.verified_as_of) <= timedelta(days=max_age_days)
