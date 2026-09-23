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
    # Sensitive document detail is readable only by the review roles, not by a
    # dispatcher who legitimately sees non-sensitive readiness metadata.
    reference = fields.Char(
        string="Document number",
        groups="fleetflow_operations.group_ops_compliance,fleetflow_operations.group_ops_fleet_manager")
    date_start = fields.Date(string="Valid from")
    date_end = fields.Date(string="Valid until")
    date_precision = fields.Selection(constants.DATE_PRECISION, default="day")
    open_ended = fields.Boolean(
        string="Reviewed non-expiring",
        help="A reviewer has confirmed this evidence genuinely has no expiry. A "
             "blank 'valid until' is NOT the same as this: it is unknown validity.")

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
    note = fields.Text(
        groups="fleetflow_operations.group_ops_compliance,fleetflow_operations.group_ops_fleet_manager")

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
        records = super().create(clean)
        records._bind_attachment()
        return records

    def write(self, vals):
        # No context flag opts out of these guards. The verified/rejected/
        # superseded lifecycle and its attribution move only through the review
        # actions, which write at the ORM level via _apply().
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
                  "date_start", "date_end", "date_precision", "open_ended",
                  "reference", "issuer", "attachment_id"}
        if frozen & set(vals):
            for rec in self:
                if rec.state in ("verified", "superseded"):
                    raise UserError(_(
                        "Verified evidence %s is locked. Supersede it with a renewal "
                        "instead of editing it."
                    ) % rec.name)
        res = super().write(vals)
        if "attachment_id" in vals:
            self._bind_attachment()
        return res

    def _apply(self, vals):
        # Internal transition used by the review actions; bypasses the public
        # write guard by writing at the ORM level.
        return super().write(vals)

    def _bind_attachment(self):
        """Bind a linked document file to THIS credential and make it private, so
        the compliance-only file restriction (ir.attachment.check) actually
        applies. A file referenced through attachment_id can therefore never be a
        loose, public or foreign-owned attachment that side-steps the guard."""
        for rec in self:
            if rec.attachment_id:
                rec.attachment_id.sudo().write({
                    "res_model": rec._name, "res_id": rec.id, "public": False})
        return True

    def _require_compliance(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance") or self.env.su):
            raise AccessError(_("Only a compliance reviewer can verify or reject evidence."))

    def action_verify(self):
        self._require_compliance()
        for rec in self:
            if rec.state not in ("draft", "pending"):
                raise UserError(_("Only draft/pending evidence can be verified (%s).") % rec.name)
        self._apply({
            "state": "verified", "verified_by": self.env.uid, "verified_on": fields.Datetime.now(),
        })
        # A verified renewal now takes over from the document it supersedes. The
        # predecessor stayed effective until this moment, so merely drafting a
        # renewal never opened a coverage gap.
        for rec in self:
            predecessor = rec.supersedes_id
            if predecessor and predecessor.state == "verified":
                predecessor._apply({"state": "superseded", "superseded_by_id": rec.id})
        self._bump_subject_locks()
        return True

    def _bump_subject_locks(self):
        """A verification/revocation changes a subject's readiness: serialise on
        the shared vehicle/driver lock so a concurrent checkout cannot miss it."""
        constants.bump_resource_locks(
            self.env, self.mapped("vehicle_id").ids, self.mapped("driver_id").ids)

    def action_submit(self):
        self.filtered(lambda r: r.state == "draft").write({"state": "pending"})
        return True

    def action_reject(self):
        self._require_compliance()
        self._apply({
            "state": "rejected", "verified_by": self.env.uid, "verified_on": fields.Datetime.now(),
        })
        self._bump_subject_locks()
        return True

    def action_supersede(self, new_vals):
        """Stage a renewal that will supersede this verified document once the
        renewal is itself verified.

        The old, still-valid evidence remains effective until the renewal is
        verified (see action_verify). Drafting a renewal therefore never drops
        coverage. A renewal must keep the same subject and document kind as its
        predecessor -- caller-supplied subject/kind cannot redirect it.
        """
        self.ensure_one()
        self._require_compliance()
        if self.state != "verified":
            raise UserError(_("Only verified evidence can be superseded (%s).") % self.name)
        vals = dict(new_vals)
        # Enforce subject/kind continuity: the renewal is bound to this record's
        # subject, whatever the caller passed.
        vals["doc_kind"] = self.doc_kind
        vals["company_id"] = self.company_id.id
        for fname in ("operator_company_id", "vehicle_id", "driver_id"):
            vals.pop(fname, None)
        subject_field = {"operator": "operator_company_id", "vehicle": "vehicle_id",
                         "driver": "driver_id"}[self.subject_kind]
        vals[subject_field] = self[subject_field].id
        renewal = self.create(vals)
        renewal._apply({"supersedes_id": self.id})
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

    def _validity(self, start_dt, end_dt, tz):
        """Classify this evidence over [start, end) as one of:

        - 'not_verified': not in the verified state.
        - 'unknown'     : validity cannot be trusted -- a blank 'valid until' that
                          is not a reviewed non-expiring, or an imprecise date
                          (year/month/unknown precision). Blank != unlimited.
        - 'expired'     : verified with a real bound the interval falls outside.
        - 'covers'      : verified and valid for the whole interval.

        Date-only validity uses a local-day boundary in the operator's timezone
        ('valid until D' = through the end of day D), never an accidental UTC
        midnight.
        """
        self.ensure_one()
        if self.state != "verified":
            return "not_verified"
        # An imprecise date cannot be trusted to a day-accurate boundary.
        if self.date_precision in ("year", "month", "unknown"):
            return "unknown"
        from datetime import timedelta
        if self.date_start and start_dt < self._local_midnight(self.date_start, tz):
            return "expired"  # not yet effective for the whole interval
        if self.date_end:
            if end_dt > self._local_midnight(self.date_end + timedelta(days=1), tz):
                return "expired"
            return "covers"
        # No 'valid until': only a reviewed non-expiring counts; a blank does not.
        return "covers" if self.open_ended else "unknown"

    def _covers_interval(self, start_dt, end_dt, tz):
        """True if verified and valid for the WHOLE [start, end)."""
        self.ensure_one()
        return self._validity(start_dt, end_dt, tz) == "covers"

    def _expires_after(self, at_dt, tz):
        """True if a valid-until exists and falls after `at_dt` (a later renewal)."""
        self.ensure_one()
        if self.state != "verified" or not self.date_end:
            return False
        from datetime import timedelta
        return self._local_midnight(self.date_end + timedelta(days=1), tz) > at_dt
