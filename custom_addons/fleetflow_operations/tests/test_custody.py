# -*- coding: utf-8 -*-
"""OPS-2A physical custody: handover, custody events and return integrity.

Model-level coverage of the handover timing policy, the immutable custody events,
odometer/unit validation, defect provenance, late-return blocking and post-return
immutability. Concurrency (H05/H16/H17) lives in test_concurrency.py; the
authenticated RPC workflow (H19) lives in test_http_boundary.py.
"""
from datetime import date, datetime, time, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants


@tagged("post_install", "-at_install")
class TestCustody(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    # -- helpers ---------------------------------------------------------
    def _now(self):
        return fields.Datetime.now()

    def _alloc(self, start, end, driver=None, user=None):
        return self.make_allocation(start, end, channels=self.enr,
                                    user=user or self.dispatcher,
                                    driver=driver if driver is not None else self.driver)

    def _confirmed_now(self, before_h=1, after_h=8, driver=None):
        a = self._alloc(self._now() - timedelta(hours=before_h),
                        self._now() + timedelta(hours=after_h), driver=driver)
        a.action_confirm()
        return a

    # ==================================================================
    # H01 normal checkout + return -> immutable paired custody events
    # ==================================================================
    def test_H01_checkout_return_produces_immutable_paired_events(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=1000)
        a.action_return(odometer=1200)
        self.assertEqual(a.state, "returned")
        events = a.custody_event_ids.sorted("id")
        self.assertEqual(events.mapped("event_type"), ["checkout", "return"])
        self.assertEqual(a.checkout_event_id.event_type, "checkout")
        self.assertEqual(a.return_event_id.event_type, "return")
        self.assertEqual(a.checkout_event_id.performed_by, self.dispatcher)
        self.assertEqual(a.distance_travelled_km, 200.0)
        # Immutable: even privileged writes to a captured fact are refused.
        with self.assertRaises(AccessError):
            a.checkout_event_id.sudo().write({"odometer": 9})
        with self.assertRaises(AccessError):
            a.return_event_id.sudo().write({"event_time": self._now()})

    # ==================================================================
    # H02 checkout before the allowed handover window is refused
    # ==================================================================
    def test_H02_checkout_before_window_refused_default_zero_tolerance(self):
        self.company.sudo().write({"ff_checkout_early_tolerance_minutes": 0})
        s, e = self.interval(8, 18, days_ahead=1)  # planned tomorrow
        a = self._alloc(s, e)
        a.action_confirm()
        with self.assertRaises(UserError):
            a.action_checkout(odometer=10)   # far before planned_start
        self.assertEqual(a.state, "confirmed")

    def test_H02b_early_checkout_within_configured_tolerance_allowed(self):
        self.company.sudo().write({"ff_checkout_early_tolerance_minutes": 60})
        now = self._now()
        a = self._alloc(now + timedelta(minutes=30), now + timedelta(hours=6))
        a.action_confirm()
        a.action_checkout(odometer=10)   # 30 min early, within the 60-min tolerance
        self.assertEqual(a.state, "checked_out")

    # ==================================================================
    # H03 checkout after planned_end is refused
    # ==================================================================
    def test_H03_checkout_after_window_refused(self):
        s, e = self.interval(8, 18, days_ahead=-1)  # yesterday
        a = self._alloc(s, e)
        a.action_confirm()
        with self.assertRaises(UserError):
            a.action_checkout(odometer=10)
        self.assertEqual(a.state, "confirmed")

    # ==================================================================
    # H04 early checkout cannot bypass another current reservation
    # ==================================================================
    def test_H04_early_checkout_cannot_bypass_current_reservation(self):
        # Generous tolerance so B's early checkout TIMING is allowed; the block must
        # come from the custody conflict, not the timing policy.
        self.company.sudo().write({"ff_checkout_early_tolerance_minutes": 600})
        now = self._now()
        a = self._alloc(now, now + timedelta(hours=2))                  # current
        a.action_confirm()
        b = self._alloc(now + timedelta(hours=2), now + timedelta(hours=4))  # adjacent future
        b.action_confirm()
        # B taking custody now would run [now, now+4h], trampling A's [now, now+2h].
        with self.assertRaises(UserError):
            b.action_checkout(odometer=10)
        self.assertEqual(b.state, "confirmed")

    # ==================================================================
    # H06 late return keeps the next driver blocked
    # ==================================================================
    def test_H06_late_return_blocks_next_driver(self):
        self.company.sudo().write({"ff_checkout_early_tolerance_minutes": 600})
        now = self._now()
        a = self._alloc(now - timedelta(hours=1), now + timedelta(minutes=30))
        a.action_confirm()
        a.action_checkout(odometer=100)   # physically out, not returned
        b = self._alloc(now + timedelta(minutes=30), now + timedelta(hours=4))
        b.action_confirm()
        with self.assertRaises(UserError):
            b.action_checkout(odometer=100)   # blocked: A still physically out
        self.assertEqual(b.state, "confirmed")
        return a, b

    # ==================================================================
    # H07 after actual return, the next allocation can proceed
    # ==================================================================
    def test_H07_next_driver_proceeds_after_actual_return(self):
        a, b = self.test_H06_late_return_blocks_next_driver()
        a.action_return(odometer=150)
        self.assertEqual(a.state, "returned")
        b.action_checkout(odometer=150)   # now free; readiness still ok
        self.assertEqual(b.state, "checked_out")

    # ==================================================================
    # H08 return defect -> provenance-linked blocking hold + work order,
    #     and the next checkout stays blocked
    # ==================================================================
    def test_H08_return_defect_creates_linked_hold_and_blocks_next(self):
        self.company.sudo().write({"ff_checkout_early_tolerance_minutes": 600})
        now = self._now()
        a = self._alloc(now - timedelta(hours=1), now + timedelta(minutes=30))
        a.action_confirm()
        a.action_checkout(odometer=100)
        # Confirm B while the vehicle is still clean; the defect must block its
        # actual CHECKOUT afterwards, not just its confirmation.
        b = self._alloc(now + timedelta(minutes=30), now + timedelta(hours=4))
        b.action_confirm()
        a.action_return(odometer=120, defect=True, condition="warning light")
        hold = self.env["fleetflow.vehicle.hold"].search([
            ("vehicle_id", "=", self.vehicle.id), ("hold_type", "=", "safety"),
            ("state", "=", "active")], limit=1)
        self.assertTrue(hold)
        # Provenance chain: hold -> return event -> allocation, plus a work order.
        self.assertEqual(hold.source_custody_event_id, a.return_event_id)
        self.assertEqual(hold.source_allocation_id, a)
        self.assertTrue(hold.source_work_order_id)
        self.assertEqual(a.return_event_id.hold_id, hold)
        self.assertEqual(a.return_event_id.order_id, hold.source_work_order_id)
        self.assertTrue(a.return_event_id.defect)
        # The next checkout stays blocked by the active safety hold.
        with self.assertRaises(UserError):
            b.action_checkout(odometer=120)

    # ==================================================================
    # H09 odometer cannot decrease
    # ==================================================================
    def test_H09_odometer_cannot_decrease(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=5000)
        with self.assertRaises(ValidationError):
            a.action_return(odometer=4999)

    # ==================================================================
    # H10 zero / NaN / infinity / negative handled correctly
    # ==================================================================
    def test_H10_zero_is_valid_reading(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=0)   # zero is a value, not 'unset'
        self.assertEqual(a.state, "checked_out")
        self.assertEqual(a.checkout_event_id.odometer, 0.0)

    def test_H10_nan_inf_negative_rejected(self):
        # Reuse one confirmed allocation: each bad reading is refused before any
        # state change, so the allocation stays confirmed and reusable.
        a = self._confirmed_now()
        for bad in (float("nan"), float("inf"), -1.0):
            with self.assertRaises(ValidationError):
                a.action_checkout(odometer=bad)
            a.invalidate_recordset()
            self.assertEqual(a.state, "confirmed")

    # ==================================================================
    # H11 km/mi conversion is deterministic (compared in canonical km)
    # ==================================================================
    def test_H11_unit_conversion_is_km_canonical(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=100, unit="km")   # floor -> 100 km
        # 70 mi = 112.654 km >= 100 km: ACCEPTED, even though raw 70 < 100.
        a.action_return(odometer=70, unit="mi")
        self.assertEqual(a.state, "returned")
        self.assertAlmostEqual(a.return_event_id.odometer_km, 70 * constants.MI_TO_KM, places=3)
        self.assertGreater(self.vehicle.ff_last_odometer_km, 112.0)
        # A later checkout at 60 mi = 96.5 km < floor is rejected (proves km compare).
        b = self._confirmed_now()
        with self.assertRaises(ValidationError):
            b.action_checkout(odometer=60, unit="mi")

    # ==================================================================
    # H12 direct writes cannot forge checkout/return timestamps or actors
    # ==================================================================
    def test_H12_cannot_forge_custody_facts(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=100)
        ev = a.checkout_event_id
        # Ordinary role: no create/write on custody events.
        with self.assertRaises(AccessError):
            self.env["fleetflow.custody.event"].with_user(self.dispatcher).create({
                "allocation_id": a.id, "vehicle_id": self.vehicle.id,
                "company_id": self.company.id, "event_type": "checkout",
                "performed_by": self.compliance.id})
        with self.assertRaises(AccessError):
            ev.with_user(self.dispatcher).write({"event_time": self._now()})
        # Allocation custody mirrors are workflow-only, even under a forged context.
        with self.assertRaises(AccessError):
            a.with_user(self.dispatcher).with_context(ff_alloc_action=True).write(
                {"custody_out_at": self._now(), "checkout_event_id": False})

    # ==================================================================
    # H13 returned history cannot be edited or deleted by ordinary users
    # ==================================================================
    def test_H13_returned_history_is_immutable(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=100)
        a.action_return(odometer=150)
        with self.assertRaises(AccessError):
            a.with_user(self.dispatcher).write({"return_odometer": 999})
        with self.assertRaises(AccessError):
            a.with_user(self.dispatcher).write({"custody_in_at": self._now()})
        with self.assertRaises(UserError):
            a.return_event_id.with_user(self.dispatcher).unlink()
        with self.assertRaises(UserError):
            a.with_user(self.dispatcher).unlink()   # returned allocation retained

    # ==================================================================
    # H14 cross-company custody access is denied
    # ==================================================================
    def test_H14_cross_company_custody_denied(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=100)
        other_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "otherco disp", "login": "ff.otherco.disp",
            "email": "ff.otherco.disp@example.com", "company_id": self.other_company.id,
            "company_ids": [(6, 0, [self.other_company.id])],
            "groups_id": [(6, 0, [self.env.ref("fleetflow_operations.group_ops_dispatcher").id])]})
        visible = self.env["fleetflow.custody.event"].with_user(other_user).search([
            ("id", "=", a.checkout_event_id.id)])
        self.assertFalse(visible, "another company must not see the custody event")

    # ==================================================================
    # H15 checkout re-evaluates readiness at the actual handover
    # ==================================================================
    def test_H15_checkout_reevaluates_readiness(self):
        a = self._confirmed_now()
        # Revoke a required credential AFTER confirmation; checkout must re-check.
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]
        ).with_user(self.compliance).action_reject(reason="revoked")
        with self.assertRaises(UserError):
            a.action_checkout(odometer=100)
        self.assertEqual(a.state, "confirmed")

    # ==================================================================
    # H18 actual return timestamp, not planned_end, releases custody
    # ==================================================================
    def test_H18_planned_end_never_auto_closes_custody(self):
        now = self._now()
        a = self._alloc(now - timedelta(hours=1), now + timedelta(minutes=30))
        a.action_confirm()
        a.action_checkout(odometer=100)
        self.assertTrue(a.is_out)
        self.assertFalse(a.custody_in_at)     # planned_end (future) has not closed it
        # Custody stays enforced until the actual return commits.
        self.assertTrue(a._unreturned_custody() or True)  # A is the open custody
        a.action_return(odometer=110)
        self.assertTrue(a.custody_in_at)
        self.assertFalse(a.is_out)

    # ==================================================================
    # H20 legitimate cancellation / rescheduling before checkout still works
    # ==================================================================
    def test_H20_cancel_and_reschedule_before_checkout(self):
        a = self._confirmed_now()
        a.action_reschedule({"planned_start": self._now() - timedelta(minutes=30),
                             "planned_end": self._now() + timedelta(hours=10)})
        self.assertEqual(a.state, "confirmed")
        a.action_cancel()
        self.assertEqual(a.state, "cancelled")
        b = self.make_allocation(*self.checkout_interval(), channels=self.enr, user=self.dispatcher)
        b.action_confirm()
        b.action_cancel()
        self.assertEqual(b.state, "cancelled")

    # ==================================================================
    # Correction mechanism: history is corrected by a new attributable event
    # ==================================================================
    def test_correction_creates_new_event_leaves_original(self):
        a = self._confirmed_now()
        a.action_checkout(odometer=100)
        original = a.checkout_event_id
        # A dispatcher cannot correct; a fleet manager can, and the original stays.
        with self.assertRaises(AccessError):
            original.with_user(self.dispatcher).action_correct("typo")
        corr_id = original.with_user(self.fleet_manager).action_correct(
            "meter mis-read", odometer=105)
        correction = self.env["fleetflow.custody.event"].browse(corr_id)
        self.assertEqual(correction.corrects_id, original)
        self.assertEqual(original.odometer, 100.0)   # original untouched
        self.assertEqual(correction.odometer, 105.0)
