# -*- coding: utf-8 -*-
"""Reproduction + regression for the approval-boundary review (R01, R02, R04, R05).

R01: an approved record's reviewed subject/scope cannot be mutated in place while
     keeping its approval (a dispatcher must not re-point an approval to another
     vehicle/city/product, or fake freshness by moving the recheck date).
R02: a verified/approved/published historical decision cannot be downgraded and
     rewritten in place; corrections are explicit new revisions.
R04: reviewed vehicle state, age exemptions, verified authorizations and published
     profiles cannot be forged at create/copy/default-context by an ordinary user.
R05: a hold's subject/severity/source is permanent history; it cannot be moved,
     downgraded to non-blocking, or deleted as an alternative clearance route.

Each attack uses an ordinary role account that HOLDS the relevant create/write
permission -- a read-only denial would not prove the workflow boundary. Superuser
is used only to build fixtures, never to perform the action under test.
"""
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase


@tagged("post_install", "-at_install")
class TestBoundaryAuthority(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()

    def _uber(self, field, subject):
        return self.env["fleetflow.channel.enrolment"].search([
            (field, "=", subject.id), ("channel", "=", "uber")], limit=1)

    # -- R01: an approved enrolment's identity is frozen -----------------
    def test_dispatcher_cannot_repoint_approved_enrolment_subject(self):
        enr = self._uber("driver_id", self.driver)
        self.assertEqual(enr.state, "approved")
        other = self.env["fleetflow.driver"].create({
            "name": "Other drv", "employee_ref": "OTH-D", "company_id": self.company.id})
        with self.assertRaises(AccessError):
            enr.with_user(self.dispatcher).write({"driver_id": other.id})
        enr.invalidate_recordset()
        self.assertEqual(enr.driver_id, self.driver)

    def test_dispatcher_cannot_change_approved_enrolment_scope(self):
        enr = self._uber("driver_id", self.driver)
        for vals in ({"city": "Abu Dhabi"}, {"product": "UberBlack"}, {"channel": "careem"}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                enr.with_user(self.dispatcher).write(vals)
        enr.invalidate_recordset()
        self.assertEqual((enr.city, enr.product, enr.channel), ("Dubai", "UberX", "uber"))

    def test_dispatcher_cannot_extend_recheck_on_approved(self):
        enr = self._uber("driver_id", self.driver)
        with self.assertRaises(AccessError):
            enr.with_user(self.dispatcher).write(
                {"recheck_date": date.today() + timedelta(days=999)})

    def test_reviewer_can_manage_recheck_on_approved(self):
        enr = self._uber("driver_id", self.driver)
        enr.with_user(self.compliance).write({"recheck_date": date.today() + timedelta(days=30)})
        self.assertEqual(enr.recheck_date, date.today() + timedelta(days=30))

    def test_enrolment_evidence_must_match_subject(self):
        driver_cred = self.make_credential("driver_licence", "driver_id", self.driver)
        # A vehicle-subject enrolment cannot borrow a driver's credential as proof.
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["fleetflow.channel.enrolment"].create({
                "company_id": self.company.id, "channel": "careem", "product": "CareemX",
                "vehicle_id": self.vehicle.id, "evidence_id": driver_cred.id})

    # -- R02: no historical rewrite via downgrade ------------------------
    def test_verified_credential_cannot_be_downgraded(self):
        cred = self.make_credential("vehicle_registration", "vehicle_id", self.vehicle)
        with self.assertRaises(AccessError):
            cred.with_user(self.compliance).write({"state": "draft"})
        self.assertEqual(cred.state, "verified")

    def test_rejected_credential_content_frozen(self):
        cred = self.env["fleetflow.credential"].create({
            "name": "REJ", "doc_kind": "insurance", "company_id": self.company.id,
            "vehicle_id": self.vehicle.id})
        cred.with_user(self.compliance).action_reject()
        with self.assertRaises(UserError):
            cred.with_user(self.compliance).write({"date_end": date.today() + timedelta(days=10)})

    def test_suspended_enrolment_cannot_be_reset_to_pending(self):
        enr = self.make_channel("careem", "CareemX", "driver_id", self.driver, state="suspended")
        for user in (self.dispatcher, self.compliance):
            with self.assertRaises(AccessError), self.cr.savepoint():
                enr.with_user(user).write({"state": "pending"})
        self.assertEqual(enr.state, "suspended")

    def test_verified_authorization_cannot_be_downgraded(self):
        auth = self.make_authorization("chauffeur")
        with self.assertRaises(AccessError):
            auth.with_user(self.compliance).write({"state": "draft"})
        self.assertEqual(auth.state, "verified")

    def test_published_profile_cannot_be_unpublished(self):
        prof = self.env["fleetflow.operating.profile"].search([
            ("state", "=", "published"), ("operating_mode", "=", "chauffeur")], limit=1)
        self.assertTrue(prof)
        with self.assertRaises(UserError):
            prof.with_user(self.compliance).write({"state": "draft"})
        self.assertEqual(prof.state, "published")

    # -- R04: forging review state at create / default context -----------
    def test_manager_cannot_forge_reviewed_vehicle_at_create(self):
        v = self.env["fleet.vehicle"].with_user(self.fleet_manager).create({
            "model_id": self.vehicle.model_id.id, "license_plate": "FORGE-1",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id,
            "ff_operational_state": "reviewed", "ff_end_of_use_exempt": True,
            "ff_authorized_end_of_use": date.today() + timedelta(days=10)})
        self.assertEqual(v.ff_operational_state, "unreviewed")
        self.assertFalse(v.ff_end_of_use_exempt)
        self.assertFalse(v.ff_authorized_end_of_use)

    def test_default_context_cannot_forge_reviewed_vehicle(self):
        v = self.env["fleet.vehicle"].with_user(self.fleet_manager).with_context(
            default_ff_operational_state="reviewed",
            default_ff_end_of_use_exempt=True).create({
            "model_id": self.vehicle.model_id.id, "license_plate": "FORGE-2",
            "company_id": self.company.id})
        self.assertEqual(v.ff_operational_state, "unreviewed")
        self.assertFalse(v.ff_end_of_use_exempt)

    def test_cannot_forge_verified_authorization_at_create(self):
        auth = self.env["fleetflow.operating.authorization"].with_user(self.compliance).create({
            "name": "FORGE-AUTH", "company_id": self.company.id, "operating_mode": "chauffeur",
            "state": "verified", "verified_by": self.compliance.id,
            "date_end": date.today() + timedelta(days=100)})
        self.assertNotEqual(auth.state, "verified")
        self.assertFalse(auth.verified_by)

    def test_cannot_forge_published_profile_at_create(self):
        prof = self.env["fleetflow.operating.profile"].with_user(self.compliance).create({
            "name": "FORGE-PROF", "company_id": self.company.id, "operating_mode": "rental",
            "state": "published"})
        self.assertEqual(prof.state, "draft")

    # -- R05: hold history is permanent ----------------------------------
    def _hold(self):
        return self.env["fleetflow.vehicle.hold"].create({
            "vehicle_id": self.vehicle.id, "hold_type": "safety",
            "reason": "brake fault", "dispatch_blocking": True})

    def test_manager_cannot_delete_hold(self):
        hold = self._hold()
        with self.assertRaises(UserError):
            hold.with_user(self.fleet_manager).unlink()
        self.assertTrue(hold.exists())

    def test_manager_cannot_downgrade_blocking_flag(self):
        hold = self._hold()
        with self.assertRaises(AccessError):
            hold.with_user(self.fleet_manager).write({"dispatch_blocking": False})
        hold.invalidate_recordset()
        self.assertTrue(hold.dispatch_blocking)

    def test_manager_cannot_move_hold_to_other_vehicle(self):
        hold = self._hold()
        v2 = self.env["fleet.vehicle"].create({
            "model_id": self.vehicle.model_id.id, "license_plate": "HOLD-2",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id})
        with self.assertRaises(AccessError):
            hold.with_user(self.fleet_manager).write({"vehicle_id": v2.id})

    def test_authorized_clear_is_attributable_and_still_works(self):
        hold = self._hold()
        hold.with_user(self.fleet_manager).action_clear(note="inspected and repaired")
        self.assertEqual(hold.state, "cleared")
        self.assertEqual(hold.cleared_by, self.fleet_manager)
        self.assertTrue(hold.cleared_on)
        self.assertEqual(hold.clear_note, "inspected and repaired")
