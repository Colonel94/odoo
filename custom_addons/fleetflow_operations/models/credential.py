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
    # Durable marker: this evidence backed an approved decision at some point. It
    # is set at first verification and NEVER cleared, so its source file stays
    # protected through rejection, supersession, expiry or archival -- protection
    # is not based on the current state alone.
    ever_verified = fields.Boolean(readonly=True, copy=False, default=False)
    # Revocation/rejection attribution, recorded SEPARATELY from verification so a
    # rejection never overwrites who originally approved the evidence.
    revoked_by = fields.Many2one("res.users", readonly=True, copy=False)
    revoked_on = fields.Datetime(readonly=True, copy=False)
    revoke_reason = fields.Text(readonly=True, copy=False)
    # When this record's coverage was effectively taken over by its successor.
    replaced_on = fields.Datetime(readonly=True, copy=False)

    attachment_id = fields.Many2one(
        "ir.attachment", string="Document file", copy=False,
        help="The source document. Access is restricted to compliance/fleet roles.",
    )
    superseded_by_id = fields.Many2one("fleetflow.credential", string="Superseded by", readonly=True, copy=False)
    supersedes_id = fields.Many2one("fleetflow.credential", string="Supersedes", readonly=True, copy=False)
    note = fields.Text(
        groups="fleetflow_operations.group_ops_compliance,fleetflow_operations.group_ops_fleet_manager")

    # Fields that may never be forged through create/write/import/context.
    _PROTECTED = {"verified_by", "verified_on", "superseded_by_id", "supersedes_id",
                  "ever_verified", "revoked_by", "revoked_on", "revoke_reason",
                  "replaced_on"}

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
        # A verified/superseded/rejected record is historical: it cannot be
        # downgraded to draft/pending by a direct write and then re-edited and
        # re-verified (the "draft detour" that would rewrite an approved claim).
        # A correction is an explicit new revision (supersede), never an in-place
        # rewrite of the same historical record. Superuser is exempt.
        if "state" in vals and not self.env.su:
            for rec in self:
                if rec.state in ("verified", "superseded", "rejected"):
                    raise AccessError(_(
                        "Evidence %s is %s; its state cannot change by a direct "
                        "write. Supersede it with a new revision instead."
                    ) % (rec.name, rec.state))
        # A verified/superseded/rejected document's content is immutable except
        # through supersession (a new attributable revision).
        frozen = {"doc_kind", "operator_company_id", "vehicle_id", "driver_id",
                  "date_start", "date_end", "date_precision", "open_ended",
                  "reference", "issuer", "attachment_id"}
        if frozen & set(vals):
            for rec in self:
                if rec.state in ("verified", "superseded", "rejected"):
                    raise UserError(_(
                        "Evidence %s is %s and locked. Supersede it with a renewal "
                        "instead of editing it."
                    ) % (rec.name, rec.state))
        res = super().write(vals)
        if "attachment_id" in vals:
            self._bind_attachment()
        return res

    def unlink(self):
        # Evidence that has ever backed an approved decision (or is not a plain
        # unused draft/pending upload) is retained as history and cannot be
        # deleted -- deletion is never an alternative to revocation/supersession.
        # Superuser (fixtures/migration) is exempt.
        if not self.env.su:
            for rec in self:
                if rec.ever_verified or rec.state not in ("draft", "pending"):
                    raise UserError(_(
                        "Evidence %s has been reviewed and is retained as history; "
                        "it cannot be deleted. Reject/supersede it instead."
                    ) % rec.name)
        return super().unlink()

    def _apply(self, vals):
        # Internal transition used by the review actions; bypasses the public
        # write guard by writing at the ORM level.
        return super().write(vals)

    # Evidence document policy: allowed types (validated on the real bytes, not
    # the filename) and a hard size ceiling. Active/script content is rejected.
    _EVIDENCE_MAX_BYTES = 15 * 1024 * 1024
    _EVIDENCE_MAGIC = (
        (b"%PDF-", "PDF"),
        (b"\xff\xd8\xff", "JPEG"),
        (b"\x89PNG\r\n\x1a\n", "PNG"),
    )

    def _bind_attachment(self):
        """Safely bind a linked document file to THIS credential.

        There is NO blanket sudo reparenting of an arbitrary attachment id. Before
        anything is changed we verify -- with the CALLER's own rights, never sudo
        -- that the file is theirs to bind: the caller can write it, it is either
        unbound or already this credential's, it belongs to this company, it is not
        the source of other verified evidence, and it passes the type/size/content
        policy. A file that fails any check is rejected and left completely
        unchanged (owner, binding, bytes, public flag and access token intact).
        Only after every check passes is the file privatised and pinned here.
        """
        for rec in self:
            att = rec.attachment_id
            if not att:
                continue
            # 1) The caller must be able to write the source file. This runs as
            #    the caller: another user's private upload, or an id they cannot
            #    access, raises here and nothing is modified.
            att.check("write")
            att_su = att.sudo()
            # 2) Unbound, or already bound to THIS credential -- never reparent a
            #    file that already belongs to another record.
            if att_su.res_model and not (
                    att_su.res_model == rec._name and att_su.res_id == rec.id):
                raise UserError(_(
                    "That file is already attached to another record and cannot be "
                    "reused as evidence. Upload the document to this credential."))
            # 3) Company ownership must match.
            if att_su.company_id and att_su.company_id.id != rec.company_id.id:
                raise UserError(_("That file belongs to another company."))
            # 4) Type / size / actual-content policy.
            rec._validate_evidence_file(att_su)
            # Passed: privatise, drop any public token and pin ownership here.
            att_su.write({
                "res_model": rec._name, "res_id": rec.id,
                "company_id": rec.company_id.id, "public": False,
                "access_token": False,
            })
        return True

    # Interactive/active PDF constructs that have no place in static evidence.
    _PDF_BANNED = (b"/JavaScript", b"/JS", b"/Launch", b"/OpenAction", b"/AA",
                   b"/EmbeddedFile", b"/RichMedia", b"/AcroForm")
    _IMAGE_MAX_PIXELS = 40_000_000  # bounded decompression (header dimensions)

    def _validate_evidence_file(self, att_su):
        """Reject empty, oversized or non-document content, judged on the real
        bytes -- a valid-looking prefix is not enough. PDFs are structurally
        sanity-checked and rejected if they carry active/embedded content; images
        are parsed (header only) with a bounded pixel budget. This is a document
        policy, not a malware scanner, and never executes the content."""
        import base64
        data = att_su.raw or (base64.b64decode(att_su.datas) if att_su.datas else b"")
        if not data:
            raise UserError(_("The evidence file is empty."))
        if len(data) > self._EVIDENCE_MAX_BYTES:
            raise UserError(_("The evidence file exceeds the %d MB limit.")
                            % (self._EVIDENCE_MAX_BYTES // (1024 * 1024)))
        kind = next((label for magic, label in self._EVIDENCE_MAGIC
                     if data.startswith(magic)), None)
        if not kind:
            raise UserError(_(
                "Evidence must be a PDF, JPEG or PNG document; active or script "
                "content is not accepted."))
        if kind == "PDF":
            self._validate_pdf_bytes(data)
        else:
            self._validate_image_bytes(data)
        return True

    def _validate_pdf_bytes(self, data):
        if b"%%EOF" not in data[-4096:]:
            raise UserError(_(
                "The PDF is malformed (no end-of-file marker); a valid-looking "
                "prefix is not a valid document."))
        for tok in self._PDF_BANNED:
            if tok in data:
                raise UserError(_(
                    "The PDF carries active or embedded content (%s), which is not "
                    "allowed in evidence.") % tok.decode())

    def _validate_image_bytes(self, data):
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            width, height = img.size
            if width * height > self._IMAGE_MAX_PIXELS:
                raise UserError(_("The image dimensions exceed the allowed limit."))
            img.verify()  # structural integrity, no full pixel decode
        except UserError:
            raise
        except Exception:
            raise UserError(_("The image file is malformed or unsupported."))

    def _require_compliance(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance") or self.env.su):
            raise AccessError(_("Only a compliance reviewer can verify or reject evidence."))

    def action_verify(self):
        self._require_compliance()
        for rec in self:
            if rec.state not in ("draft", "pending"):
                raise UserError(_("Only draft/pending evidence can be verified (%s).") % rec.name)
        now = fields.Datetime.now()
        # Re-validate the source file against its CURRENT bytes immediately before
        # verifying, under a row lock. This closes two gaps: a file edited after
        # linking cannot slip past the approval-time policy, and a concurrent
        # mutation cannot leave verified evidence pointing at different bytes (once
        # verified, ever_verified freezes the source so no later write can diverge).
        for rec in self:
            if rec.attachment_id:
                self.env.cr.execute(
                    "SELECT id FROM ir_attachment WHERE id = %s FOR UPDATE",
                    (rec.attachment_id.id,))
                rec.attachment_id.invalidate_recordset(["raw", "datas"])
                rec._validate_evidence_file(rec.attachment_id.sudo())
        self._apply({
            "state": "verified", "verified_by": self.env.uid, "verified_on": now,
            "ever_verified": True,
        })
        # A verified renewal takes over from the document it supersedes -- but only
        # the RELATIONSHIP is recorded here; coverage is decided per requested
        # interval by effective dates (see _validity). A future-effective renewal
        # therefore does not remove the predecessor's still-valid current coverage.
        for rec in self:
            predecessor = rec.supersedes_id
            if predecessor and predecessor.state == "verified":
                predecessor._apply({"state": "superseded", "superseded_by_id": rec.id,
                                    "replaced_on": now})
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

    def action_reject(self, reason=None):
        """Reject a pending upload, or revoke a previously verified document.

        Revocation records its OWN actor/time/reason and never overwrites the
        original verification attribution. A once-verified record keeps
        ever_verified=True, so revoking it neither unlocks its source file nor
        resurrects its coverage (a rejected record provides no coverage)."""
        self._require_compliance()
        reason = reason or self.env.context.get("revoke_reason")
        self._apply({
            "state": "rejected", "revoked_by": self.env.uid,
            "revoked_on": fields.Datetime.now(),
            "revoke_reason": reason or _("(no reason recorded)"),
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
        # Return a serializable id (not a recordset) so the workflow can be driven
        # through the authenticated JSON-RPC API and the caller can load the
        # renewal without injecting the protected supersedes link by hand.
        return renewal.id

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
        # Coverage is provided by a record that was legitimately approved and not
        # revoked: 'verified' (current) or 'superseded' (replaced, but its own
        # effective interval remains historically valid). A rejected/revoked or
        # never-verified record provides NO coverage -- revoked coverage is never
        # resurrected. The effective interval below then bounds it, so a
        # future-effective renewal only covers its own window.
        if self.state not in ("verified", "superseded"):
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
