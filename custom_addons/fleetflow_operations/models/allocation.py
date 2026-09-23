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
    city = fields.Char(required=True, default="Dubai",
                       help="Operating city; channel platform approval is matched per city.")
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

    # Amendment inputs (consumed by the guarded Reschedule action, then cleared).
    amend_planned_start = fields.Datetime(copy=False)
    amend_planned_end = fields.Datetime(copy=False)

    # Explicit acknowledgement of non-blocking warnings (recorded on the decision).
    acknowledge_warnings = fields.Boolean(
        copy=False,
        help="Tick to proceed despite non-blocking warnings; recorded against "
             "the decision. It never overrides a Blocked or Needs-review verdict.")
    warnings_ack_by = fields.Many2one("res.users", readonly=True, copy=False)
    warnings_ack_on = fields.Datetime(readonly=True, copy=False)

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
                  "readiness_status", "readiness_snapshot", "readiness_version",
                  "warnings_ack_by", "warnings_ack_on"}
    # The plan (resources + interval) is locked once the allocation leaves draft;
    # a change then requires the audited amendment path, which re-locks resources
    # and re-evaluates readiness and conflicts.
    _PLANNING = {"vehicle_id", "driver_id", "operating_mode", "planned_start",
                 "planned_end", "channel_enrolment_ids", "city"}

    @api.constrains("planned_start", "planned_end")
    def _check_interval(self):
        for rec in self:
            if rec.planned_start and rec.planned_end and rec.planned_end <= rec.planned_start:
                raise ValidationError(_("Planned end must be after planned start (half-open interval)."))

    def write(self, vals):
        # There is NO context flag that opts out of these guards. Protected
        # lifecycle/custody/readiness fields move only through the workflow
        # actions, which write at the ORM level via _apply(). A public write --
        # from the form, an import, a copy or a forged RPC context -- can never
        # set them, not even alongside state='draft'.
        forbidden = self._PROTECTED & set(vals)
        if forbidden:
            raise AccessError(_(
                "Allocation state, custody and readiness are set by the workflow "
                "actions (confirm/checkout/return/cancel), not by direct edits."))
        # Once confirmed/checked-out/returned/cancelled, the plan is frozen.
        if self._PLANNING & set(vals):
            for rec in self:
                if rec.state != "draft":
                    raise AccessError(_(
                        "The plan of allocation %s is locked in state '%s'. Use "
                        "Reschedule to amend it (which re-checks readiness and "
                        "conflicts), or cancel and plan a new one."
                    ) % (rec.name, rec.state))
        return super().write(vals)

    def unlink(self):
        # Only genuine unused drafts are deletable by an ordinary user; a
        # confirmed/checked-out/returned allocation carries reservation and
        # custody history that must be cancelled, not erased. Superuser/admin
        # maintenance (migrations, test teardown) is exempt.
        if not self.env.su:
            for rec in self:
                if rec.state != "draft":
                    raise UserError(_(
                        "Only a draft allocation can be deleted. Cancel a confirmed "
                        "allocation instead; checked-out/returned custody is retained "
                        "for audit (%s is '%s').") % (rec.name, rec.state))
        return super().unlink()

    def _apply(self, vals):
        # Internal transition: bypass the public write guard by writing at the
        # ORM level. The only callers are the workflow actions below, which have
        # already checked role, source state, resource conflicts and readiness.
        return super().write(vals)

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
        self._lock_ids(self.mapped("vehicle_id").ids, self.mapped("driver_id").ids)

    def _lock_ids(self, vehicle_ids, driver_ids):
        """Bump the lock counter on specific vehicle/driver rows (vehicles first,
        both in id order) so competing transactions serialise deterministically."""
        self.flush_recordset()
        vehicle_ids = tuple(sorted(set(vehicle_ids)))
        driver_ids = tuple(sorted(set(driver_ids)))
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

    def _evaluate(self, start=None, end=None):
        """Evaluate readiness over an interval (defaults to the planned one).

        Checkout passes the ACTUAL handover window [now, planned_end] so that a
        stale document is caught and future-dated evidence cannot be relied on;
        confirm uses the planned interval."""
        self.ensure_one()
        return self.env["fleetflow.readiness"].evaluate_readiness(
            self.company_id, self.vehicle_id, self.driver_id, self.operating_mode,
            self._requested_channel_products(),
            start or self.planned_start, end or self.planned_end, city=self.city)

    def _decision_vals(self, result):
        return {
            "readiness_status": result["status"],
            "readiness_snapshot": json.dumps(result, default=str),
            "readiness_version": result.get("profile") and str(result["profile"].get("version")),
        }

    def _require_ack(self, result, acknowledge):
        """A non-blocking WARNING may proceed only with an explicit acknowledgement,
        recorded against the decision. It can never override Blocked or Needs
        review (those already fail can_confirm and are rejected before this)."""
        self.ensure_one()
        if not result.get("requires_ack"):
            return {}
        if not acknowledge:
            warns = [r["message"] for r in result["reasons"] if r["status"] == constants.WARNING]
            raise UserError(_(
                "This allocation has non-blocking warning(s). Acknowledge them to "
                "proceed:\n- %s") % "\n- ".join(warns))
        return {"warnings_ack_by": self.env.uid, "warnings_ack_on": fields.Datetime.now()}

    def action_confirm(self, acknowledge=None):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "draft":
            raise UserError(_("Only a draft allocation can be confirmed."))
        acknowledge = self.acknowledge_warnings if acknowledge is None else acknowledge
        self._lock_resources()
        result = self._evaluate()
        if not result["can_confirm"]:
            raise UserError(_("Not ready to confirm:\n- %s") % "\n- ".join(result["next_actions"]))
        conflicts = self._overlapping_conflicts()
        if conflicts:
            raise UserError(_("The vehicle or driver is already reserved for an overlapping interval (%s).")
                            % ", ".join(conflicts.mapped("name")))
        ack_vals = self._require_ack(result, acknowledge)
        self._apply({"state": "confirmed", "confirmed_by": self.env.uid,
                     **self._decision_vals(result), **ack_vals})
        self.message_post(body=_("Confirmed. Readiness: %s.%s") % (
            result["status"], _(" Warnings acknowledged.") if ack_vals else ""))
        return True

    def action_checkout(self, odometer=None, acknowledge=None):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "confirmed":
            raise UserError(_("Only a confirmed allocation can be checked out."))
        # OPS-1 offers rental CAPACITY blocking only; a physical rental handover
        # needs renter/contract controls that are not part of this increment.
        if self.operating_mode == "rental":
            raise UserError(_(
                "Physical rental checkout is not available in OPS-1 (rental "
                "allocations block capacity only)."))
        acknowledge = self.acknowledge_warnings if acknowledge is None else acknowledge
        now = fields.Datetime.now()
        # Server time is authoritative and the handover must fall inside the
        # approved reservation window: a handover after planned_end would validate
        # a window that has already passed -- reschedule instead.
        if now >= self.planned_end:
            raise UserError(_(
                "The reservation window ended at %s (server time). Reschedule the "
                "allocation before checking out.") % self.planned_end)
        self._lock_resources()
        # Fresh readiness over the ACTUAL handover window [now, planned_end], not
        # the planned start: a document expired by now blocks, and evidence not
        # yet effective cannot be relied on for an early handover.
        result = self._evaluate(start=now, end=self.planned_end)
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
        ack_vals = self._require_ack(result, acknowledge)
        vals = {"state": "checked_out", "custody_out_at": now, **ack_vals}
        odometer = self.checkout_odometer if odometer is None else odometer
        if odometer:
            self._validate_odometer(odometer)
            vals["checkout_odometer"] = odometer
        self._apply(vals)
        self.message_post(body=_("Checked out.%s") % (
            _(" Warnings acknowledged.") if ack_vals else ""))
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

    # ------------------------------------------------------------------
    # Guarded amendment (the sanctioned way to change a confirmed plan)
    # ------------------------------------------------------------------
    def _amend_vals(self):
        self.ensure_one()
        vals = {}
        if self.amend_planned_start:
            vals["planned_start"] = self.amend_planned_start
        if self.amend_planned_end:
            vals["planned_end"] = self.amend_planned_end
        return vals

    @staticmethod
    def _m2m_ids(commands):
        """Resolve an id list from an x2many (6,0,ids) command or a plain list."""
        if commands and isinstance(commands[0], (list, tuple)):
            for cmd in commands:
                if cmd and cmd[0] == 6:
                    return list(cmd[2])
            return []
        return list(commands or [])

    def _prospective_conflicts(self, vehicle, driver, start, end):
        self.ensure_one()
        subject = ["|", ("vehicle_id", "=", vehicle.id)]
        subject.append(("driver_id", "=", driver.id) if driver else ("id", "=", 0))
        domain = [("id", "!=", self.id), ("state", "in", list(ACTIVE_STATES))] + subject + [
            ("planned_start", "<", end), ("planned_end", ">", start)]
        return self.env["fleetflow.allocation"].search(domain)

    def action_reschedule(self, vals=None, acknowledge=None):
        """Guarded amendment of a CONFIRMED allocation's plan.

        Locks the old and new resources, re-evaluates readiness and conflicts on
        the PROSPECTIVE values (nothing is written until they pass, so a rejected
        amendment leaves the record untouched), preserves the previous decision in
        the chatter and records the new one. A checked-out allocation is checked
        in, not rescheduled.
        """
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "confirmed":
            raise UserError(_(
                "Only a confirmed allocation can be rescheduled (check it in or "
                "cancel first)."))
        vals = self._amend_vals() if vals is None else dict(vals)
        vals = {k: v for k, v in vals.items() if k in self._PLANNING}
        if not vals:
            raise UserError(_("Enter a new interval or resource to reschedule."))
        acknowledge = self.acknowledge_warnings if acknowledge is None else acknowledge

        # Prospective values -- not written yet.
        new_start = vals.get("planned_start", self.planned_start)
        new_end = vals.get("planned_end", self.planned_end)
        new_mode = vals.get("operating_mode", self.operating_mode)
        new_city = vals.get("city", self.city)
        new_vehicle = (self.env["fleet.vehicle"].browse(vals["vehicle_id"])
                       if "vehicle_id" in vals else self.vehicle_id)
        if "driver_id" in vals:
            new_driver = (self.env["fleetflow.driver"].browse(vals["driver_id"])
                          if vals["driver_id"] else self.env["fleetflow.driver"])
        else:
            new_driver = self.driver_id
        if new_end <= new_start:
            raise ValidationError(_("Planned end must be after planned start."))

        # Lock the current AND the prospective resources before re-checking.
        self._lock_ids([self.vehicle_id.id, new_vehicle.id],
                       list(filter(None, [self.driver_id.id, new_driver.id])))

        if "channel_enrolment_ids" in vals:
            enrolments = self.env["fleetflow.channel.enrolment"].browse(
                self._m2m_ids(vals["channel_enrolment_ids"]))
            products = list({(e.channel, e.product) for e in enrolments})
        else:
            products = self._requested_channel_products()

        result = self.env["fleetflow.readiness"].evaluate_readiness(
            self.company_id, new_vehicle, new_driver, new_mode, products,
            new_start, new_end, city=new_city)
        if not result["can_confirm"]:
            raise UserError(_("The amended plan is not ready:\n- %s")
                            % "\n- ".join(result["next_actions"]))
        conflicts = self._prospective_conflicts(new_vehicle, new_driver, new_start, new_end)
        if conflicts:
            raise UserError(_("The amended plan conflicts with an existing reservation (%s).")
                            % ", ".join(conflicts.mapped("name")))
        ack_vals = self._require_ack(result, acknowledge)

        # Preserve the previous decision, then apply the new plan + decision.
        self.message_post(body=_(
            "Amended. Previous plan: %s -> %s (readiness %s, version %s).") % (
            self.planned_start, self.planned_end, self.readiness_status, self.readiness_version))
        self._apply({**vals, **self._decision_vals(result), **ack_vals,
                     "amend_planned_start": False, "amend_planned_end": False})
        self.message_post(body=_("Rescheduled. Readiness: %s.") % result["status"])
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
