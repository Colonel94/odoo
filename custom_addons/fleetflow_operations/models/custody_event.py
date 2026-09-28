# -*- coding: utf-8 -*-
import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants

_ODO_EPS = 1e-6  # tolerance for float km comparisons (unit conversion)


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

    # ------------------------------------------------------------------
    # Effective-version resolution (corrections form one linear chain)
    # ------------------------------------------------------------------
    def _physical_root(self):
        """The original physical event this record belongs to (follow corrects_id up).
        Its event_time/actor/driver are the authoritative record of the physical
        movement and are never changed by a correction."""
        self.ensure_one()
        cur, seen = self, set()
        while cur.corrects_id and cur.id not in seen:
            seen.add(cur.id)
            cur = cur.corrects_id
        return cur

    def _effective_tip(self):
        """The current ACCEPTED version of this physical event: the tip of its linear
        correction chain (itself if never corrected). Operational consumers -- trusted
        mileage, checkout/return comparison, distance, display, safety follow-up -- use
        this record's measurements."""
        self.ensure_one()
        cur, seen = self, set()
        while cur.corrected_by_ids and cur.id not in seen:
            seen.add(cur.id)
            cur = cur.corrected_by_ids.sorted(key=lambda e: e.id)[-1]
        return cur

    def _is_safety(self):
        """True if this event records a roadworthiness concern per FleetFlow policy:
        a safety-coded condition OR an explicit defect."""
        self.ensure_one()
        return bool(self.defect) or (self.condition in constants.SAFETY_CONDITION_CODES)

    def _correction_bounds(self):
        """(lower, upper) canonical-km bounds a corrected reading for THIS event must
        stay within, from the vehicle's OTHER accepted physical readings ordered by
        physical time then id (so a checkout precedes its equal-timed return). None =
        unbounded on that side. Keeps a correction from contradicting a neighbouring
        accepted movement."""
        self.ensure_one()
        root = self._physical_root()
        my_key = (root.event_time, root.id)
        lower = upper = None
        for other in self.vehicle_id.ff_custody_event_ids.filtered(lambda e: not e.corrects_id):
            if other.id == root.id:
                continue
            km = other._effective_tip().odometer_km or 0.0
            if (other.event_time, other.id) < my_key:
                lower = km if lower is None else max(lower, km)
            else:
                upper = km if upper is None else min(upper, km)
        return lower, upper

    def _validate_corrected_odometer(self, value, unit):
        """Reuse handover measurement validation for a corrected reading: finite,
        numeric, non-negative, valid unit, and chronologically consistent with the
        surrounding accepted readings. Returns canonical km."""
        self.ensure_one()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(_("Odometer reading must be a number."))
        if math.isnan(value) or math.isinf(value):
            raise ValidationError(_("Odometer reading must be a finite number."))
        if value < 0:
            raise ValidationError(_("Odometer reading must be non-negative."))
        if unit not in dict(constants.ODOMETER_UNITS):
            raise ValidationError(_("Invalid odometer unit."))
        km = self._to_km(value, unit)
        lower, upper = self._correction_bounds()
        if lower is not None and km < lower - _ODO_EPS:
            raise ValidationError(_(
                "Corrected reading (%.3f km) is below the preceding accepted reading "
                "(%.3f km). A decrease requires a reviewed meter-change correction.")
                % (km, lower))
        if upper is not None and km > upper + _ODO_EPS:
            raise ValidationError(_(
                "Corrected reading (%.3f km) conflicts with a later accepted reading "
                "(%.3f km); this requires review, not a silent rewrite.") % (km, upper))
        return km

    def _raise_safety_followup(self, reason=None):
        """Create the dispatch-blocking safety hold + work order originating from THIS
        event (its provenance). Idempotent: if this event already originated a hold,
        nothing is created (retry-safe). Privileged; the caller has checked role."""
        self.ensure_one()
        if self.hold_id:
            return self.hold_id
        alloc = self.allocation_id
        label = dict(constants.CONDITION_CODES).get(self.condition, self.condition)
        note = reason or self.notes or label or _("safety condition")
        order = self.env["fleetflow.order"].sudo().create({
            "title": _("Safety follow-up from custody: %s") % (alloc.name or self.display_name),
            "description": note or "",
            "vehicle_id": self.vehicle_id.id, "company_id": self.company_id.id,
            "priority": "3",
        })
        hold = self.env["fleetflow.vehicle.hold"].sudo().create({
            "vehicle_id": self.vehicle_id.id, "hold_type": "safety",
            "reason": _("Safety condition on %s: %s") % (alloc.name or self.display_name, note),
            "dispatch_blocking": True,
            "source_work_order_id": order.id,
            "source_allocation_id": alloc.id,
            "source_custody_event_id": self.id,
        })
        self._apply({"hold_id": hold.id, "order_id": order.id})
        return hold

    # Fields a correction may change; everything else (identity, physical time/actor,
    # canonical value, provenance, approval/legacy markers) is rejected.
    _CORRECTABLE = {"odometer", "odometer_unit", "energy_kind", "energy_level",
                    "condition", "defect", "notes"}

    def action_correct(self, reason, **measurements):
        """Record an attributable, VALIDATED and operationally effective correction.

        The original event is never altered. A correction is a NEW event that
        supersedes the current accepted version, carrying its own reason, actor and
        recording time -- it never changes who physically received/returned the
        vehicle or when the movement happened. Corrections form one linear chain (no
        competing branches); the tip is the effective version used by operations. The
        correction is validated like a handover measurement, coordinated with
        checkout/return on the shared vehicle lock, and (when it adds a safety finding)
        raises the blocking follow-up. It never opens/closes physical custody.
        Returns the new event's id.
        """
        self.ensure_one()
        if not (self.env.user.has_group("fleetflow_operations.group_ops_fleet_manager")
                or self.env.su):
            raise AccessError(_("Only a fleet manager can correct a custody record."))
        # Access (incl. company isolation) is checked before any privileged write/SQL.
        self.check_access_rights("read")
        self.check_access_rule("read")
        if not (reason and reason.strip()):
            raise UserError(_("A correction requires a reason."))
        bad = set(measurements) - self._CORRECTABLE
        if bad:
            raise UserError(_(
                "These fields cannot be corrected: %s. Only %s may be corrected.")
                % (", ".join(sorted(bad)), ", ".join(sorted(self._CORRECTABLE))))
        # Serialise with checkout/return and other corrections on the shared vehicle
        # lock (first-updater-wins under REPEATABLE READ). A losing concurrent
        # correction aborts with a serialization failure and retries against the new
        # tip; a checkout either sees the corrected floor or is refused after commit.
        constants.bump_resource_locks(self.env, self.vehicle_id.ids)
        # Always correct the CURRENT accepted version, keeping the chain linear.
        tip = self._effective_tip()
        self.env.cr.execute(
            "SELECT id FROM fleetflow_custody_event WHERE id = %s FOR UPDATE", (tip.id,))
        tip.invalidate_recordset(["corrected_by_ids"])
        if tip.corrected_by_ids:
            raise UserError(_(
                "This record was corrected concurrently; retry against the current "
                "accepted version."))
        # Resolve the corrected snapshot (fallback to the current tip's values), then
        # validate before creating historical facts.
        unit = measurements.get("odometer_unit", tip.odometer_unit) or "km"
        odometer = measurements.get("odometer", tip.odometer)
        km = tip._validate_corrected_odometer(odometer, unit)
        energy_kind = measurements.get("energy_kind", tip.energy_kind)
        if "energy_level" in measurements:
            energy_level = measurements["energy_level"]
            if energy_level is not None and (isinstance(energy_level, bool)
                                             or not isinstance(energy_level, int)):
                raise ValidationError(_("Energy level must be an integer percentage."))
        else:
            energy_level = tip.energy_level
        condition = measurements.get("condition", tip.condition)
        if condition and condition not in dict(constants.CONDITION_CODES):
            raise ValidationError(_("Invalid condition code."))
        defect = bool(measurements.get("defect", tip.defect))
        notes = measurements.get("notes", tip.notes)
        correction = self.sudo().create({
            "allocation_id": tip.allocation_id.id, "vehicle_id": tip.vehicle_id.id,
            "driver_id": tip.driver_id.id, "company_id": tip.company_id.id,
            "event_type": tip.event_type, "corrects_id": tip.id,
            "correction_reason": reason.strip(),
            "odometer": odometer, "odometer_unit": unit,
            "energy_kind": energy_kind or False,
            "energy_level": energy_level if (energy_kind and energy_level is not None) else False,
            "condition": condition or False, "defect": defect,
            "notes": notes or False, "fuel_note": tip.fuel_note or False,
        })
        # Effective measurements changed: recompute the vehicle's trusted mileage.
        tip.vehicle_id._ff_recompute_trusted_odometer()
        # A correction that ADDS a safety finding raises the blocking follow-up; it
        # never clears an existing hold (that stays with the authorised clearance flow).
        if correction._is_safety() and not tip._is_safety():
            correction._raise_safety_followup(reason=reason.strip())
        return correction.id
