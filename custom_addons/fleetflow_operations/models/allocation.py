# -*- coding: utf-8 -*-
import json
import math
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants

ACTIVE_STATES = ("confirmed", "checked_out")
_ODO_EPS = 1e-6  # tolerance for float km comparisons (unit conversion)


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

    # Checkout / return capture inputs. These are consumed by the actions to build
    # the IMMUTABLE custody events (fleetflow.custody.event), which are the source of
    # truth. They are editable only before their event is recorded and are frozen
    # afterwards (see write); they are never a second, editable source of truth.
    checkout_odometer = fields.Float(copy=False)
    return_odometer = fields.Float(copy=False)
    # The CHECKOUT reported unit (return has its own return_odometer_unit).
    odometer_unit = fields.Selection(constants.ODOMETER_UNITS, default="km",
                                     string="Checkout unit")
    return_fuel = fields.Char(copy=False)
    return_condition = fields.Text(copy=False)
    return_defect = fields.Boolean(copy=False)
    # Structured capture (optional): energy state and a condition code per handover.
    # Checkout and return each carry their OWN reported reading AND unit, so a return
    # in km never relabels a checkout that was recorded in miles.
    checkout_condition_code = fields.Selection(constants.CONDITION_CODES, copy=False)
    checkout_energy_kind = fields.Selection(constants.ENERGY_KINDS, copy=False)
    checkout_energy_level = fields.Integer(copy=False)
    checkout_notes = fields.Text(copy=False)
    return_odometer_unit = fields.Selection(constants.ODOMETER_UNITS, default="km", copy=False)
    return_condition_code = fields.Selection(constants.CONDITION_CODES, copy=False)
    return_energy_kind = fields.Selection(constants.ENERGY_KINDS, copy=False)
    return_energy_level = fields.Integer(copy=False)

    # Immutable-custody links (source of truth) and derived read-only mirrors.
    custody_event_ids = fields.One2many(
        "fleetflow.custody.event", "allocation_id", string="Custody events")
    checkout_event_id = fields.Many2one(
        "fleetflow.custody.event", readonly=True, copy=False, string="Checkout event")
    return_event_id = fields.Many2one(
        "fleetflow.custody.event", readonly=True, copy=False, string="Return event")
    current_holder_id = fields.Many2one(
        "fleetflow.driver", compute="_compute_custody_view", string="Currently with")
    is_out = fields.Boolean(compute="_compute_custody_view", string="Physically out")
    is_overdue = fields.Boolean(compute="_compute_custody_view", string="Overdue")
    distance_travelled_km = fields.Float(
        compute="_compute_custody_view", string="Distance travelled (km)")

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
                  "warnings_ack_by", "warnings_ack_on",
                  "checkout_event_id", "return_event_id"}
    # Capture inputs that become historical once their handover event is recorded.
    _CHECKOUT_CAPTURE = {"checkout_odometer", "odometer_unit", "checkout_condition_code",
                         "checkout_energy_kind", "checkout_energy_level", "checkout_notes"}
    _RETURN_CAPTURE = {"return_odometer", "return_odometer_unit", "return_fuel",
                       "return_condition", "return_defect", "return_condition_code",
                       "return_energy_kind", "return_energy_level"}
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

    @api.depends("state", "driver_id", "planned_end", "custody_out_at",
                 "checkout_event_id", "return_event_id")
    def _compute_custody_view(self):
        now = fields.Datetime.now()
        for rec in self:
            out = rec.state == "checked_out" and bool(rec.custody_out_at) and not rec.custody_in_at
            rec.is_out = out
            rec.current_holder_id = rec.driver_id if out else False
            rec.is_overdue = bool(out and rec.planned_end and now > rec.planned_end)
            if rec.checkout_event_id and rec.return_event_id:
                # Use the EFFECTIVE (accepted-tip) readings so an approved correction
                # is reflected in the journey distance.
                out_km = rec.checkout_event_id._effective_tip().odometer_km or 0.0
                in_km = rec.return_event_id._effective_tip().odometer_km or 0.0
                rec.distance_travelled_km = max(0.0, in_km - out_km)
            else:
                rec.distance_travelled_km = 0.0

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
        # Capture inputs are frozen once their handover has been recorded, so a
        # checked-out or returned allocation's historical custody facts can never be
        # rewritten through the form/RPC/import mirror. The immutable custody events
        # remain the source of truth; these fields only feed them.
        if self._CHECKOUT_CAPTURE & set(vals):
            for rec in self:
                if rec.state in ("checked_out", "returned", "cancelled"):
                    raise AccessError(_(
                        "Checkout details for %s were captured at handover and are "
                        "now historical. Record a custody correction instead."
                    ) % rec.name)
        if self._RETURN_CAPTURE & set(vals):
            for rec in self:
                if rec.state == "returned":
                    raise AccessError(_(
                        "Return details for %s were captured at handover and are now "
                        "historical. Record a custody correction instead.") % rec.name)
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
        """Bump the shared lock counter on specific vehicle/driver rows so
        competing transactions serialise deterministically."""
        self.flush_recordset()
        constants.bump_resource_locks(self.env, vehicle_ids, driver_ids)
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

    def _custody_conflicts(self, now):
        """Resources that make taking physical custody NOW unsafe.

        Physical custody would run [now, planned_end); anything an early checkout
        would trample is a conflict, not just a plan that overlaps the reservation
        window. Two parts, unioned:

        - an active reservation (confirmed/checked-out) on the same vehicle/driver
          whose PLANNED window intersects [now, planned_end) -- so an early handover
          cannot seize a car another current reservation still holds even when the
          two planned windows do not overlap;
        - any unreturned physical custody on the resource (a late return blocks the
          next checkout even after its own window has ended).
        """
        self.ensure_one()
        overlap = self.env["fleetflow.allocation"].search(self._overlapping_domain() + [
            ("planned_start", "<", self.planned_end),
            ("planned_end", ">", now),
        ])
        return overlap | self._unreturned_custody()

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

    def action_checkout(self, odometer=None, unit=None, condition=None, condition_code=None,
                        energy_kind=None, energy_level=None, notes=None, acknowledge=None):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "confirmed":
            raise UserError(_("Only a confirmed allocation can be checked out."))
        # OPS-1/2A offer rental CAPACITY blocking only; a physical rental handover
        # needs renter/contract controls that are not part of this increment.
        if self.operating_mode == "rental":
            raise UserError(_(
                "Physical rental checkout is not available yet (rental allocations "
                "block capacity only)."))
        acknowledge = self.acknowledge_warnings if acknowledge is None else acknowledge
        now = fields.Datetime.now()
        # Handover-timing policy (server time is authoritative). A handover after
        # planned_end validates a window that has already passed -- reschedule. An
        # early handover is allowed only within the operating company's configured
        # early tolerance before planned_start; with no tolerance (the conservative
        # default) checkout before planned_start is refused. This is a FleetFlow
        # operational rule, not a legal one.
        if now >= self.planned_end:
            raise UserError(_(
                "The reservation window ended at %s (server time). Reschedule the "
                "allocation before checking out.") % self.planned_end)
        tolerance = self.company_id.ff_checkout_early_tolerance_minutes or 0
        earliest = self.planned_start - timedelta(minutes=tolerance)
        if now < earliest:
            raise UserError(_(
                "Too early to hand over: checkout opens at %s (planned start %s, "
                "early-handover tolerance %s min). Handover before then is not "
                "allowed.") % (earliest, self.planned_start, tolerance))
        # Resolve EVERY captured input ONCE: explicit argument when supplied, else the
        # saved form value. The immutable event and the allocation mirrors are then
        # built from the SAME payload, so history and display cannot disagree.
        odometer = self.checkout_odometer if odometer is None else odometer
        unit = unit or self.odometer_unit or "km"
        condition_code = condition_code if condition_code is not None else self.checkout_condition_code
        energy_kind = energy_kind if energy_kind is not None else self.checkout_energy_kind
        energy_level = self.checkout_energy_level if energy_level is None else energy_level
        notes = notes if notes is not None else self.checkout_notes
        # Energy is 'recorded' only when a kind is set; a measured 0% is then kept and
        # 'not recorded' (no kind) stores no level -- 0 and omission stay distinct.
        energy_level = energy_level if energy_kind else False
        # A safety-coded condition means the car is NOT fit to hand over: refuse the
        # handover (raise a hold through the proper path) rather than persist a hold in
        # a transaction that a later validation error would roll back.
        if condition_code in constants.SAFETY_CONDITION_CODES:
            raise UserError(_(
                "A safety condition (%s) was recorded for checkout; the vehicle cannot "
                "be handed over. Record a hold and resolve it first.")
                % dict(constants.CONDITION_CODES).get(condition_code, condition_code))
        # A checkout odometer is mandatory and validated (0 is a value, not 'unset').
        if odometer is None:
            raise UserError(_("A checkout odometer reading is required."))
        self._lock_resources()
        # Fresh readiness over the ACTUAL handover window [now, planned_end], not
        # the planned start: a document expired by now blocks, and evidence not yet
        # effective cannot be relied on for an early handover.
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
        # Physical custody starts NOW, so the conflict horizon is [now, planned_end)
        # -- not merely the planned window. This catches a resource occupied between
        # now and this allocation's plan (an early checkout must not seize a car
        # another current reservation still holds) and any unreturned custody.
        conflicts = self._custody_conflicts(now)
        if conflicts:
            raise UserError(_("Cannot check out: the vehicle or driver is busy or "
                              "not yet returned (%s).") % ", ".join(conflicts.mapped("name")))
        km = self._validate_odometer(odometer, unit)
        ack_vals = self._require_ack(result, acknowledge)
        # Event and mirrors from the SAME resolved payload (`condition` free-text is
        # carried via notes; the structured code is the resolved condition_code).
        event = self._create_custody_event(
            "checkout", now, odometer, unit, km, condition=condition,
            condition_code=condition_code, energy_kind=energy_kind,
            energy_level=energy_level, notes=notes, defect=False)
        self.vehicle_id._ff_record_odometer(km, odometer, unit)
        self._apply({
            "state": "checked_out", "custody_out_at": now, "checkout_event_id": event.id,
            "checkout_odometer": odometer, "odometer_unit": unit,
            "checkout_condition_code": condition_code,
            "checkout_energy_kind": energy_kind,
            "checkout_energy_level": energy_level or 0,
            "checkout_notes": notes,
            **ack_vals})
        self.message_post(body=_("Checked out (odometer %s %s).%s") % (
            odometer, unit, _(" Warnings acknowledged.") if ack_vals else ""))
        return True

    def action_return(self, odometer=None, unit=None, fuel=None, condition=None, defect=None,
                      condition_code=None, energy_kind=None, energy_level=None, notes=None):
        self.ensure_one()
        self._require_dispatcher()
        if self.state != "checked_out":
            raise UserError(_("Only a checked-out allocation can be returned."))
        self._lock_resources()
        # An open checkout custody must exist -- a return is the close of a real
        # handover, never a standalone edit.
        if not self.checkout_event_id or self.return_event_id:
            raise UserError(_("No open checkout custody to return against."))
        # Resolve each input ONCE from its own saved form value (the return has its own
        # reported unit, distinct from the checkout unit). Preserve explicit zero.
        odometer = self.return_odometer if odometer is None else odometer
        unit = unit or self.return_odometer_unit or "km"
        fuel = self.return_fuel if fuel is None else fuel
        condition = self.return_condition if condition is None else condition
        defect = self.return_defect if defect is None else bool(defect)
        condition_code = condition_code if condition_code is not None else self.return_condition_code
        energy_kind = energy_kind if energy_kind is not None else self.return_energy_kind
        energy_level = self.return_energy_level if energy_level is None else energy_level
        energy_level = energy_level if energy_kind else False
        if odometer is None:
            raise UserError(_("A return odometer reading is required."))
        # Validate the reading (including 0) against checkout and the vehicle's last
        # accepted km; a zero/decrease cannot slip past.
        km = self._validate_odometer(odometer, unit, is_return=True)
        now = fields.Datetime.now()
        event = self._create_custody_event(
            "return", now, odometer, unit, km, condition=condition,
            condition_code=condition_code, energy_kind=energy_kind,
            energy_level=energy_level, notes=notes, fuel=fuel, defect=defect)
        self.vehicle_id._ff_record_odometer(km, odometer, unit)
        # A car is ALWAYS recorded as returned even when damaged; a safety-coded
        # condition OR an explicit defect atomically raises the dispatch-blocking
        # follow-up FROM the immutable return event (custody still closes below). A
        # safety condition cannot be cancelled by leaving the defect box unticked.
        if defect or (condition_code in constants.SAFETY_CONDITION_CODES):
            event._raise_safety_followup(reason=condition or notes)
        self._apply({
            "state": "returned", "custody_in_at": now, "return_event_id": event.id,
            "return_odometer": odometer, "return_odometer_unit": unit, "return_fuel": fuel,
            "return_condition": condition, "return_defect": defect,
            "return_condition_code": condition_code, "return_energy_kind": energy_kind,
            "return_energy_level": energy_level or 0})
        self.message_post(body=_("Returned (odometer %s %s).%s") % (
            odometer, unit, _(" Safety follow-up raised.") if (
                defect or condition_code in constants.SAFETY_CONDITION_CODES) else ""))
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

    @staticmethod
    def _normalize_km(value, unit):
        """Canonical kilometres for comparison; 100 mi is never compared with 100 km."""
        if value is None:
            return None
        return value * constants.MI_TO_KM if unit == "mi" else float(value)

    def _validate_odometer(self, value, unit, is_return=False):
        """Validate a reported reading and return its canonical km.

        Rejects non-finite, negative and decreasing readings. Comparison is done in
        canonical km against the vehicle's latest trusted km (which the previous
        checkout already advanced), so mixed km/mi never compare directly and a
        return below checkout is caught through the same floor.
        """
        self.ensure_one()
        if value is None:
            raise ValidationError(_("An odometer reading is required."))
        if math.isnan(value) or math.isinf(value):
            raise ValidationError(_("Odometer reading must be a finite number."))
        if value < 0:
            raise ValidationError(_("Odometer reading must be non-negative."))
        km = self._normalize_km(value, unit)
        floor = self.vehicle_id.ff_last_odometer_km or 0.0
        if km < floor - _ODO_EPS:
            raise ValidationError(_(
                "Odometer reading (%s %s = %.3f km) is below the vehicle's last "
                "accepted reading (%.3f km). A decrease requires a reviewed "
                "meter-change correction.") % (value, unit, km, floor))
        # Belt-and-braces for the return: never below its own checkout event.
        if is_return and self.checkout_event_id:
            out_km = self.checkout_event_id.odometer_km or 0.0
            if km < out_km - _ODO_EPS:
                raise ValidationError(_(
                    "Return odometer (%.3f km) is below checkout (%.3f km). A "
                    "decrease requires a reviewed meter-change correction.") % (km, out_km))
        return km

    def _create_custody_event(self, event_type, when, odometer, unit, km, condition=None,
                              condition_code=None, energy_kind=None, energy_level=None,
                              notes=None, fuel=None, defect=False):
        """Create the immutable custody event that IS the record of this handover.

        Created privileged (there is no public create right on custody events); the
        event stamps its own authoritative time and actor. A free-text `condition`
        note is preserved; the structured `condition_code` defaults sensibly.
        """
        self.ensure_one()
        code = condition_code or ("damage_noted" if defect else "acceptable")
        return self.env["fleetflow.custody.event"].sudo().create({
            "allocation_id": self.id, "vehicle_id": self.vehicle_id.id,
            "driver_id": self.driver_id.id or False, "company_id": self.company_id.id,
            "event_type": event_type, "event_time": when,
            "odometer": odometer, "odometer_unit": unit, "odometer_km": km,
            "energy_kind": energy_kind or False,
            "energy_level": energy_level if energy_level is not None else False,
            "fuel_note": fuel or False, "condition": code, "defect": bool(defect),
            "notes": notes or condition or False,
        })

