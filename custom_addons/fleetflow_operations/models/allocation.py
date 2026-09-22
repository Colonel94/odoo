# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants

ACTIVE_STATES = ("confirmed", "checked_out")


class FleetflowAllocation(models.Model):
    """A vehicle (and optional driver) reservation with real custody.

    A future reservation, a driver shift and a vehicle physically out are
    distinct states. Confirm and checkout recompute readiness and check resource
    conflicts inside one transaction that locks the persistent vehicle/driver
    rows, so two competing requests cannot both win. A planned end time does not
    prove a return: an unreturned custody keeps blocking later checkout.
    """
    _name = "fleetflow.allocation"
    _description = "FleetFlow Allocation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "planned_start desc, id desc"

    name = fields.Char(default=lambda s: _("New"), required=True, copy=False, readonly=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda s: s.env.company, index=True)
    operating_mode = fields.Selection(constants.OPERATING_MODES, required=True, default="chauffeur")
    vehicle_id = fields.Many2one("fleet.vehicle", required=True, check_company=True, index=True, ondelete="restrict")
    driver_id = fields.Many2one("fleetflow.driver", check_company=True, index=True, ondelete="restrict")
    channel_enrolment_ids = fields.Many2many("fleetflow.channel.enrolment", string="Channel products")

    planned_start = fields.Datetime(required=True)
    planned_end = fields.Datetime(required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("checked_out", "Checked out"),
         ("returned", "Returned"), ("cancelled", "Cancelled")],
        default="draft", required=True, tracking=True, copy=False, index=True,
    )

    # Actual custody (physical), distinct from the plan.
    custody_out_at = fields.Datetime(readonly=True, copy=False)
    custody_in_at = fields.Datetime(readonly=True, copy=False)
    confirmed_by = fields.Many2one("res.users", readonly=True, copy=False)

    # Frozen decision snapshot for audit; current readiness is computed separately.
    readiness_status = fields.Selection(constants.READINESS_STATES, readonly=True, copy=False)
    readiness_snapshot = fields.Text(readonly=True, copy=False)
    readiness_version = fields.Char(readonly=True, copy=False)

    # Checkout / return records (captured in-form, consumed by the actions).
    checkout_odometer = fields.Float(copy=False)
    return_odometer = fields.Float(copy=False)
    odometer_unit = fields.Selection([("km", "km"), ("mi", "mi")], default="km")
    return_fuel = fields.Char(copy=False)
    return_condition = fields.Text(copy=False)
    return_defect = fields.Boolean(copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("fleetflow.allocation") or _("New")
            # A new allocation always starts draft with no custody/readiness,
            # whatever the caller or default_* context says. Set False explicitly
            # (not pop) so a default_<field> context key cannot refill it.
            for key in self._PROTECTED:
                vals[key] = False
            vals["state"] = "draft"
        return super().create(vals_list)

    # State/custody/readiness are advanced ONLY through the workflow actions,
    # never by a direct write/import/default context.
    _PROTECTED = {"state", "custody_out_at", "custody_in_at", "confirmed_by",
                  "readiness_status", "readiness_snapshot", "readiness_version"}

    @api.constrains("planned_start", "planned_end")
    def _check_interval(self):
        for rec in self:
            if rec.planned_start and rec.planned_end and rec.planned_end <= rec.planned_start:
                raise ValidationError(_("Planned end must be after planned start (half-open interval)."))

    def write(self, vals):
        if not self.env.context.get("ff_alloc_action"):
            forbidden = self._PROTECTED & set(vals)
            if forbidden and vals.get("state") != "draft":
                raise AccessError(_(
                    "Allocation state and custody are changed through the workflow "
                    "actions (confirm/checkout/return/cancel), not by direct edits."
                ))
        return super().write(vals)

    def _apply(self, vals):
        return super(FleetflowAllocation, self.with_context(ff_alloc_action=True)).write(vals)

    # ------------------------------------------------------------------
    # Concurrency-safe transitions
    # ------------------------------------------------------------------
    def _require_dispatcher(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_dispatcher") or self.env.su):
            raise AccessError(_("Only a dispatcher can manage allocations."))

    def _lock_resources(self):
        """Serialise competing reservations on the persistent vehicle/driver rows.

        Odoo runs REPEATABLE READ, so a plain SELECT ... FOR UPDATE that only
        locks (without modifying) the resource row would let the loser keep a
        stale snapshot and miss a competitor's just-committed reservation. We
        therefore UPDATE a lock counter on the row: two concurrent confirms then
        hit Postgres first-updater-wins, and exactly one survives (Odoo retries
        the serialisation failure at the RPC layer, where it then sees the
        conflict and reports it cleanly). Vehicles are locked before drivers, in
        id order, so two transactions cannot deadlock.
        """
        self.flush_recordset()
        vehicle_ids = tuple(sorted(set(self.mapped("vehicle_id").ids)))
        driver_ids = tuple(sorted(set(self.mapped("driver_id").ids)))
        if vehicle_ids:
            self.env.cr.execute(
                "UPDATE fleet_vehicle SET ff_alloc_lock = COALESCE(ff_alloc_lock, 0) + 1 "
                "WHERE id IN %s", (vehicle_ids,))
        if driver_ids:
            self.env.cr.execute(
                "UPDATE fleetflow_driver SET ff_alloc_lock = COALESCE(ff_alloc_lock, 0) + 1 "
                "WHERE id IN %s", (driver_ids,))
        self.invalidate_recordset()

    def _overlapping_domain(self):
        self.ensure_one()
        subject = ["|", ("vehicle_id", "=", self.vehicle_id.id)]
        subject.append(("driver_id", "=", self.driver_id.id) if self.driver_id else ("id", "=", 0))
        return [("id", "!=", self.id), ("state", "in", list(ACTIVE_STATES))] + subject

    def _overlapping_conflicts(self):
        """Overlapping active reservations on the same vehicle/driver (half-open).

        Used at CONFIRM: back-to-back plans are allowed, so an adjacent shift is
        not a conflict here even if the current one is still physically out."""
        self.ensure_one()
        return self.env["fleetflow.allocation"].search(self._overlapping_domain() + [
            ("planned_start", "<", self.planned_end),
            ("planned_end", ">", self.planned_start),
        ])

    def _unreturned_custody(self):
        """Unreturned custody on the same resource, regardless of planned interval.

        Used at CHECKOUT: a late physical return blocks the next checkout even
        once its own reservation window has ended."""
        self.ensure_one()
        return self.env["fleetflow.allocation"].search(self._overlapping_domain() + [
            ("state", "=", "checked_out"), ("custody_out_at", "!=", False),
            ("custody_in_at", "=", False),
        ])

    def _requested_channel_products(self):
        self.ensure_one()
        return list({(e.channel, e.product) for e in self.channel_enrolment_ids})

    def _evaluate(self):
        self.ensure_one()
        return self.env["fleetflow.readiness"].evaluate_readiness(
            self.company_id, self.vehicle_id, self.driver_id, self.operating_mode,
            self._requested_channel_products(), self.planned_start, self.planned_end)

    def action_confirm(self):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "draft":
            raise UserError(_("Only a draft allocation can be confirmed."))
        self._lock_resources()
        result = self._evaluate()
        if not result["can_confirm"]:
            raise UserError(_("Not ready to confirm:\n- %s") % "\n- ".join(result["next_actions"]))
        conflicts = self._overlapping_conflicts()
        if conflicts:
            raise UserError(_("The vehicle or driver is already reserved for an overlapping interval (%s).")
                            % ", ".join(conflicts.mapped("name")))
        self._apply({
            "state": "confirmed", "confirmed_by": self.env.uid,
            "readiness_status": result["status"],
            "readiness_snapshot": json.dumps(result, default=str),
            "readiness_version": result.get("profile") and str(result["profile"].get("version")),
        })
        self.message_post(body=_("Confirmed. Readiness: %s.") % result["status"])
        return True

    def action_checkout(self, odometer=None):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "confirmed":
            raise UserError(_("Only a confirmed allocation can be checked out."))
        self._lock_resources()
        # Fresh readiness at the moment of custody handover (no stale snapshot).
        result = self._evaluate()
        if not result["can_confirm"]:
            raise UserError(_("Readiness changed; cannot check out:\n- %s")
                            % "\n- ".join(result["next_actions"]))
        # Active dispatch-blocking hold on the vehicle blocks checkout.
        blocking = self.env["fleetflow.vehicle.hold"].search_count([
            ("vehicle_id", "=", self.vehicle_id.id), ("state", "=", "active"),
            ("dispatch_blocking", "=", True)])
        if blocking:
            raise UserError(_("Vehicle has an active dispatch-blocking hold."))
        conflicts = self._overlapping_conflicts() | self._unreturned_custody()
        if conflicts:
            raise UserError(_("Cannot check out: resource busy or not returned (%s).")
                            % ", ".join(conflicts.mapped("name")))
        vals = {"state": "checked_out", "custody_out_at": fields.Datetime.now()}
        odometer = self.checkout_odometer if odometer is None else odometer
        if odometer:
            self._validate_odometer(odometer)
            vals["checkout_odometer"] = odometer
        self._apply(vals)
        self.message_post(body=_("Checked out."))
        return True

    def action_return(self, odometer=None, fuel=None, condition=None, defect=None):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "checked_out":
            raise UserError(_("Only a checked-out allocation can be returned."))
        self._lock_resources()
        # Fall back to the in-form values when called from a button.
        odometer = self.return_odometer if odometer is None else odometer
        fuel = self.return_fuel if fuel is None else fuel
        condition = self.return_condition if condition is None else condition
        defect = self.return_defect if defect is None else bool(defect)
        vals = {"state": "returned", "custody_in_at": fields.Datetime.now(),
                "return_fuel": fuel, "return_condition": condition, "return_defect": defect}
        if odometer:
            self._validate_odometer(odometer, is_return=True)
            vals["return_odometer"] = odometer
        self._apply(vals)
        if defect:
            self._raise_defect_hold(condition)
        self.message_post(body=_("Returned.%s") % (_(" Defect reported.") if defect else ""))
        return True

    def action_cancel(self):
        self.ensure_one()
        self._require_dispatcher()
        if self.state not in ("draft", "confirmed"):
            raise UserError(_("Only a draft or confirmed allocation can be cancelled (not after checkout)."))
        self._apply({"state": "cancelled"})
        return True

    def action_check_readiness(self):
        """Explain readiness before confirming: a notification with the verdict
        and the precise next actions, so a blocker is never an unexplained dot."""
        self.ensure_one()
        result = self._evaluate()
        lines = ["%s — %s" % (r["status"].upper(), r["message"]) for r in result["reasons"]]
        kind = {constants.READY: "success", constants.WARNING: "warning"}.get(result["status"], "danger")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Readiness: %s") % dict(constants.READINESS_STATES)[result["status"]],
                "message": "\n".join(lines) or _("All checks pass."),
                "sticky": True,
                "type": kind,
            },
        }

    def _validate_odometer(self, value, is_return=False):
        self.ensure_one()
        if value is None:
            return
        if value < 0 or value != value:  # negative or NaN
            raise ValidationError(_("Odometer reading must be a non-negative number."))
        if is_return and self.checkout_odometer and value < self.checkout_odometer:
            # A decrease needs a reviewed correction/meter-change path, not silent
            # acceptance.
            raise ValidationError(_(
                "Return odometer (%s) is below checkout (%s). A decrease requires "
                "a reviewed meter-change correction.") % (value, self.checkout_odometer))

    def _raise_defect_hold(self, note):
        """A serious reported defect creates a safety hold and a work order."""
        self.ensure_one()
        self.env["fleetflow.vehicle.hold"].sudo().create({
            "vehicle_id": self.vehicle_id.id, "hold_type": "safety",
            "reason": _("Defect reported on return of %s: %s") % (self.name, note or _("(no note)")),
            "dispatch_blocking": True,
        })
        # Create a linked FleetFlow work order through the normal model.
        self.env["fleetflow.order"].sudo().create({
            "title": _("Defect reported on return: %s") % self.name,
            "description": note or "",
            "vehicle_id": self._fleetflow_order_vehicle(),
            "company_id": self.company_id.id,
            "priority": "3",
        })

    def _fleetflow_order_vehicle(self):
        """fleetflow.order requires a fleet.vehicle; reuse this allocation's vehicle."""
        return self.vehicle_id.id
