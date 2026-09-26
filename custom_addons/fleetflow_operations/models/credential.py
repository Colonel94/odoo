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

    # Prohibited PDF features, enforced SEMANTICALLY over the parsed object graph
    # (resolved indirect objects, normalised names), never by a raw byte match --
    # so ordinary page text that merely mentions a keyword is fine, while an
    # escaped name or an indirect reference cannot smuggle the feature past us.
    # This preserves the prior prohibition on JavaScript/actions, embedded files,
    # rich media and AcroForm content.
    _PDF_BANNED_KEYS = frozenset({
        "/JS", "/JavaScript", "/AA", "/OpenAction", "/AcroForm", "/RichMedia",
        "/EmbeddedFiles", "/EF"})
    _PDF_BANNED_ACTIONS = frozenset({"/JavaScript", "/Launch"})  # action /S subtype
    _PDF_BANNED_TYPES = frozenset({  # /Type or /Subtype values
        "/EmbeddedFile", "/Filespec", "/RichMedia", "/Screen", "/Movie"})
    # Traversal budgets (bound our own work; the input-size cap bounds the parse).
    _PDF_MAX_PAGES = 4000
    _PDF_MAX_OBJECTS = 60000
    _PDF_MAX_DEPTH = 60
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
        """Structurally validate a PDF with the runtime parser (PyPDF2 1.26.0, the
        version shipped in the odoo:16.0 image) and reject prohibited features
        found in the parsed object graph.

        Strictness/recovery: opened with strict=False (the parser tolerates minor
        deviations real scanners emit), but successful construction is NOT treated
        as success -- we additionally require a readable page tree and walk the
        catalog. Encrypted documents cannot be inspected and are rejected (no
        password handling is added). Malformed/unsupported structures that cannot
        be inspected with confidence are rejected. The document is never executed
        and stream data is never decoded (no external access, no rewrite).

        Bounds: the 15 MB input cap bounds the parse; the traversal is separately
        bounded by object/reference/depth/page budgets. See OPS1 evidence for the
        one retained limitation (PyPDF2's own parse time is not sandboxed).
        """
        import io
        import struct
        try:
            from PyPDF2 import PdfFileReader
            from PyPDF2.utils import PdfReadError
        except ImportError:  # fail closed -- never accept unvalidated bytes
            raise UserError(_("PDF validation is unavailable on this server."))
        # Expected malformed-document failures from the parser/our traversal, turned
        # into a clear business rejection. Programming-defect exceptions
        # (AttributeError/TypeError/NameError) are deliberately NOT caught here, so a
        # bug is not disguised as an ordinary rejection.
        parse_errors = (PdfReadError, ValueError, KeyError, IndexError,
                        AssertionError, EOFError, RecursionError, OverflowError,
                        struct.error)
        try:
            reader = PdfFileReader(io.BytesIO(data), strict=False)
            if reader.isEncrypted:
                raise UserError(_(
                    "Encrypted or password-protected PDFs cannot be inspected and "
                    "are not accepted as evidence."))
            npages = reader.getNumPages()  # walks/validates the page tree
            if npages < 1:
                raise UserError(_("The PDF has no readable pages."))
            if npages > self._PDF_MAX_PAGES:
                raise UserError(_("The PDF has too many pages to validate (%d).")
                                % npages)
            root = reader.trailer.get("/Root")
            if root is None:
                raise UserError(_("The PDF has no document catalog."))
            self._pdf_scan_prohibited(root)
        except UserError:
            raise
        except parse_errors as exc:
            raise UserError(_(
                "The PDF is malformed or uses a structure that cannot be validated "
                "(%s).") % type(exc).__name__)

    @staticmethod
    def _pdf_norm_name(name):
        """Normalise a PDF name, decoding #xx hex escapes, so a spelling variation
        such as /J#61vaScript is compared as /JavaScript."""
        import re
        s = str(name)
        if "#" in s:
            s = re.sub(r"#([0-9A-Fa-f]{2})",
                       lambda m: chr(int(m.group(1), 16)), s)
        return s

    def _pdf_check_dict(self, dico):
        norm = {self._pdf_norm_name(k): v for k, v in dico.items()}
        banned = set(norm) & self._PDF_BANNED_KEYS
        if banned:
            raise UserError(_(
                "The PDF carries a prohibited feature (%s), which is not allowed in "
                "static evidence.") % ", ".join(sorted(banned)))
        action = norm.get("/S")
        if action is not None and self._pdf_norm_name(action) in self._PDF_BANNED_ACTIONS:
            raise UserError(_(
                "The PDF carries a prohibited action (%s).")
                % self._pdf_norm_name(action))
        for key in ("/Type", "/Subtype"):
            value = norm.get(key)
            if value is not None and self._pdf_norm_name(value) in self._PDF_BANNED_TYPES:
                raise UserError(_(
                    "The PDF carries a prohibited object type (%s).")
                    % self._pdf_norm_name(value))

    def _pdf_scan_prohibited(self, root):
        """Bounded walk of the reachable object graph from the catalog, resolving
        indirect objects (and object streams, transparently via the parser). Does
        NOT stop at the top-level dictionary or the first page, and never decodes
        stream data."""
        from PyPDF2.generic import IndirectObject, DictionaryObject, ArrayObject
        seen, stack, visited = set(), [(root, 0)], 0
        while stack:
            obj, depth = stack.pop()
            if depth > self._PDF_MAX_DEPTH:
                raise UserError(_("The PDF nesting is too deep to validate."))
            if isinstance(obj, IndirectObject):
                ref = (obj.idnum, obj.generation)
                if ref in seen:
                    continue
                seen.add(ref)
                obj = obj.getObject()  # resolves classic/xref-stream/object-stream
                visited += 1
                if visited > self._PDF_MAX_OBJECTS:
                    raise UserError(_("The PDF has too many objects to validate."))
            if isinstance(obj, DictionaryObject):
                self._pdf_check_dict(obj)
                for value in obj.values():
                    stack.append((value, depth + 1))
            elif isinstance(obj, ArrayObject):
                for value in obj:
                    stack.append((value, depth + 1))

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
            # A linked renewal establishes the predecessor's effective cutover from
            # its OWN effective start; approving it without a precise 'Valid from'
            # would leave the cutover ambiguous. Refuse rather than guess today's
            # date (F): record a precise effective date or return it for review.
            if rec.supersedes_id and (not rec.date_start or rec.date_precision != "day"):
                raise UserError(_(
                    "Evidence %s replaces an earlier document, so it needs a precise "
                    "effective (Valid from) date before it can be approved. Record "
                    "one, or return it for review.") % rec.name)
        now = fields.Datetime.now()
        # Re-validate the source file against its CURRENT bytes immediately before
        # verifying, under a row lock, THEN bump the source-lock counter so the
        # approval is a committed write on that row. This closes two gaps: a file
        # edited after linking cannot slip past the approval-time policy; and a
        # writer that observed the still-unverified credential on an older snapshot
        # cannot commit a competing attachment mutation after approval -- its write
        # now conflicts on the same row (first-updater-wins under REPEATABLE READ),
        # so verified evidence can never end up pointing at unvalidated bytes.
        att_ids = sorted(self.mapped("attachment_id").ids)
        for att_id in att_ids:
            self.env.cr.execute(
                "SELECT id FROM ir_attachment WHERE id = %s FOR UPDATE", (att_id,))
        for rec in self:
            if rec.attachment_id:
                rec.attachment_id.invalidate_recordset(["raw", "datas"])
                rec._validate_evidence_file(rec.attachment_id.sudo())
        self._apply({
            "state": "verified", "verified_by": self.env.uid, "verified_on": now,
            "ever_verified": True,
        })
        constants.bump_attachment_source_locks(self.env, att_ids)
        # A verified renewal takes over from the document it supersedes -- but only
        # the RELATIONSHIP + attribution are recorded here; coverage is then decided
        # per requested interval by effective dates (see _effective_interval). The
        # predecessor row is locked FOR UPDATE first so two reviewers approving
        # competing successors concurrently cannot both win: the second sees the
        # predecessor already replaced (or fails to serialise and retries), and one
        # unambiguous chain results. A predecessor that is no longer verified (e.g.
        # revoked in the meantime) is never resurrected.
        for rec in self:
            predecessor = rec.supersedes_id
            if not predecessor:
                continue
            self.env.cr.execute(
                "SELECT id FROM fleetflow_credential WHERE id = %s FOR UPDATE",
                (predecessor.id,))
            predecessor.invalidate_recordset(["state", "superseded_by_id"])
            if (predecessor.state == "superseded"
                    and predecessor.superseded_by_id != rec):
                raise UserError(_(
                    "Evidence %s has already been replaced by another approved "
                    "renewal. Resolve the conflicting replacement chain before "
                    "approving this one.") % predecessor.name)
            if predecessor.state == "verified":
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

    def _cutover(self, tz):
        """The reviewed effective cutover of a superseded record: the moment its
        successor takes over, i.e. the successor's own effective start (Valid from).

        Derived from the LINKED successor (an immutable, verified record whose
        subject/kind continuity was enforced at supersession), so it cannot move
        because the successor is later expired, revoked, rejected or archived, and
        it is never confused with the approval timestamp. Returns None when the
        successor gives no precise effective date -- ambiguity is surfaced for
        review, never guessed (no silent 'today').
        """
        self.ensure_one()
        succ = self.superseded_by_id
        if not succ or not succ.date_start or succ.date_precision != "day":
            return None
        return self._local_midnight(succ.date_start, tz)

    def _effective_interval(self, tz):
        """Return (eff_start, eff_end, reliable): the half-open [eff_start, eff_end)
        over which THIS record is trusted operating evidence, as tz-aware datetimes
        (None = unbounded on that side).

        A verified record is bounded by its own precise validity (or unbounded when
        a reviewer marked it non-expiring). A superseded record's authority ENDS at
        its cutover -- it never falls back to its own printed expiry for a period
        assigned to its successor. reliable=False means the record supplies no
        trustworthy coverage (not verified/superseded, an imprecise/blank date, or a
        superseded record whose cutover is ambiguous); such a record is surfaced for
        review rather than silently granting eligibility.
        """
        self.ensure_one()
        if self.state not in ("verified", "superseded"):
            return (None, None, False)
        if self.date_precision in ("year", "month", "unknown"):
            return (None, None, False)
        from datetime import timedelta
        eff_start = self._local_midnight(self.date_start, tz) if self.date_start else None
        if self.date_end:
            eff_end = self._local_midnight(self.date_end + timedelta(days=1), tz)
        elif self.open_ended:
            eff_end = None  # reviewed non-expiring
        else:
            return (None, None, False)  # blank 'valid until' != unlimited
        if self.state == "superseded":
            cutover = self._cutover(tz)
            if cutover is None:
                return (None, None, False)  # ambiguous replacement -> needs review
            eff_end = cutover if eff_end is None else min(eff_end, cutover)
            if eff_start is not None and eff_end <= eff_start:
                return (None, None, False)
        return (eff_start, eff_end, True)

    def _validity(self, start_dt, end_dt, tz):
        """Classify this SINGLE record over [start, end) as one of:

        - 'not_verified': not in the verified/superseded lifecycle.
        - 'unknown'     : verified/superseded but its effective interval cannot be
                          trusted (blank non-reviewed expiry, imprecise date, or a
                          superseded record with an ambiguous cutover).
        - 'expired'     : effective, but the interval falls outside it (expired, not
                          yet effective, or past the record's cutover).
        - 'covers'      : effective for the whole interval on its own.

        Date-only validity uses a local-day boundary in the operator's timezone
        ('valid until D' = through the end of day D), with half-open boundaries.
        """
        self.ensure_one()
        if self.state not in ("verified", "superseded"):
            return "not_verified"
        if self.date_precision in ("year", "month", "unknown"):
            return "unknown"
        eff_start, eff_end, reliable = self._effective_interval(tz)
        if not reliable:
            return "unknown"
        if eff_start is not None and start_dt < eff_start:
            return "expired"  # not yet effective for the whole interval
        if eff_end is not None and end_dt > eff_end:
            return "expired"  # expired, or authority ended at the cutover
        return "covers"

    @api.model
    def _resolve_coverage(self, creds, start_dt, end_dt, tz):
        """Return an ordered recordset [oldest..newest] whose EFFECTIVE intervals
        together cover the whole [start, end), or an empty recordset if they do not.

        Coverage is satisfied by a single record when possible, otherwise ONLY by a
        continuous reviewed-renewal chain (records linked by supersession). This
        deliberately never bridges a genuine validity gap and never combines
        unrelated records as if they were a renewal chain. Selection is independent
        of record/search order.
        """
        info = {}
        for cred in creds:
            eff_start, eff_end, reliable = cred._effective_interval(tz)
            if reliable:
                info[cred.id] = (eff_start, eff_end)

        def active_at(cred, pos):
            eff_start, eff_end = info[cred.id]
            return ((eff_start is None or eff_start <= pos)
                    and (eff_end is None or pos < eff_end))

        def reaches(cred, pos):
            eff_end = info[cred.id][1]
            return eff_end is None or eff_end >= pos

        contributors = creds.filtered(lambda c: c.id in info)
        # 1) A single record covering the whole interval (prefer the current head).
        for cred in contributors.sorted(key=lambda c: (c.state != "verified", c.id)):
            if active_at(cred, start_dt) and reaches(cred, end_dt):
                return cred
        # 2) A continuous reviewed-renewal chain: from a record active at `start`,
        #    follow superseded_by_id, requiring each successor to pick up exactly
        #    where the predecessor's authority ends (no gap, no unrelated record).
        Empty = self.env["fleetflow.credential"]
        starters = contributors.filtered(lambda c: active_at(c, start_dt))
        for starter in starters.sorted(key=lambda c: (c.id,)):
            selected = Empty
            current = starter
            pos = start_dt
            guard = 0
            while current is not None and guard < 64:
                guard += 1
                selected |= current
                eff_end = info[current.id][1]
                pos = end_dt if eff_end is None else eff_end
                if pos >= end_dt:
                    return selected
                succ = current.superseded_by_id
                if (succ and succ.id in info and active_at(succ, pos)):
                    current = succ
                else:
                    current = None  # gap or broken chain: this starter fails
        return Empty

    def _covers_interval(self, start_dt, end_dt, tz):
        """True if this single record is effective for the WHOLE [start, end)."""
        self.ensure_one()
        return self._validity(start_dt, end_dt, tz) == "covers"

    def _expires_after(self, at_dt, tz):
        """True if a valid-until exists and falls after `at_dt` (a later renewal)."""
        self.ensure_one()
        if self.state != "verified" or not self.date_end:
            return False
        from datetime import timedelta
        return self._local_midnight(self.date_end + timedelta(days=1), tz) > at_dt
