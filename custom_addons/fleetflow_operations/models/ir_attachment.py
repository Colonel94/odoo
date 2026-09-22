# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import AccessError


class IrAttachment(models.Model):
    """Restrict compliance-evidence document files.

    A dispatcher legitimately reads credential metadata (kind, validity, state)
    to understand a blocker, but must not download the underlying private
    document (identity, licence, clearance). Only compliance reviewers and fleet
    managers may access the attached files. This does not weaken any existing
    access; it only adds a restriction on credential attachments.
    """
    _inherit = "ir.attachment"

    def check(self, mode, values=None):
        if not self.env.su and self:
            user = self.env.user
            privileged = (
                user.has_group("fleetflow_operations.group_ops_compliance")
                or user.has_group("fleetflow_operations.group_ops_fleet_manager")
            )
            if not privileged:
                for attachment in self.sudo():
                    if attachment.res_model == "fleetflow.credential":
                        raise AccessError(_(
                            "Compliance evidence documents are restricted to "
                            "compliance and fleet-manager roles."
                        ))
        return super().check(mode, values=values)
