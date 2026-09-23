# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from . import constants


class FleetflowVehicleHold(models.Model):
    """An explicit block on a vehicle, independent of any workflow stage.

    Holds are independent: clearing or cancelling one work order never clears an
    unrelated hold, and a hold survives until an authorised person clears it with
    a reason/evidence. A vehicle with several unresolved blocking holds does not
    become available because one was cleared.
    """
    _name = "fleetflow.vehicle.hold"
    _description = "FleetFlow Vehicle Hold"
    _inherit = ["mail.thread"]
    _check_company_auto = True
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    vehicle_id = fields.Many2one("fleet.vehicle", required=True, check_company=True, index=True, ondelete="restrict")
    company_id = fields.Many2one(related="vehicle_id.company_id", store=True, index=True)
    hold_type = fields.Selection(
        [("safety", "Safety / defect"), ("maintenance", "Maintenance"),
         ("document", "Document / compliance"), ("incident", "Incident"),
         ("admin", "Administrative")],
        required=True, default="maintenance", tracking=True,
    )
    reason = fields.Text(required=True)
    source_work_order_id = fields.Many2one("fleetflow.order", string="Source work order")
    reference = fields.Char(string="External reference")
    dispatch_blocking = fields.Boolean(
        default=True, tracking=True,
        help="If set, this hold blocks checkout while active.",
    )
    state = fields.Selection(
        [("active", "Active"), ("cleared", "Cleared")],
        default="active", required=True, tracking=True, copy=False,
    )
    created_by = fields.Many2one("res.users", readonly=True, default=lambda s: s.env.user, copy=False)
    cleared_by = fields.Many2one("res.users", readonly=True, copy=False)
    cleared_on = fields.Datetime(readonly=True, copy=False)
    clear_note = fields.Text(readonly=True, copy=False)
    clear_reason_input = fields.Text(string="Clearance note", copy=False,
                                     help="Reason/evidence; required to clear this hold.")

    def button_clear(self):
        """Form action: clear this hold using the entered clearance note."""
        for hold in self:
            hold.action_clear(note=hold.clear_reason_input)
        return True

    @api.depends("hold_type", "vehicle_id", "state")
    def _compute_name(self):
        for hold in self:
            hold.name = "%s hold — %s" % (
                dict(self._fields["hold_type"].selection).get(hold.hold_type, hold.hold_type),
                hold.vehicle_id.display_name or "?",
            )

    _PROTECTED = {"state", "cleared_by", "cleared_on", "clear_note"}

    @api.model_create_multi
    def create(self, vals_list):
        # A new hold always starts active with no clearance history, whatever the
        # caller or default_* context supplies.
        for vals in vals_list:
            vals["state"] = "active"
            for key in ("cleared_by", "cleared_on", "clear_note"):
                vals[key] = False
        records = super().create(vals_list)
        # A new hold can invalidate a concurrent checkout: bump the shared vehicle
        # lock so the two transactions serialise instead of both winning.
        constants.bump_resource_locks(self.env, records.mapped("vehicle_id").ids)
        return records

    def write(self, vals):
        # A hold is cleared only through action_clear (with a note); no context
        # flag opts out of this guard.
        if self._PROTECTED & set(vals):
            raise AccessError(_(
                "A hold is cleared through the Clear action (with a note), not by "
                "a direct edit."))
        return super().write(vals)

    def _apply(self, vals):
        return super().write(vals)

    def action_clear(self, note=None):
        """Clear THIS hold only. Requires fleet-manager rights and a note."""
        if not (self.env.user.has_group("fleetflow_operations.group_ops_fleet_manager")
                or self.env.su):
            raise AccessError(_("Only a fleet manager can clear a hold."))
        note = note or self.env.context.get("clear_note")
        for hold in self:
            if hold.state != "active":
                continue
            if not (note and note.strip()):
                raise UserError(_("Clearing a hold requires a reason/evidence note."))
            hold._apply({
                "state": "cleared", "cleared_by": self.env.uid,
                "cleared_on": fields.Datetime.now(), "clear_note": note.strip(),
            })
        # Clearing a blocking hold can re-enable dispatch: serialise on the vehicle.
        constants.bump_resource_locks(self.env, self.mapped("vehicle_id").ids)
        return True
