# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase


@tagged("post_install", "-at_install")
class TestSecurity(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    # -- Forged states ---------------------------------------------------
    def test_cannot_forge_allocation_confirmed_via_write(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        with self.assertRaises(AccessError):
            alloc.write({"state": "confirmed"})
        with self.assertRaises(AccessError):
            alloc.write({"custody_out_at": date.today()})
        self.assertEqual(alloc.state, "draft")

    def test_cannot_forge_allocation_confirmed_via_create_context(self):
        alloc = self.env["fleetflow.allocation"].with_user(self.dispatcher).with_context(
            default_state="confirmed", default_confirmed_by=self.dispatcher.id,
        ).create({
            "company_id": self.company.id, "operating_mode": "chauffeur",
            "vehicle_id": self.vehicle.id, "driver_id": self.driver.id,
            "planned_start": "2026-10-01 08:00:00", "planned_end": "2026-10-01 18:00:00",
            "state": "confirmed", "confirmed_by": self.dispatcher.id,
        })
        self.assertEqual(alloc.state, "draft")
        self.assertFalse(alloc.confirmed_by)

    def test_cannot_forge_hold_cleared_via_write(self):
        hold = self.env["fleetflow.vehicle.hold"].with_user(self.fleet_manager).create({
            "vehicle_id": self.vehicle.id, "hold_type": "safety", "reason": "x"})
        with self.assertRaises(AccessError):
            hold.write({"state": "cleared"})
        self.assertEqual(hold.state, "active")

    # -- Role gates ------------------------------------------------------
    def test_driver_cannot_verify_own_evidence(self):
        driver_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "drv", "login": "drv.self", "email": "drv.self@x.com",
            "company_id": self.company.id, "company_ids": [(6, 0, self.company.ids)],
            "groups_id": [(6, 0, [self.env.ref("fleetflow_operations.group_ops_driver").id])]})
        self.driver.user_id = driver_user.id
        cred = self.env["fleetflow.credential"].create({
            "name": "own lic", "doc_kind": "driver_licence", "company_id": self.company.id,
            "driver_id": self.driver.id})
        with self.assertRaises(AccessError):
            cred.with_user(driver_user).action_verify()

    def test_dispatcher_cannot_clear_hold(self):
        hold = self.env["fleetflow.vehicle.hold"].create({
            "vehicle_id": self.vehicle.id, "hold_type": "safety", "reason": "x"})
        with self.assertRaises(AccessError):
            hold.with_user(self.dispatcher).action_clear(note="trying")

    def test_driver_sees_only_own_allocations(self):
        driver_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "drv2", "login": "drv.own", "email": "drv.own@x.com",
            "company_id": self.company.id, "company_ids": [(6, 0, self.company.ids)],
            "groups_id": [(6, 0, [self.env.ref("fleetflow_operations.group_ops_driver").id])]})
        self.driver.user_id = driver_user.id
        mine = self.make_allocation(channels=self.enr, user=self.dispatcher)
        other_driver = self.env["fleetflow.driver"].create({
            "name": "Other", "company_id": self.company.id})
        theirs = self.make_allocation(driver=other_driver, user=self.dispatcher)
        visible = self.env["fleetflow.allocation"].with_user(driver_user).search([]).ids
        self.assertIn(mine.id, visible)
        self.assertNotIn(theirs.id, visible)

    # -- Cross-company ---------------------------------------------------
    def test_cross_company_relation_injection_fails(self):
        other_driver = self.env["fleetflow.driver"].create({
            "name": "Foreign", "company_id": self.other_company.id})
        # Odoo 16 assertRaises rejects a tuple; assert manually. A driver from
        # another company must not attach to this company's allocation.
        try:
            with self.cr.savepoint():
                self.env["fleetflow.allocation"].create({
                    "company_id": self.company.id, "operating_mode": "chauffeur",
                    "vehicle_id": self.vehicle.id, "driver_id": other_driver.id,
                    "planned_start": "2026-10-01 08:00:00", "planned_end": "2026-10-01 18:00:00"})
            self.fail("Cross-company driver injection should be rejected.")
        except (ValidationError, UserError, AccessError):
            pass

    def test_only_dispatcher_confirms(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        compliance_only = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "co", "login": "co.only", "email": "co.only@x.com",
            "company_id": self.company.id, "company_ids": [(6, 0, self.company.ids)],
            "groups_id": [(6, 0, [self.env.ref("fleetflow_operations.group_ops_compliance").id])]})
        with self.assertRaises(AccessError):
            alloc.with_user(compliance_only).action_confirm()
