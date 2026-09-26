# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from . import constants


class FleetVehicle(models.Model):
    """Operational extension of the standard fleet vehicle.

    We extend fleet.vehicle rather than duplicating it. Existing Odoo fields are
    reused as-is: license_plate, vin_sn (chassis), model_id, model_year,
    acquisition_date (immatriculation, NOT manufacture or first registration),
    company_id, active, odometer. The fields below add the operational context
    Dubai fleet operations needs and that core fleet does not carry.
    """
    _inherit = "fleet.vehicle"

    # -- Legal context -------------------------------------------------------
    ff_operator_company_id = fields.Many2one(
        "res.company",
        string="Operating company",
        help="The legal company currently authorised to operate this vehicle. "
             "Ownership is separate: an external owner/lessor is a partner.",
    )
    ff_owner_partner_id = fields.Many2one(
        "res.partner",
        string="Owner / lessor",
        help="Registered owner or lessor. May be external (Takamul lender). "
             "Shared ownership never by itself authorises operation.",
    )

    # -- Dates and age basis (distinct calculations) -------------------------
    ff_manufacture_date = fields.Date(
        string="Manufacture date",
        help="Do not infer a day from the model year; set the precision instead.",
    )
    ff_manufacture_precision = fields.Selection(
        constants.DATE_PRECISION, string="Manufacture date precision", default="unknown",
    )
    ff_first_registration_date = fields.Date(string="First registration date")
    ff_source_category = fields.Selection(
        constants.SOURCE_CATEGORY, string="Acquisition / source", default="unknown",
    )
    ff_powertrain = fields.Selection(
        constants.POWERTRAIN, string="Powertrain", default="unknown",
    )

    # -- Official classification (evidence-backed, never inferred) -----------
    ff_official_category = fields.Selection(
        constants.OFFICIAL_CATEGORY, string="Official category", default="unknown",
        help="Set only from an official classification credential, never from "
             "price or badge.",
    )
    ff_authorized_end_of_use = fields.Date(
        string="Authorised end-of-use", copy=False,
        help="Individually authorised end-of-use date from official evidence, "
             "when known. Absence does not imply any generic age limit.",
    )
    ff_end_of_use_exempt = fields.Boolean(
        string="End-of-use: reviewed exemption", readonly=True, copy=False,
        help="A compliance reviewer has determined that no end-of-use restriction "
             "applies to this vehicle. A blank field is NOT an exemption.",
    )
    ff_end_of_use_reviewed_by = fields.Many2one("res.users", readonly=True, copy=False)
    ff_end_of_use_reviewed_on = fields.Datetime(readonly=True, copy=False)

    # -- Plate identity ------------------------------------------------------
    ff_emirate = fields.Char(string="Emirate")
    ff_plate_code = fields.Char(string="Plate code")
    ff_plate_log_ids = fields.One2many(
        "fleetflow.vehicle.plate.log", "vehicle_id", string="Plate history",
    )

    # -- Operational review state (existing vehicles start unreviewed) -------
    ff_operational_state = fields.Selection(
        [("unreviewed", "Unreviewed"), ("reviewed", "Reviewed")],
        string="Operational review", default="unreviewed", required=True, copy=False,
        help="Existing vehicles are operationally unreviewed until a compliance "
             "reviewer confirms them. Migration never approves a vehicle by default.",
    )
    ff_credential_ids = fields.One2many(
        "fleetflow.credential", "vehicle_id", string="Vehicle evidence",
    )
    ff_channel_enrolment_ids = fields.One2many(
        "fleetflow.channel.enrolment", "vehicle_id", string="Channel enrolments",
    )
    ff_hold_ids = fields.One2many(
        "fleetflow.vehicle.hold", "vehicle_id", string="Holds",
    )
    ff_allocation_ids = fields.One2many(
        "fleetflow.allocation", "vehicle_id", string="Allocations",
    )
    ff_active_hold_count = fields.Integer(
        string="Active blocking holds", compute="_compute_active_hold_count",
    )
    ff_alloc_lock = fields.Integer(
        string="Allocation lock counter", default=0, copy=False,
        help="Bumped inside a locked transaction to serialise competing "
             "reservations (Odoo runs REPEATABLE READ; updating the row forces "
             "first-updater-wins on concurrent confirms).",
    )

    @api.depends("ff_hold_ids.state", "ff_hold_ids.dispatch_blocking")
    def _compute_active_hold_count(self):
        for vehicle in self:
            vehicle.ff_active_hold_count = len(vehicle.ff_hold_ids.filtered(
                lambda h: h.state == "active" and h.dispatch_blocking))

    @api.constrains("ff_manufacture_date", "ff_first_registration_date")
    def _check_operational_dates(self):
        for vehicle in self:
            man = vehicle.ff_manufacture_date
            reg = vehicle.ff_first_registration_date
            if man and reg and reg < man:
                raise ValidationError(_(
                    "First registration cannot precede the manufacture date on %s."
                ) % vehicle.display_name)

    # Authority-bearing fields set only through the compliance actions below
    # (which write at the ORM level via super()); a user who merely holds
    # vehicle-write rights cannot forge them by a direct edit.
    _FF_REVIEW_FIELDS = {"ff_operational_state", "ff_authorized_end_of_use",
                         "ff_end_of_use_exempt", "ff_end_of_use_reviewed_by",
                         "ff_end_of_use_reviewed_on"}

    @api.model_create_multi
    def create(self, vals_list):
        # A vehicle is created operationally UNREVIEWED with no age determination,
        # whatever the caller, copy or default_* context supplies: the reviewed
        # state and end-of-use exemption are compliance actions, never forgeable at
        # creation/import/copy by an ordinary user. Values are set explicitly (not
        # popped) so a default_<field> context key cannot refill them. Superuser
        # (fixtures/migration) may seed a reviewed state deliberately.
        if not self.env.su:
            for vals in vals_list:
                vals["ff_operational_state"] = "unreviewed"
                vals["ff_end_of_use_exempt"] = False
                vals["ff_end_of_use_reviewed_by"] = False
                vals["ff_end_of_use_reviewed_on"] = False
                vals["ff_authorized_end_of_use"] = False
        return super().create(vals_list)

    def write(self, vals):
        forbidden = self._FF_REVIEW_FIELDS & set(vals)
        if forbidden:
            raise AccessError(_(
                "A vehicle's operational review state and authorised end-of-use "
                "are set by the compliance review actions, not by a direct edit."))
        return super().write(vals)

    def _require_compliance(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance")
                or self.env.su):
            raise AccessError(_("Only a compliance reviewer can perform this vehicle review action."))

    def ff_mark_reviewed(self):
        """Compliance action: mark a vehicle operationally reviewed."""
        self._require_compliance()
        return super().write({"ff_operational_state": "reviewed"})

    def ff_mark_unreviewed(self):
        """Compliance action: return a vehicle to operationally unreviewed."""
        self._require_compliance()
        return super().write({"ff_operational_state": "unreviewed"})

    def ff_review_end_of_use(self, exempt=False, authorized_end_of_use=None):
        """Compliance action: record an age/end-of-use determination with
        provenance -- either an authorised end-of-use date, or an explicit
        reviewed exemption. A blank field is never treated as either."""
        self._require_compliance()
        vals = {
            "ff_end_of_use_exempt": bool(exempt),
            "ff_end_of_use_reviewed_by": self.env.uid,
            "ff_end_of_use_reviewed_on": fields.Datetime.now(),
        }
        if authorized_end_of_use is not None:
            vals["ff_authorized_end_of_use"] = authorized_end_of_use
        return super().write(vals)


class FleetVehiclePlateLog(models.Model):
    """Effective-dated plate/emirate history, so plate changes retain history."""
    _name = "fleetflow.vehicle.plate.log"
    _description = "FleetFlow Vehicle Plate History"
    _order = "effective_date desc, id desc"

    vehicle_id = fields.Many2one(
        "fleet.vehicle", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="vehicle_id.company_id", store=True, index=True)
    emirate = fields.Char()
    plate_code = fields.Char()
    license_plate = fields.Char(required=True)
    effective_date = fields.Date(required=True, default=fields.Date.context_today)
    note = fields.Char()
