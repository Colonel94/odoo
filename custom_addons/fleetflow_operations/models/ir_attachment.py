# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError


# Attachment fields whose change would move, expose, replace or orphan the file.
_MUTATING_FIELDS = {"raw", "datas", "db_datas", "store_fname", "mimetype",
                    "res_model", "res_id", "res_field", "public", "access_token",
                    "company_id", "url", "type", "name"}


class IrAttachment(models.Model):
    """Restrict and protect compliance-evidence document files.

    Two guarantees on files bound to a fleetflow.credential:
    1. Read access: a dispatcher legitimately reads credential metadata (kind,
       validity, state) to understand a blocker, but must not download the
       underlying private document (identity, licence, clearance). Only
       compliance reviewers and fleet managers may access the attached files.
    2. Approved-source immutability (durable): once a file has backed an approved
       decision (the credential's ever_verified marker), it cannot be overwritten,
       re-bound, made public, tokenised or deleted through generic attachment
       operations -- and this survives rejection/revocation, supersession, expiry
       and archival. Protection is keyed on that durable history, NOT on the
       credential's current state, so revoking evidence never re-opens its source.
       A correction is a new evidence revision, not an in-place edit.

    This only adds restrictions on credential attachments; unrelated Odoo
    mail/assets/attachments are untouched.
    """
    _inherit = "ir.attachment"

    # Version counter bumped inside the verification transaction (see
    # constants.bump_attachment_source_locks). It exists so that approving a
    # credential is a committed write on its source row: a concurrent writer that
    # observed the credential while still unverified and then mutates this file
    # conflicts on this row (first-updater-wins under REPEATABLE READ) instead of
    # slipping a change past approval. Only added on credential evidence files;
    # unrelated attachments simply carry a null counter.
    ff_source_lock = fields.Integer(
        string="Evidence source lock counter", default=0, copy=False)

    def check(self, mode, values=None):
        if not self.env.su and self:
            user = self.env.user
            privileged = (
                user.has_group("fleetflow_operations.group_ops_compliance")
                or user.has_group("fleetflow_operations.group_ops_fleet_manager")
            )
            for attachment in self.sudo():
                if attachment.res_model != "fleetflow.credential":
                    continue
                if not privileged:
                    raise AccessError(_(
                        "Compliance evidence documents are restricted to "
                        "compliance and fleet-manager roles."
                    ))
                # A privileged role is not enough on its own: the caller must also
                # be able to access the underlying credential record, which is
                # company-isolated. A reviewer of ANOTHER company therefore cannot
                # fetch this file by guessing its id.
                cred = self.env["fleetflow.credential"].browse(attachment.res_id)
                if cred.exists():
                    try:
                        cred.check_access_rights("read")
                        cred.check_access_rule("read")
                    except AccessError:
                        raise AccessError(_(
                            "This evidence document belongs to another company."))
                if mode in ("write", "unlink", "create") and self._ff_is_frozen_source(attachment):
                    raise AccessError(_(
                        "This file is the source of verified evidence and cannot "
                        "be altered, re-bound, published or deleted. Supersede the "
                        "evidence with a new revision instead."
                    ))
        return super().check(mode, values=values)

    def _ff_is_frozen_source(self, attachment_su):
        # Durable: a file that has EVER backed an approved decision stays frozen,
        # regardless of the credential's current state (rejected/revoked/expired/
        # archived included). Rejection disables use; it never unlocks the source.
        cred = self.env["fleetflow.credential"].sudo().browse(attachment_su.res_id)
        return bool(cred.exists()) and cred.ever_verified

    def write(self, vals):
        # Belt-and-suspenders around a frozen verified-evidence source: even a
        # compliance user (who passes check()) cannot mutate the stored bytes,
        # binding, public flag or token of a file backing verified evidence.
        if not self.env.su and (_MUTATING_FIELDS & set(vals)):
            for att in self.sudo():
                if att.res_model == "fleetflow.credential" and self._ff_is_frozen_source(att):
                    raise AccessError(_(
                        "This file is the source of verified evidence and is "
                        "immutable. Supersede the evidence with a new revision."
                    ))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            for att in self.sudo():
                if att.res_model == "fleetflow.credential" and self._ff_is_frozen_source(att):
                    raise AccessError(_(
                        "This file is the source of verified evidence and cannot "
                        "be deleted. Supersede the evidence with a new revision."
                    ))
        return super().unlink()
