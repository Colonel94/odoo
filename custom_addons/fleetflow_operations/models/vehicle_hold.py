# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


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
            hold.write({
                "state": "cleared", "cleared_by": self.env.uid,
                "cleared_on": fields.Datetime.now(), "clear_note": note.strip(),
            })
        return True
