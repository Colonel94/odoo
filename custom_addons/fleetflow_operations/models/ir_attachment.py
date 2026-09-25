# -*- coding: utf-8 -*-
from odoo import models, _
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
    2. Verified-source immutability: once a file is the source of verified (or
       superseded) evidence, it cannot be overwritten, re-bound, made public,
       tokenised or deleted through generic attachment operations. A correction
       is a new evidence revision, not an in-place edit of the frozen source.

    This only adds restrictions on credential attachments; unrelated Odoo
    mail/assets/attachments are untouched.
    """
    _inherit = "ir.attachment"

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
        cred = self.env["fleetflow.credential"].sudo().browse(attachment_su.res_id)
        return bool(cred.exists()) and cred.state in ("verified", "superseded")

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
