# -*- coding: utf-8 -*-
"""Reproduction + regression for the dispatch-integrity review (F01, F02, F04).

These tests target the *authority and lifecycle* bypasses: the caller-controlled
context flags, the draft-reset payloads, post-confirmation plan edits, and direct
forging of approval/verified/published state. They are written to FAIL against
the reviewed commit (where the bypasses exist) and to PASS once the guards are
made unconditional. Every attempt uses an ordinary role account with legitimate
model write access -- a read-only user's denial does not prove a workflow guard.
"""
from datetime import date, datetime, time, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase


@tagged("post_install", "-at_install")
class TestLifecycleBypass(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    def _interval(self, sh, eh, days_ahead=1):
        day = date.today() + timedelta(days=days_ahead)
        return datetime.combine(day, time(sh, 0)), datetime.combine(day, time(eh, 0))

    # -- F01: context flag is not a capability ---------------------------
    def test_ff_alloc_action_context_cannot_forge_state(self):
        """A caller-supplied ff_alloc_action context must NOT bypass the guard."""
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        with self.assertRaises(AccessError):
            alloc.with_user(self.dispatcher).with_context(
                ff_alloc_action=True).write({"state": "confirmed"})
        with self.assertRaises(AccessError):
            alloc.with_user(self.dispatcher).with_context(
                ff_alloc_action=True).write({"custody_out_at": datetime.now()})
        self.assertEqual(alloc.state, "draft")
        self.assertFalse(alloc.custody_out_at)

    def test_draft_reset_payload_cannot_smuggle_custody(self):
        """state='draft' in the payload must not open the door to custody edits."""
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        with self.assertRaises(AccessError):
            alloc.with_user(self.dispatcher).write({
                "state": "draft", "custody_out_at": datetime.now(),
                "readiness_status": "ready"})
        self.assertFalse(alloc.custody_out_at)

    def test_confirmed_cannot_be_reset_to_draft(self):
        """Resetting a confirmed/checked-out allocation to draft would drop it out
        of the occupied set; it must be refused (cancel instead)."""
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        with self.assertRaises(AccessError):
            alloc.with_user(self.dispatcher).write({"state": "draft"})
        self.assertEqual(alloc.state, "confirmed")

    def test_checked_out_reset_to_draft_refused(self):
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        alloc.action_checkout(odometer=100)
        with self.assertRaises(AccessError):
            alloc.with_user(self.dispatcher).write({
                "state": "draft", "custody_out_at": False})
        self.assertEqual(alloc.state, "checked_out")

    # -- F02: planning fields are locked after confirmation --------------
    def test_confirmed_dates_locked_server_side(self):
        """Editing planned dates on a confirmed allocation must be refused at the
        server, not merely made readonly in the form."""
        s1, e1 = self._interval(8, 12)
        s2, e2 = self._interval(12, 16)
        a = self.make_allocation(s1, e1, channels=self.enr, user=self.dispatcher)
        a.action_confirm()
        b = self.make_allocation(s2, e2, channels=self.enr, user=self.dispatcher)
        b.action_confirm()
        # Try to stretch b back over a's interval via a plain write.
        with self.assertRaises(AccessError):
            b.with_user(self.dispatcher).write({"planned_start": s1})
        self.assertEqual(b.planned_start, s2)

    def test_confirmed_vehicle_change_refused(self):
        v2 = self.env["fleet.vehicle"].create({
            "model_id": self.vehicle.model_id.id, "license_plate": "OPS-9",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id,
            "ff_operational_state": "reviewed"})
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        with self.assertRaises(AccessError):
            alloc.with_user(self.dispatcher).write({"vehicle_id": v2.id})

    def test_confirmed_allocation_cannot_be_deleted(self):
        # Use the fleet manager, who holds unlink rights on allocations (a
        # dispatcher has none), so the refusal is the lifecycle guard and not an
        # ACL denial.
        alloc = self.make_allocation(channels=self.enr, user=self.dispatcher)
        alloc.action_confirm()
        with self.assertRaises(UserError):
            alloc.with_user(self.fleet_manager).unlink()
        self.assertTrue(alloc.exists())
        # A draft one may be removed.
        draft = self.make_allocation(channels=self.enr, user=self.dispatcher)
        draft.with_user(self.fleet_manager).unlink()
        self.assertFalse(draft.exists())

    # -- F04: approval/verified/published state cannot be forged ---------
    def test_dispatcher_cannot_approve_channel(self):
        """action_approve must require a compliance reviewer, not merely channel
        write access (dispatchers have create/write on channel enrolments)."""
        enr = self.env["fleetflow.channel.enrolment"].with_user(self.dispatcher).create({
            "company_id": self.company.id, "channel": "careem", "product": "CareemX",
            "driver_id": self.driver.id})
        with self.assertRaises(AccessError):
            enr.with_user(self.dispatcher).action_approve()
        self.assertEqual(enr.state, "pending")

    def test_dispatcher_cannot_direct_write_channel_approved(self):
        enr = self.env["fleetflow.channel.enrolment"].with_user(self.dispatcher).create({
            "company_id": self.company.id, "channel": "careem", "product": "CareemX",
            "driver_id": self.driver.id})
        with self.assertRaises(AccessError):
            enr.with_user(self.dispatcher).write({
                "state": "approved", "verified_as_of": datetime.now()})
        self.assertEqual(enr.state, "pending")

    def test_authorization_verified_state_not_directly_writable(self):
        auth = self.env["fleetflow.operating.authorization"].create({
            "name": "AUTH-x", "company_id": self.company.id, "operating_mode": "chauffeur",
            "date_start": date.today() - timedelta(days=1),
            "date_end": date.today() + timedelta(days=30)})
        # Even a compliance reviewer must go through action_verify (attribution).
        with self.assertRaises(AccessError):
            auth.with_user(self.compliance).write({"state": "verified"})
        self.assertNotEqual(auth.state, "verified")

    def test_published_profile_is_frozen(self):
        profile = self.publish_profile(
            "rental", require_operating_authorization=False,
            require_vehicle_registration=True, require_insurance=True,
            require_driver_licence=False, require_professional_permit=False,
            require_channel_approval=False, enforce_end_of_use=False)
        self.assertEqual(profile.state, "published")
        # A published policy version is immutable; corrections make a new version.
        with self.assertRaises(UserError):
            profile.with_user(self.compliance).write({"require_insurance": False})
        with self.assertRaises(UserError):
            profile.with_user(self.compliance).write({"require_driver_licence": True})

    def test_vehicle_operational_state_not_directly_writable(self):
        """A fleet manager has vehicle write, but the operational review state is
        set only through the compliance-gated action."""
        v = self.env["fleet.vehicle"].create({
            "model_id": self.vehicle.model_id.id, "license_plate": "OPS-REV",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id})
        with self.assertRaises(AccessError):
            v.with_user(self.fleet_manager).write({"ff_operational_state": "reviewed"})
        self.assertEqual(v.ff_operational_state, "unreviewed")

    def test_supersession_keeps_old_coverage_until_renewal_verified(self):
        """A still-valid document must not be dropped the instant a renewal is
        drafted: the old evidence stays effective until the renewal is verified."""
        cred = self.make_credential("vehicle_registration", "vehicle_id", self.vehicle,
                                    end=date.today() + timedelta(days=10))
        renewal = cred.browse(cred.with_user(self.compliance).action_supersede({
            "name": "REG-renew", "date_start": date.today(),
            "date_end": date.today() + timedelta(days=400)}))
        # Renewal is not yet verified -> old must remain the effective, verified one.
        self.assertEqual(renewal.state, "draft")
        self.assertEqual(cred.state, "verified")
        self.assertFalse(cred.superseded_by_id)
        # Once verified, the renewal takes over and the old flips to superseded.
        renewal.with_user(self.compliance).action_verify()
        self.assertEqual(cred.state, "superseded")
        self.assertEqual(cred.superseded_by_id, renewal)
        self.assertEqual(renewal.supersedes_id, cred)
