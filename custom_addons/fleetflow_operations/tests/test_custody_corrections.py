# -*- coding: utf-8 -*-
"""OPS-2A corrections: accurate handover capture + operationally effective corrections.

Covers input resolution (form save + no-argument button), event-specific unit display,
validated and effective corrections, and the safety-condition dispatch policy. The
button path is exercised by SAVING form fields then calling the action with NO
measurement arguments -- not by passing every value directly.
"""
from datetime import date, datetime, time, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants


@tagged("post_install", "-at_install")
class TestCustodyCorrections(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    # -- helpers ---------------------------------------------------------
    def _confirmed(self):
        a = self.make_allocation(*self.checkout_interval(), channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        return a

    def _fresh_checked_out(self, odo=100, unit="km"):
        a = self._confirmed()
        a.action_checkout(odometer=odo, unit=unit)
        return a

    # ==================================================================
    # F01 — saved form values + no-argument Checkout produce the event
    # ==================================================================
    def test_F01_saved_form_values_flow_into_event(self):
        a = self._confirmed()
        # The dispatcher fills the form, then presses Check out (no method args).
        a.with_user(self.dispatcher).write({
            "checkout_odometer": 1000, "odometer_unit": "km",
            "checkout_condition_code": "clean", "checkout_energy_kind": "fuel",
            "checkout_energy_level": 40, "checkout_notes": "pre-trip ok"})
        a.with_user(self.dispatcher).action_checkout()   # pure button path
        ev = a.checkout_event_id
        self.assertEqual(ev.odometer, 1000.0)
        self.assertEqual(ev.condition, "clean")   # NOT the 'acceptable' default
        self.assertEqual(ev.energy_kind, "fuel")
        self.assertEqual(ev.energy_level, 40)
        self.assertEqual(ev.notes, "pre-trip ok")
        # Allocation mirror and immutable event agree.
        self.assertEqual(a.checkout_condition_code, "clean")
        self.assertEqual(a.checkout_energy_level, 40)

    # ==================================================================
    # F02 — API args and form fallback follow one validated policy;
    #       zero vs omitted energy stays distinguishable
    # ==================================================================
    def test_F02_explicit_args_override_form(self):
        a = self._confirmed()
        a.with_user(self.dispatcher).write({
            "checkout_energy_kind": "fuel", "checkout_energy_level": 40})
        a.with_user(self.dispatcher).action_checkout(
            odometer=500, energy_kind="ev", energy_level=90)
        ev = a.checkout_event_id
        self.assertEqual(ev.energy_kind, "ev")   # argument wins over saved form
        self.assertEqual(ev.energy_level, 90)

    def test_F02_measured_zero_vs_not_recorded(self):
        # Measured 0% (kind set) is preserved; not-recorded (no kind) stays distinct.
        a = self._confirmed()
        a.with_user(self.dispatcher).action_checkout(odometer=10, energy_kind="ev", energy_level=0)
        self.assertEqual(a.checkout_event_id.energy_kind, "ev")
        self.assertEqual(a.checkout_event_id.energy_level, 0)   # measured empty battery
        b = self._confirmed_other_vehicle()
        b.action_checkout(odometer=10)   # no energy at all
        self.assertFalse(b.checkout_event_id.energy_kind)       # not recorded
        self.assertEqual(b.checkout_event_id.energy_level, 0)

    def _confirmed_other_vehicle(self):
        v2 = self.env["fleet.vehicle"].create({
            "model_id": self.vehicle.model_id.id, "license_plate": "OPS-F02",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id,
            "ff_operational_state": "reviewed"})
        d2 = self.env["fleetflow.driver"].create({"name": "F02 d2", "company_id": self.company.id})
        for kind in ("vehicle_registration", "insurance"):
            self.make_credential(kind, "vehicle_id", v2)
        for kind in ("driver_licence", "professional_permit"):
            self.make_credential(kind, "driver_id", d2)
        enr = (self.make_channel("uber", "UberX", "vehicle_id", v2)
               + self.make_channel("uber", "UberX", "driver_id", d2))
        a = self.make_allocation(*self.checkout_interval(), vehicle=v2, driver=d2,
                                 channels=enr, user=self.dispatcher)
        a.action_confirm()
        return a

    # ==================================================================
    # F03 — mixed-unit checkout/return history shows each original unit
    # ==================================================================
    def test_F03_mixed_unit_history_display(self):
        a = self._confirmed()
        a.action_checkout(odometer=100, unit="mi")          # 160.9344 km
        a.action_return(odometer=300, unit="km")            # 300 km >= floor
        self.assertEqual(a.checkout_event_id.odometer_unit, "mi")
        self.assertEqual(a.return_event_id.odometer_unit, "km")
        # Allocation mirrors keep each handover's OWN unit.
        self.assertEqual(a.odometer_unit, "mi")
        self.assertEqual(a.return_odometer_unit, "km")
        # Distance is canonical km: 300 - 160.9344.
        self.assertAlmostEqual(a.distance_travelled_km, 300 - 100 * constants.MI_TO_KM, places=3)

    # ==================================================================
    # F04 — a valid correction changes effective mileage/distance and the
    #       next checkout's validation, without changing original history
    # ==================================================================
    def test_F04_valid_correction_is_effective(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)
        orig = a.return_event_id
        corr_id = orig.with_user(self.fleet_manager).action_correct("meter mis-read", odometer=250)
        correction = self.env["fleetflow.custody.event"].browse(corr_id)
        # Original history is intact; the effective (tip) is the correction.
        self.assertEqual(orig.odometer, 200.0)
        self.assertEqual(orig._effective_tip(), correction)
        self.assertEqual(correction.odometer, 250.0)
        a.invalidate_recordset()
        self.assertEqual(a.distance_travelled_km, 150.0)     # 250 - 100
        self.assertEqual(self.vehicle.ff_last_odometer_km, 250.0)
        # Next checkout at 210 is refused (below the corrected floor); >=250 proceeds.
        b = self._confirmed()
        with self.assertRaises(ValidationError):
            b.action_checkout(odometer=210)
        b.action_checkout(odometer=260)
        self.assertEqual(b.state, "checked_out")

    # ==================================================================
    # F05 — invalid/decreasing/conflicting corrections fail cleanly
    # ==================================================================
    def test_F05_invalid_corrections_rejected(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)
        orig = a.return_event_id
        for bad in (float("nan"), float("inf"), -5.0, 90):   # 90 < checkout 100
            with self.assertRaises(ValidationError):
                orig.with_user(self.fleet_manager).action_correct("bad", odometer=bad)
        # Nothing moved: original, effective, floor and custody unchanged.
        orig.invalidate_recordset()
        self.assertEqual(orig.odometer, 200.0)
        self.assertEqual(orig._effective_tip(), orig)
        self.assertEqual(self.vehicle.ff_last_odometer_km, 200.0)
        self.assertEqual(a.state, "returned")

    def test_F05_correction_conflicting_with_later_reading_rejected(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)
        # A later accepted movement raises the floor to 210.
        b = self._confirmed()
        b.action_checkout(odometer=210)
        # Correcting A's earlier return above the later 210 reading must be refused.
        with self.assertRaises(ValidationError):
            a.return_event_id.with_user(self.fleet_manager).action_correct("late fix", odometer=250)
        a.return_event_id.invalidate_recordset()
        self.assertEqual(a.return_event_id.odometer, 200.0)
        self.assertEqual(self.vehicle.ff_last_odometer_km, 210.0)

    # ==================================================================
    # F06 — corrections never open or end physical possession
    # ==================================================================
    def test_F06_correction_does_not_change_custody(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)
        before = (a.state, a.custody_in_at, a.custody_out_at)
        a.return_event_id.with_user(self.fleet_manager).action_correct("notes only", notes="scratch")
        a.invalidate_recordset()
        self.assertEqual((a.state, a.custody_in_at, a.custody_out_at), before)
        self.assertFalse(a.is_out)

    # ==================================================================
    # F07 — safety-coded return triggers follow-up even with defect=false
    # ==================================================================
    def test_F07_safety_coded_return_raises_hold_without_defect(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=150, condition_code="warning_light", defect=False)
        hold = self.env["fleetflow.vehicle.hold"].search([
            ("vehicle_id", "=", self.vehicle.id), ("hold_type", "=", "safety"),
            ("state", "=", "active")], limit=1)
        self.assertTrue(hold, "a safety-coded condition must raise a blocking hold")
        self.assertEqual(hold.source_custody_event_id, a.return_event_id)
        self.assertEqual(a.state, "returned")   # still physically returned

    def test_F07_non_blocking_condition_raises_no_hold(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=150, condition_code="interior_issue", defect=False)
        self.assertFalse(self.env["fleetflow.vehicle.hold"].search_count([
            ("vehicle_id", "=", self.vehicle.id), ("hold_type", "=", "safety"),
            ("state", "=", "active")]))

    def test_F07_checkout_safety_condition_refused(self):
        a = self._confirmed()
        with self.assertRaises(UserError):
            a.action_checkout(odometer=100, condition_code="body_damage")
        self.assertEqual(a.state, "confirmed")
        # No hold persisted from the rolled-back handover.
        self.assertFalse(self.env["fleetflow.vehicle.hold"].search_count([
            ("vehicle_id", "=", self.vehicle.id), ("state", "=", "active")]))

    # ==================================================================
    # F08 — a safety defect added by correction blocks the next handover;
    #       later corrections do not silently clear that hold
    # ==================================================================
    def test_F08_correction_adds_safety_then_not_cleared(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)   # clean return, no hold
        self.assertFalse(self.env["fleetflow.vehicle.hold"].search_count([
            ("vehicle_id", "=", self.vehicle.id), ("state", "=", "active")]))
        # Confirm the next allocation while the vehicle is still clean.
        b = self._confirmed()
        corr_id = a.return_event_id.with_user(self.fleet_manager).action_correct(
            "defect found later", defect=True)
        correction = self.env["fleetflow.custody.event"].browse(corr_id)
        hold = self.env["fleetflow.vehicle.hold"].search([
            ("vehicle_id", "=", self.vehicle.id), ("hold_type", "=", "safety"),
            ("state", "=", "active")], limit=1)
        self.assertTrue(hold)
        self.assertEqual(hold.source_custody_event_id, correction)
        # Next checkout is now blocked by the correction-raised hold.
        with self.assertRaises(UserError):
            b.action_checkout(odometer=260)
        # A later correction back to defect=false must NOT clear the hold.
        correction.with_user(self.fleet_manager).action_correct("re-review", defect=False)
        hold.invalidate_recordset()
        self.assertEqual(hold.state, "active")

    # ==================================================================
    # F10 — authorized succeeds; unauthorized / foreign-company rejected
    # ==================================================================
    def test_F10_authorization_and_company_isolation(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)
        ev = a.return_event_id
        # A dispatcher cannot correct.
        with self.assertRaises(AccessError):
            ev.with_user(self.dispatcher).action_correct("nope", odometer=210)
        # A fleet manager can.
        ev.with_user(self.fleet_manager).action_correct("ok", odometer=210)
        # A foreign-company user cannot even see the event, let alone correct it.
        other = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "oc mgr", "login": "ff.oc.mgr", "email": "ff.oc.mgr@example.com",
            "company_id": self.other_company.id, "company_ids": [(6, 0, [self.other_company.id])],
            "groups_id": [(6, 0, [self.env.ref("fleetflow_operations.group_ops_fleet_manager").id])]})
        self.assertFalse(ev.with_user(other).search([("id", "=", ev.id)]))
        with self.assertRaises(AccessError):
            ev.with_user(other).action_correct("foreign", odometer=999)

    def test_F10_correction_field_allowlist(self):
        a = self._fresh_checked_out(odo=100)
        a.action_return(odometer=200)
        ev = a.return_event_id
        for bad in ({"vehicle_id": self.vehicle.id}, {"performed_by": self.dispatcher.id},
                    {"event_time": fields.Datetime.now()}, {"is_legacy": True},
                    {"odometer_km": 5}, {"allocation_id": a.id}):
            with self.assertRaises(UserError):
                ev.with_user(self.fleet_manager).action_correct("inject", **bad)
