# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants


class FleetflowCredential(models.Model):
    """A single piece of compliance evidence with a verification lifecycle.

    Exactly one subject: an operating company, a vehicle, or a driver. A pending
    upload cannot self-approve: the verified state is only reachable through the
    compliance action, never through create/write/import/context defaults. A
    verified document is immutable except by being superseded, which retains the
    old version. Attachments are kept restricted (see record rules).
    """
    _name = "fleetflow.credential"
    _description = "FleetFlow Compliance Evidence"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "date_end desc, id desc"

    name = fields.Char(string="Reference", required=True, tracking=True)
    doc_kind = fields.Selection(constants.DOC_KINDS, required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="Operating company", required=True,
        default=lambda self: self.env.company, index=True,
    )

    # Exactly one subject.
    operator_company_id = fields.Many2one("res.company", string="Operator subject")
    vehicle_id = fields.Many2one("fleet.vehicle", string="Vehicle subject", check_company=True)
    driver_id = fields.Many2one("fleetflow.driver", string="Driver subject", check_company=True)
    subject_kind = fields.Selection(
        [("operator", "Operator"), ("vehicle", "Vehicle"), ("driver", "Driver")],
        compute="_compute_subject_kind", store=True,
    )

    issuer = fields.Char()
    reference = fields.Char(string="Document number")
    date_start = fields.Date(string="Valid from")
    date_end = fields.Date(string="Valid until")
    date_precision = fields.Selection(constants.DATE_PRECISION, default="day")

    state = fields.Selection(
        [("draft", "Draft"), ("pending", "Pending verification"),
         ("verified", "Verified"), ("rejected", "Rejected"), ("superseded", "Superseded")],
        default="draft", required=True, tracking=True, copy=False,
    )
    verified_by = fields.Many2one("res.users", readonly=True, copy=False)
    verified_on = fields.Datetime(readonly=True, copy=False)

    attachment_id = fields.Many2one(
        "ir.attachment", string="Document file", copy=False,
        help="The source document. Access is restricted to compliance/fleet roles.",
    )
    superseded_by_id = fields.Many2one("fleetflow.credential", string="Superseded by", readonly=True, copy=False)
    supersedes_id = fields.Many2one("fleetflow.credential", string="Supersedes", readonly=True, copy=False)
    note = fields.Text()

    # Fields that may never be forged through create/write/import/context.
    _PROTECTED = {"verified_by", "verified_on", "superseded_by_id", "supersedes_id"}

    @api.depends("operator_company_id", "vehicle_id", "driver_id")
    def _compute_subject_kind(self):
        for rec in self:
            if rec.vehicle_id:
                rec.subject_kind = "vehicle"
            elif rec.driver_id:
                rec.subject_kind = "driver"
            elif rec.operator_company_id:
                rec.subject_kind = "operator"
            else:
                rec.subject_kind = False

    @api.constrains("operator_company_id", "vehicle_id", "driver_id", "subject_kind")
    def _check_single_subject(self):
        for rec in self:
            subjects = [bool(rec.operator_company_id), bool(rec.vehicle_id), bool(rec.driver_id)]
            if sum(subjects) != 1:
                raise ValidationError(_(
                    "Evidence %s must have exactly one subject (operator, vehicle or driver)."
                ) % rec.name)

    @api.constrains("operator_company_id", "vehicle_id", "driver_id", "subject_kind", "company_id")
    def _check_subject_company(self):
        for rec in self:
            if rec.operator_company_id and rec.operator_company_id != rec.company_id:
                raise ValidationError(_("Operator subject must match the evidence company."))
            if rec.vehicle_id and rec.vehicle_id.company_id != rec.company_id:
                raise ValidationError(_("Vehicle subject must belong to the evidence company."))
            if rec.driver_id and rec.driver_id.company_id != rec.company_id:
                raise ValidationError(_("Driver subject must belong to the evidence company."))

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("Evidence %s ends before it starts.") % rec.name)

    # ------------------------------------------------------------------
    # Forged-state protection
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        clean = []
        for source in vals_list:
            vals = dict(source)
            # New evidence never starts verified/superseded and carries no
            # verification history, whatever the caller or default_* context says.
            for key in self._PROTECTED:
                vals[key] = False
            if vals.get("state") not in ("draft", "pending"):
                vals["state"] = "draft"
            clean.append(vals)
        return super().create(clean)

    def write(self, vals):
        internal = self.env.context.get("ff_credential_action")
        if not internal:
            forbidden = self._PROTECTED & set(vals)
            if forbidden:
                raise AccessError(_(
                    "Verification history is set through the review actions, not direct writes."
                ))
            if vals.get("state") in ("verified", "superseded"):
                raise AccessError(_(
                    "Use Verify to record a verified state; it cannot be set directly."
                ))
            # A verified document is immutable except through supersession.
            frozen = {"doc_kind", "operator_company_id", "vehicle_id", "driver_id",
                      "date_start", "date_end", "reference", "issuer", "attachment_id"}
            if frozen & set(vals):
                for rec in self:
                    if rec.state in ("verified", "superseded"):
                        raise UserError(_(
                            "Verified evidence %s is locked. Supersede it with a renewal "
                            "instead of editing it."
                        ) % rec.name)
        return super().write(vals)

    def _require_compliance(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance") or self.env.su):
            raise AccessError(_("Only a compliance reviewer can verify or reject evidence."))

    def action_verify(self):
        self._require_compliance()
        for rec in self:
            if rec.state not in ("draft", "pending"):
                raise UserError(_("Only draft/pending evidence can be verified (%s).") % rec.name)
        self.with_context(ff_credential_action=True).write({
            "state": "verified", "verified_by": self.env.uid, "verified_on": fields.Datetime.now(),
        })
        return True

    def action_submit(self):
        self.filtered(lambda r: r.state == "draft").write({"state": "pending"})
        return True

    def action_reject(self):
        self._require_compliance()
        self.with_context(ff_credential_action=True).write({
            "state": "rejected", "verified_by": self.env.uid, "verified_on": fields.Datetime.now(),
        })
        return True

    def action_supersede(self, new_vals):
        """Create a renewal that supersedes this verified document, retaining history."""
        self.ensure_one()
        self._require_compliance()
        vals = dict(new_vals)
        vals.setdefault("doc_kind", self.doc_kind)
        vals.setdefault("company_id", self.company_id.id)
        for fname in ("operator_company_id", "vehicle_id", "driver_id"):
            if self[fname]:
                vals.setdefault(fname, self[fname].id)
        renewal = self.create(vals)
        renewal.with_context(ff_credential_action=True).write({"supersedes_id": self.id})
        self.with_context(ff_credential_action=True).write({
            "state": "superseded", "superseded_by_id": renewal.id,
        })
        return renewal

    # ------------------------------------------------------------------
    # Validity helpers (used by the readiness service)
    # ------------------------------------------------------------------
    @staticmethod
    def _local_midnight(day, tz):
        """Timezone-aware midnight of `day` in pytz zone `tz`.

        Uses tz.localize (never datetime.replace, which would apply the zone's
        historical LMT offset instead of the real standard offset).
        """
        from datetime import datetime, time
        return tz.localize(datetime.combine(day, time.min))

    def _covers_interval(self, start_dt, end_dt, tz):
        """True if this evidence is verified and valid for the WHOLE [start,end).

        Date-only validity uses a local-day boundary: 'valid until D' means valid
        through the end of day D in the operator's timezone, never an accidental
        UTC midnight. A missing bound is treated as open on that side.
        """
        self.ensure_one()
        if self.state != "verified":
            return False
        from datetime import timedelta
        if self.date_start and start_dt < self._local_midnight(self.date_start, tz):
            return False
        if self.date_end:
            # End of local day date_end (exclusive upper boundary = next midnight).
            if end_dt > self._local_midnight(self.date_end + timedelta(days=1), tz):
                return False
        return True

    def _expires_after(self, at_dt, tz):
        """True if a valid-until exists and falls after `at_dt` (a later renewal)."""
        self.ensure_one()
        if self.state != "verified" or not self.date_end:
            return False
        from datetime import timedelta
        return self._local_midnight(self.date_end + timedelta(days=1), tz) > at_dt
