# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants


class FleetflowCustodyEvent(models.Model):
    """An immutable, attributable record of a PHYSICAL vehicle handover.

    A reservation (fleetflow.allocation) is a plan; a custody event is what
    actually happened: a vehicle physically leaving with a driver (checkout) or
    coming back (return), at an authoritative server time, by a named actor, with
    the odometer / energy / condition captured then. These facts are frozen at
    creation -- no ordinary write/import/copy/default context can rewrite who had
    the vehicle, when, or with what mileage. A mistake is corrected by recording a
    NEW, separately attributable correction event that points at the original, never
    by editing history. This is deliberately specific to fleet custody, not a
    general ledger framework.
    """
    _name = "fleetflow.custody.event"
    _description = "FleetFlow Custody Event"
    _inherit = ["mail.thread"]
    _check_company_auto = True
    _order = "event_time desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    allocation_id = fields.Many2one(
        "fleetflow.allocation", required=True, index=True, ondelete="restrict",
        string="Allocation")
    vehicle_id = fields.Many2one(
        "fleet.vehicle", required=True, index=True, check_company=True, ondelete="restrict")
    driver_id = fields.Many2one(
        "fleetflow.driver", index=True, check_company=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, index=True)
    event_type = fields.Selection(constants.CUSTODY_EVENT_TYPES, required=True, index=True)

    # Authoritative server time and actor -- both forged-proof (see create/write).
    # A live event is always attributed; performed_by is left empty ONLY for legacy
    # events reconstructed by migration, where the handover actor was never recorded
    # (see _check_actor). We never fabricate an actor for old data.
    event_time = fields.Datetime(required=True, readonly=True, index=True)
    performed_by = fields.Many2one("res.users", readonly=True)

    # Captured operational measurements.
    odometer = fields.Float(string="Odometer (reported)", readonly=True)
    odometer_unit = fields.Selection(constants.ODOMETER_UNITS, default="km", readonly=True)
    # Canonical distance for comparisons; 100 mi is never compared with 100 km.
    odometer_km = fields.Float(string="Odometer (km, canonical)", readonly=True)
    energy_kind = fields.Selection(constants.ENERGY_KINDS, readonly=True)
    energy_level = fields.Integer(string="Energy level (%)", readonly=True)
    fuel_note = fields.Char(readonly=True, help="Free-text fuel/charge note retained for audit.")
    condition = fields.Selection(constants.CONDITION_CODES, readonly=True)
    defect = fields.Boolean(readonly=True)
    notes = fields.Text(readonly=True)

    # Provenance to the actionable follow-up raised from a return defect.
    hold_id = fields.Many2one("fleetflow.vehicle.hold", readonly=True, string="Blocking hold")
    order_id = fields.Many2one("fleetflow.order", readonly=True, string="Work order")

    # Attributable correction/reversal: a NEW event that supersedes an earlier one.
    corrects_id = fields.Many2one("fleetflow.custody.event", readonly=True, string="Corrects")
    correction_reason = fields.Text(readonly=True)
    corrected_by_ids = fields.One2many("fleetflow.custody.event", "corrects_id",
                                       string="Corrections")

    # Legacy provenance: events reconstructed by migration from pre-custody-event
    # allocation fields. Precision that was never recorded is marked unknown, never
    # fabricated.
    is_legacy = fields.Boolean(readonly=True, default=False,
                               help="Reconstructed from pre-OPS-2A allocation data.")
    legacy_source = fields.Char(readonly=True)

    # Fields that ARE the historical fact: frozen after creation. A correction is a
    # new attributable event, never an edit. hold_id/order_id are linked once by the
    # workflow via _apply and are not public inputs.
    _IMMUTABLE = {
        "allocation_id", "vehicle_id", "driver_id", "company_id", "event_type",
        "event_time", "performed_by", "odometer", "odometer_unit", "odometer_km",
        "energy_kind", "energy_level", "fuel_note", "condition", "defect", "notes",
        "corrects_id", "correction_reason", "is_legacy", "legacy_source",
    }

    @api.depends("event_type", "vehicle_id", "event_time")
    def _compute_name(self):
        labels = dict(constants.CUSTODY_EVENT_TYPES)
        for ev in self:
            ev.name = "%s — %s — %s" % (
                labels.get(ev.event_type, ev.event_type or "?"),
                ev.vehicle_id.display_name or "?", ev.event_time or "")

    @api.constrains("energy_level")
    def _check_energy_level(self):
        for ev in self:
            if ev.energy_level and not (0 <= ev.energy_level <= 100):
                raise ValidationError(_("Energy level must be a percentage between 0 and 100."))

    @api.constrains("performed_by", "is_legacy")
    def _check_actor(self):
        for ev in self:
            if not ev.performed_by and not ev.is_legacy:
                raise ValidationError(_(
                    "A live custody event must record who performed the handover."))

    @staticmethod
    def _to_km(value, unit):
        if value is None:
            return None
        return value * constants.MI_TO_KM if unit == "mi" else float(value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # The server time and the acting user are authoritative. An ordinary
            # caller can never forge them: outside superuser (migration) the event
            # time is stamped now and the actor is the current user, whatever the
            # payload/default context said. Migration (su) may supply a recorded
            # historical time/actor, or leave the actor unknown by passing it
            # explicitly as False.
            if not self.env.su:
                vals["event_time"] = fields.Datetime.now()
                vals["performed_by"] = self.env.uid
                vals["is_legacy"] = False
            else:
                vals.setdefault("event_time", fields.Datetime.now())
                vals.setdefault("performed_by", self.env.uid)
            # Canonical km is derived, never trusted from the caller.
            vals["odometer_km"] = self._to_km(vals.get("odometer"), vals.get("odometer_unit") or "km")
        return super().create(vals_list)

    def write(self, vals):
        # Custody facts are immutable. Record a correction event instead of editing
        # history. Only the internal workflow link (_apply) may set hold/order, and
        # only mail/activity system fields pass through.
        if self._IMMUTABLE & set(vals):
            raise AccessError(_(
                "A custody event is an immutable record of what physically happened. "
                "Record a correction event instead of editing it."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_(
                "A custody event is permanent history and cannot be deleted."))
        return super().unlink()

    def _apply(self, vals):
        # Internal, workflow-only write (links the follow-up hold/order); bypasses
        # the public immutability guard.
        return super().write(vals)

    def action_correct(self, reason, **measurements):
        """Record an attributable correction: a NEW event that supersedes this one.

        The original is never altered. Only a fleet manager may correct custody
        history, and a reason is required. Returns the new event's id.
        """
        self.ensure_one()
        if not (self.env.user.has_group("fleetflow_operations.group_ops_fleet_manager")
                or self.env.su):
            raise AccessError(_("Only a fleet manager can correct a custody record."))
        if not (reason and reason.strip()):
            raise UserError(_("A correction requires a reason."))
        vals = {
            "allocation_id": self.allocation_id.id, "vehicle_id": self.vehicle_id.id,
            "driver_id": self.driver_id.id, "company_id": self.company_id.id,
            "event_type": self.event_type, "corrects_id": self.id,
            "correction_reason": reason.strip(),
            "odometer": measurements.get("odometer", self.odometer),
            "odometer_unit": measurements.get("odometer_unit", self.odometer_unit),
            "energy_kind": measurements.get("energy_kind", self.energy_kind),
            "energy_level": measurements.get("energy_level", self.energy_level),
            "condition": measurements.get("condition", self.condition),
            "defect": measurements.get("defect", self.defect),
            "notes": measurements.get("notes", self.notes),
        }
        correction = self.sudo().create(vals)
        return correction.id
