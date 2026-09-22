# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta, date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase


@tagged("post_install", "-at_install")
class TestAllocation(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    def _interval(self, sh, eh, days_ahead=1):
        day = date.today() + timedelta(days=days_ahead)
        return datetime.combine(day, time(sh, 0)), datetime.combine(day, time(eh, 0))

    def test_confirm_ready_then_checkout_and_return(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        self.assertEqual(alloc.state, "confirmed")
        self.assertEqual(alloc.readiness_status, "ready")
        alloc.action_checkout(odometer=1000)
        self.assertEqual(alloc.state, "checked_out")
        self.assertTrue(alloc.custody_out_at)
        alloc.action_return(odometer=1200, fuel="full", condition="ok")
        self.assertEqual(alloc.state, "returned")
        self.assertTrue(alloc.custody_in_at)

    def test_confirm_blocked_when_not_ready(self):
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]).unlink()
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        with self.assertRaises(UserError):
            alloc.action_confirm()
        self.assertEqual(alloc.state, "draft")

    def test_two_allocations_same_vehicle_conflict(self):
        s, e = self._interval(8, 18)
        a = self.make_allocation(s, e, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        # Second overlapping allocation on the same vehicle, different driver.
        d2 = self.env["fleetflow.driver"].create({"name": "D2", "company_id": self.company.id})
        for kind in ("driver_licence", "professional_permit"):
            self.make_credential(kind, "driver_id", d2)
        self.make_channel("uber", "UberX", "driver_id", d2)
        b = self.make_allocation(s, e, driver=d2, channels=self.uber_enrolment(), user=self.dispatcher)
        with self.assertRaises(UserError):
            b.action_confirm()

    def test_two_cars_same_driver_conflict(self):
        s, e = self._interval(8, 18)
        a = self.make_allocation(s, e, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        v2 = self.env["fleet.vehicle"].create({
            "model_id": self.vehicle.model_id.id, "license_plate": "OPS-2",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id,
            "ff_operational_state": "reviewed"})
        for kind in ("vehicle_registration", "insurance"):
            self.make_credential(kind, "vehicle_id", v2)
        b = self.make_allocation(s, e, vehicle=v2, channels=self.enr, user=self.dispatcher)
        with self.assertRaises(UserError):
            b.action_confirm()

    def test_adjacent_intervals_are_allowed(self):
        s1, e1 = self._interval(8, 12)
        s2, e2 = self._interval(12, 16)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        b = self.make_allocation(s2, e2, channels=self.enr, user=self.dispatcher)
        b.action_confirm()  # half-open [8,12) and [12,16) do not overlap
        self.assertEqual(b.state, "confirmed")

    def test_late_return_blocks_second_checkout(self):
        s1, e1 = self._interval(8, 12)
        s2, e2 = self._interval(12, 16)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        a.action_checkout()  # out, not yet returned (late return)
        b = self.make_allocation(s2, e2, channels=self.enr, user=self.dispatcher)
        b.action_confirm()  # planning ok (adjacent)
        with self.assertRaises(UserError):
            b.action_checkout()  # blocked: vehicle still physically out

    def test_active_hold_blocks_checkout(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        self.env["fleetflow.vehicle.hold"].create({
            "vehicle_id": self.vehicle.id, "hold_type": "safety", "reason": "brake fault",
            "dispatch_blocking": True})
        with self.assertRaises(UserError):
            alloc.action_checkout()

    def test_clearing_one_hold_keeps_others(self):
        h1 = self.env["fleetflow.vehicle.hold"].create({
            "vehicle_id": self.vehicle.id, "hold_type": "safety", "reason": "brakes"})
        h2 = self.env["fleetflow.vehicle.hold"].create({
            "vehicle_id": self.vehicle.id, "hold_type": "document", "reason": "insurance query"})
        h1.with_user(self.fleet_manager).action_clear(note="brakes fixed and inspected")
        self.assertEqual(h1.state, "cleared")
        self.assertEqual(h2.state, "active")
        # Readiness still blocked by the remaining hold.
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], "blocked")

    def test_work_order_release_does_not_clear_hold(self):
        order = self.env["fleetflow.order"].sudo().create({
            "title": "Service", "vehicle_id": self.vehicle.id, "company_id": self.company.id})
        hold = self.env["fleetflow.vehicle.hold"].create({
            "vehicle_id": self.vehicle.id, "hold_type": "maintenance", "reason": "service due",
            "source_work_order_id": order.id})
        # Cancelling the source work order must not clear the independent hold.
        order.sudo().write({"decision_notes": "dup"})
        order.sudo().action_cancel()
        self.assertEqual(hold.state, "active")

    def test_rental_capacity_block_conflicts_with_shift(self):
        s, e = self._interval(8, 18)
        rental = self.make_allocation(s, e, driver=self.env["fleetflow.driver"], mode="rental",
                                      user=self.dispatcher)
        # A rental capacity block confirms without a driver requirement.
        self.publish_profile("rental", require_operating_authorization=False,
                             require_vehicle_registration=True, require_insurance=True,
                             require_driver_licence=False, require_professional_permit=False,
                             require_channel_approval=False, enforce_end_of_use=False)
        rental.action_confirm()
        # A chauffeur shift on the same vehicle/interval conflicts.
        shift = self.make_allocation(s, e, channels=self.enr, user=self.dispatcher)
        with self.assertRaises(UserError):
            shift.action_confirm()

    def test_odometer_decrease_rejected(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        alloc.action_checkout(odometer=5000)
        with self.assertRaises(ValidationError):
            alloc.action_return(odometer=4000)  # silent decrease not accepted

    def test_defect_return_creates_hold_and_order(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        alloc.action_checkout(odometer=100)
        orders_before = self.env["fleetflow.order"].search_count([("vehicle_id", "=", self.vehicle.id)])
        alloc.action_return(odometer=150, defect=True, condition="warning light")
        self.assertTrue(self.env["fleetflow.vehicle.hold"].search_count([
            ("vehicle_id", "=", self.vehicle.id), ("state", "=", "active"), ("hold_type", "=", "safety")]))
        self.assertEqual(
            self.env["fleetflow.order"].search_count([("vehicle_id", "=", self.vehicle.id)]),
            orders_before + 1)

    def test_cancel_before_checkout(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        alloc.action_cancel()
        self.assertEqual(alloc.state, "cancelled")
        alloc.action_checkout  # no-op ref
        with self.assertRaises(UserError):
            alloc.action_checkout()
