# -*- coding: utf-8 -*-
"""Regression for the amendment path (F02) and physical checkout (F06).

Covers: a confirmed plan is amended only through the guarded Reschedule action,
which re-evaluates readiness and conflicts on the prospective values; physical
checkout is bound to the approved reservation window using authoritative server
time and evaluates the ACTUAL handover interval; non-blocking warnings need an
explicit acknowledgement; and physical rental checkout is disabled in OPS-1.
"""
from datetime import date, datetime, time, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants


@tagged("post_install", "-at_install")
class TestAmendmentCheckout(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    def _codes(self, result):
        return {r["code"] for r in result["reasons"]}

    def _iv(self, sh, eh, days_ahead=1):
        day = date.today() + timedelta(days=days_ahead)
        return datetime.combine(day, time(sh, 0)), datetime.combine(day, time(eh, 0))

    def _now_iv(self, before_h=1, after_h=8):
        now = fields.Datetime.now()
        return now - timedelta(hours=before_h), now + timedelta(hours=after_h)

    # -- F02: guarded amendment ------------------------------------------
    def test_reschedule_rejects_conflicting_amendment(self):
        s1, e1 = self._iv(8, 12)
        s2, e2 = self._iv(12, 16)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        b = self.make_allocation(s2, e2, channels=self.enr, user=self.dispatcher)
        b.action_confirm()
        # Amending b back over a's interval conflicts and must be refused; because
        # the check runs on prospective values, b is left completely unchanged.
        with self.assertRaises(UserError):
            b.with_user(self.dispatcher).action_reschedule(
                {"planned_start": s1, "planned_end": e1})
        self.assertEqual(b.planned_start, s2)
        self.assertEqual(b.planned_end, e2)

    def test_reschedule_valid_updates_plan_and_keeps_history(self):
        s1, e1 = self._iv(8, 12)
        s3, e3 = self._iv(16, 20)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        a.with_user(self.dispatcher).action_reschedule(
            {"planned_start": s3, "planned_end": e3})
        self.assertEqual(a.planned_start, s3)
        self.assertEqual(a.planned_end, e3)
        self.assertEqual(a.state, "confirmed")
        self.assertTrue(a.readiness_snapshot)
        # The previous decision is preserved in the chatter, not overwritten.
        self.assertTrue(any("Previous plan" in (m or "")
                            for m in a.message_ids.mapped("body")))

    def test_reschedule_requires_confirmed(self):
        draft = self.make_allocation(channels=self.enr, user=self.dispatcher)
        with self.assertRaises(UserError):
            draft.with_user(self.dispatcher).action_reschedule(
                {"planned_start": self._iv(9, 10)[0], "planned_end": self._iv(9, 10)[1]})

    def test_reschedule_via_form_amend_fields(self):
        # The Reschedule button path reads the amend_* inputs.
        s1, e1 = self._iv(8, 12)
        s3, e3 = self._iv(16, 20)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        a.with_user(self.dispatcher).write(
            {"amend_planned_start": s3, "amend_planned_end": e3})
        a.with_user(self.dispatcher).action_reschedule()
        self.assertEqual(a.planned_start, s3)
        self.assertFalse(a.amend_planned_start)  # inputs cleared after use

    # -- F06: checkout window / server time ------------------------------
    def test_checkout_refused_after_reservation_window(self):
        # A past interval still confirms (evidence is valid), but cannot be
        # physically handed over now: the reservation window has ended.
        s, e = self._iv(8, 18, days_ahead=-1)  # yesterday
        a = self.make_allocation(s, e, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        self.assertEqual(a.state, "confirmed")
        with self.assertRaises(UserError):
            a.action_checkout(odometer=10)
        self.assertEqual(a.state, "confirmed")

    def test_checkout_within_window_records_server_time(self):
        s, e = self._now_iv()
        a = self.make_allocation(s, e, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        a.action_checkout(odometer=10)
        self.assertEqual(a.state, "checked_out")
        self.assertTrue(a.custody_out_at)

    # -- F06: rental physical checkout disabled --------------------------
    def test_rental_physical_checkout_disabled(self):
        s, e = self._now_iv()
        self.publish_profile(
            "rental", require_operating_authorization=False,
            require_vehicle_registration=True, require_insurance=True,
            require_driver_licence=False, require_professional_permit=False,
            require_channel_approval=False, enforce_end_of_use=False)
        rental = self.make_allocation(
            s, e, driver=self.env["fleetflow.driver"], mode="rental", user=self.dispatcher)
        rental.action_confirm()  # capacity block confirms fine
        self.assertEqual(rental.state, "confirmed")
        with self.assertRaises(UserError):
            rental.action_checkout(odometer=10)
        self.assertEqual(rental.state, "confirmed")

    # -- F06: warning acknowledgement ------------------------------------
    def test_warning_requires_acknowledgement(self):
        s, e = self._now_iv()
        # Insurance valid for the interval but expiring within the warn window
        # just after it -> a non-blocking WARNING.
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]).unlink()
        self.make_credential("insurance", "vehicle_id", self.vehicle,
                             end=e.date() + timedelta(days=3))
        result = self.evaluate(user=self.dispatcher, start=s, end=e)
        self.assertEqual(result["status"], constants.WARNING, self._codes(result))
        a = self.make_allocation(s, e, channels=self.enr, user=self.dispatcher)
        # Unacknowledged warning is refused; a Blocked/Needs-review could not be
        # acknowledged past at all (it fails can_confirm first).
        with self.assertRaises(UserError):
            a.action_confirm()
        self.assertEqual(a.state, "draft")
        a.action_confirm(acknowledge=True)
        self.assertEqual(a.state, "confirmed")
        self.assertEqual(a.warnings_ack_by, self.dispatcher)
