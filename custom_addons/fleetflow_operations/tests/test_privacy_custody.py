# -*- coding: utf-8 -*-
"""Regression for evidence-file privacy (F08) and custody integrity (F09).

Privacy: a document file linked to a credential is bound to that credential and
made private, so the compliance-only file restriction actually applies however
the file was created; sensitive document fields are not readable by a dispatcher.
Custody: odometer readings must be finite, non-decreasing (a zero return no
longer slips past), and reconciled against the vehicle's last accepted reading;
a defect links the allocation -> work order -> specific hold.

NOTE: authenticated HTTP download/export regressions are NOT exercised here (the
test harness runs with --no-http); these are ORM/model-level checks. HTTP privacy
is therefore reported as unverified, not verified.
"""
from datetime import date, datetime, time, timedelta

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase


@tagged("post_install", "-at_install")
class TestPrivacyCustody(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    def _iv(self, sh, eh, days_ahead=1):
        day = date.today() + timedelta(days=days_ahead)
        return datetime.combine(day, time(sh, 0)), datetime.combine(day, time(eh, 0))

    # -- F08: attachment binding & privacy -------------------------------
    def test_linked_attachment_is_bound_and_restricted(self):
        att = self.env["ir.attachment"].create({"name": "lic.pdf", "raw": b"%PDF-1.4 x"})
        cred = self.env["fleetflow.credential"].create({
            "name": "L", "doc_kind": "driver_licence", "company_id": self.company.id,
            "driver_id": self.driver.id, "attachment_id": att.id})
        att.invalidate_recordset(["res_model", "res_id", "public"])
        self.assertEqual(att.res_model, "fleetflow.credential")
        self.assertEqual(att.res_id, cred.id)
        self.assertFalse(att.public)
        with self.assertRaises(AccessError):
            att.with_user(self.dispatcher).check("read")
        att.with_user(self.compliance).check("read")  # compliance may

    def test_foreign_attachment_is_rebound_when_linked(self):
        # A file initially bound elsewhere (or public) cannot be smuggled in as a
        # credential file that side-steps the restriction: linking rebinds it.
        att = self.env["ir.attachment"].create({
            "name": "x.pdf", "raw": b"%PDF", "public": True,
            "res_model": "res.partner", "res_id": self.env.user.partner_id.id})
        cred = self.env["fleetflow.credential"].create({
            "name": "L2", "doc_kind": "insurance", "company_id": self.company.id,
            "vehicle_id": self.vehicle.id, "attachment_id": att.id})
        att.invalidate_recordset(["res_model", "res_id", "public"])
        self.assertEqual(att.res_model, "fleetflow.credential")
        self.assertEqual(att.res_id, cred.id)
        self.assertFalse(att.public)
        with self.assertRaises(AccessError):
            att.with_user(self.dispatcher).check("read")

    def test_dispatcher_cannot_read_sensitive_fields(self):
        cred = self.env["fleetflow.credential"].create({
            "name": "R", "doc_kind": "driver_licence", "company_id": self.company.id,
            "driver_id": self.driver.id, "reference": "SECRET-123", "note": "private"})
        # Dispatcher may read non-sensitive metadata...
        self.assertTrue(cred.with_user(self.dispatcher).read(["doc_kind", "state"]))
        # ...but not the document number or notes.
        with self.assertRaises(AccessError):
            cred.with_user(self.dispatcher).read(["reference"])
        with self.assertRaises(AccessError):
            cred.with_user(self.dispatcher).read(["note"])
        # Compliance can.
        self.assertEqual(cred.with_user(self.compliance).read(["reference"])[0]["reference"],
                         "SECRET-123")

    # -- F09: custody integrity ------------------------------------------
    def test_return_zero_does_not_bypass_decrease(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        alloc.action_checkout(odometer=5000)
        with self.assertRaises(ValidationError):
            alloc.action_return(odometer=0)

    def test_infinite_odometer_rejected(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        with self.assertRaises(ValidationError):
            alloc.action_checkout(odometer=float("inf"))
        self.assertEqual(alloc.state, "confirmed")

    def test_odometer_below_last_accepted_rejected(self):
        s1, e1 = self._iv(8, 12)
        s2, e2 = self._iv(13, 17)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        a.action_checkout(odometer=2000)
        a.action_return(odometer=3000)
        b = self.make_allocation(s2, e2, channels=self.enr, user=self.dispatcher)
        b.action_confirm()
        with self.assertRaises(ValidationError):
            b.action_checkout(odometer=1000)  # below the last accepted 3000

    def test_defect_links_allocation_order_and_hold(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        alloc.action_checkout(odometer=100)
        alloc.action_return(odometer=150, defect=True, condition="warning light")
        hold = self.env["fleetflow.vehicle.hold"].search([
            ("vehicle_id", "=", self.vehicle.id), ("hold_type", "=", "safety"),
            ("state", "=", "active")], limit=1)
        self.assertTrue(hold)
        self.assertEqual(hold.source_allocation_id, alloc)
        self.assertTrue(hold.source_work_order_id)
        self.assertEqual(hold.source_work_order_id.vehicle_id.id, self.vehicle.id)
