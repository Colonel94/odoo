# -*- coding: utf-8 -*-
from datetime import date, datetime, time, timedelta

from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants


@tagged("post_install", "-at_install")
class TestReadiness(OperationsCase):

    def _codes(self, result):
        return {r["code"] for r in result["reasons"]}

    def test_valid_setup_is_ready_and_confirmable(self):
        self.ready_chauffeur_setup()
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.READY, self._codes(result))
        self.assertTrue(result["can_confirm"])

    def test_no_published_profile_is_needs_review(self):
        # Reviewed vehicle but no profile published at all.
        self.vehicle.write({"ff_operator_company_id": self.company.id})
        self.vehicle.with_user(self.compliance).ff_mark_reviewed()
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("no_policy", self._codes(result))
        self.assertFalse(result["can_confirm"])

    def test_expired_document_blocks(self):
        self.ready_chauffeur_setup()
        # Replace the valid insurance with an already-expired verified one (a
        # verified document cannot be edited to expire it in place -- that is the
        # frozen-evidence guard; here we model a genuinely expired document).
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]).unlink()
        self.make_credential("insurance", "vehicle_id", self.vehicle,
                             end=date.today() - timedelta(days=1))
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.BLOCKED)
        self.assertIn("doc_expired", self._codes(result))
        self.assertFalse(result["can_confirm"])

    def test_expiry_mid_interval_blocks(self):
        self.ready_chauffeur_setup()
        # Licence valid until *today*: the interval is tomorrow, so it is expired
        # before the interval starts -> blocked. Model it as a genuinely expired
        # verified document rather than editing a frozen one.
        self.env["fleetflow.credential"].search([
            ("driver_id", "=", self.driver.id), ("doc_kind", "=", "driver_licence")]).unlink()
        self.make_credential("driver_licence", "driver_id", self.driver, end=date.today())
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.BLOCKED)
        self.assertIn("doc_expired", self._codes(result))

    def test_missing_evidence_is_needs_review_not_ready(self):
        self.ready_chauffeur_setup()
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]).unlink()
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("doc_missing", self._codes(result))

    def test_unverified_evidence_is_needs_review(self):
        self.ready_chauffeur_setup()
        # Add a fresh registration in draft alongside the verified one? Instead,
        # leave registration unverified: delete verified, add draft.
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "vehicle_registration")]).unlink()
        self.make_credential("vehicle_registration", "vehicle_id", self.vehicle, verify=False)
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("doc_unverified", self._codes(result))

    def test_unreviewed_vehicle_is_needs_review(self):
        self.ready_chauffeur_setup()
        self.vehicle.with_user(self.compliance).ff_mark_unreviewed()
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("vehicle_unreviewed", self._codes(result))

    def test_wrong_employer_blocks(self):
        self.ready_chauffeur_setup()
        other_driver = self.env["fleetflow.driver"].create({
            "name": "Foreign driver", "company_id": self.other_company.id})
        result = self.evaluate(user=self.fleet_manager, driver=other_driver)
        self.assertEqual(result["status"], constants.BLOCKED)
        self.assertIn("driver_wrong_employer", self._codes(result))

    def test_uber_approval_does_not_satisfy_careem(self):
        self.ready_chauffeur_setup()  # has Uber/UberX approved only
        result = self.evaluate(user=self.dispatcher, channel_products=[("careem", "CareemBusiness")])
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("channel_missing", self._codes(result))

    def test_suspended_channel_blocks(self):
        self.ready_chauffeur_setup()
        enr = self.env["fleetflow.channel.enrolment"].search([
            ("driver_id", "=", self.driver.id), ("channel", "=", "uber")])
        enr.with_user(self.compliance).action_suspend()
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.BLOCKED)
        self.assertIn("channel_suspended", self._codes(result))

    def test_stale_channel_is_needs_review(self):
        self.ready_chauffeur_setup()
        enr = self.env["fleetflow.channel.enrolment"].search([
            ("driver_id", "=", self.driver.id), ("channel", "=", "uber")])
        # Age the platform verification (verified_as_of is reviewer-protected, so
        # set it through the internal transition rather than a direct write).
        enr._apply({"verified_as_of": datetime.now() - timedelta(days=400)})
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("channel_stale", self._codes(result))

    def test_renewal_supersede_makes_ready_again(self):
        self.ready_chauffeur_setup()
        # Model a genuinely expired verified insurance.
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]).unlink()
        ins = self.make_credential("insurance", "vehicle_id", self.vehicle,
                                   end=date.today() - timedelta(days=1))
        self.assertEqual(self.evaluate(user=self.dispatcher)["status"], constants.BLOCKED)
        renewal = ins.browse(ins.with_user(self.compliance).action_supersede({
            "name": "INS-renewal", "date_start": date.today() - timedelta(days=1),
            "date_end": date.today() + timedelta(days=365),
        }))
        # The renewal is not yet verified; the old (expired) evidence still
        # stands, so the request stays blocked -- coverage is never opened by a
        # mere draft, nor is the still-listed old document ignored.
        self.assertEqual(ins.state, "verified")
        self.assertEqual(self.evaluate(user=self.dispatcher)["status"], constants.BLOCKED)
        renewal.with_user(self.compliance).action_verify()
        # Once verified, the renewal takes over and the predecessor is superseded.
        self.assertEqual(ins.state, "superseded")
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.READY, self._codes(result))

    def test_end_of_use_exceeded_blocks(self):
        self.ready_chauffeur_setup()
        self.publish_profile(
            "chauffeur", require_operating_authorization=True, require_vehicle_registration=True,
            require_insurance=True, require_driver_licence=True, require_professional_permit=True,
            require_channel_approval=True, enforce_end_of_use=True,
        )
        self.vehicle.with_user(self.compliance).ff_review_end_of_use(
            authorized_end_of_use=date.today() - timedelta(days=1))
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.BLOCKED)
        self.assertIn("end_of_use_exceeded", self._codes(result))

    def test_result_carries_no_attachment_content(self):
        self.ready_chauffeur_setup()
        result = self.evaluate(user=self.dispatcher)
        blob = str(result)
        self.assertNotIn("raw", blob)
        self.assertNotIn("datas", blob)
        # Evidence references expose only metadata.
        for r in result["reasons"]:
            if "evidence_ref" in r:
                self.assertEqual(set(r["evidence_ref"]) <= {"model", "id", "kind", "state", "date_end"}, True)
