# -*- coding: utf-8 -*-
"""Regression against false-green readiness (F05).

'No restriction recorded' is not a reviewed determination that no restriction
applies; a blank expiry is not 'unlimited'; an imprecise date is not a day-
accurate bound; and document expiry must be interpreted in the operator's
timezone, never the requesting user's. All of these must resolve to Needs review
rather than Ready.
"""
from datetime import date, timedelta

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants


@tagged("post_install", "-at_install")
class TestFalseGreen(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.vehicle.write({"ff_official_category": "ordinary"})

    def _codes(self, result):
        return {r["code"] for r in result["reasons"]}

    def _enforce_end_of_use(self):
        # Re-publish the chauffeur profile with end-of-use enforcement on.
        self.publish_profile(
            "chauffeur", require_operating_authorization=True,
            require_vehicle_registration=True, require_insurance=True,
            require_driver_licence=True, require_professional_permit=True,
            require_channel_approval=True, enforce_end_of_use=True)

    # -- End-of-use age applicability ------------------------------------
    def test_end_of_use_unknown_is_needs_review(self):
        self._enforce_end_of_use()
        # Known category, but NO authorised end-of-use date and no reviewed
        # exemption: applicability is unresolved -> Needs review, not Ready.
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW, self._codes(result))
        self.assertIn("end_of_use_unknown", self._codes(result))

    def test_end_of_use_reviewed_exemption_is_ready(self):
        self._enforce_end_of_use()
        self.vehicle.with_user(self.compliance).ff_review_end_of_use(exempt=True)
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.READY, self._codes(result))
        self.assertIn("end_of_use_exempt", self._codes(result))

    def test_authorized_end_of_use_not_directly_writable(self):
        with self.assertRaises(AccessError):
            self.vehicle.with_user(self.fleet_manager).write(
                {"ff_authorized_end_of_use": date.today() + timedelta(days=10)})
        with self.assertRaises(AccessError):
            self.vehicle.with_user(self.fleet_manager).write({"ff_end_of_use_exempt": True})

    def test_end_of_use_date_set_by_review_action(self):
        self._enforce_end_of_use()
        self.vehicle.with_user(self.compliance).ff_review_end_of_use(
            authorized_end_of_use=date.today() + timedelta(days=365))
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.READY, self._codes(result))

    # -- Missing / imprecise validity ------------------------------------
    def _replace_insurance(self, **vals):
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")]).unlink()
        base = {"name": "INS-x", "doc_kind": "insurance", "company_id": self.company.id,
                "vehicle_id": self.vehicle.id, "date_start": date.today() - timedelta(days=30)}
        base.update(vals)
        cred = self.env["fleetflow.credential"].create(base)
        cred.with_user(self.compliance).action_verify()
        return cred

    def test_missing_expiry_is_needs_review(self):
        self._replace_insurance()  # verified, no date_end, not open-ended
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW, self._codes(result))
        self.assertIn("doc_validity_unknown", self._codes(result))

    def test_reviewed_open_ended_document_is_ready(self):
        self._replace_insurance(open_ended=True)  # reviewed non-expiring
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.READY, self._codes(result))

    def test_imprecise_expiry_is_needs_review(self):
        self._replace_insurance(date_end=date.today() + timedelta(days=365),
                                date_precision="year")
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW, self._codes(result))
        self.assertIn("doc_validity_unknown", self._codes(result))

    # -- Authorization bounds / jurisdiction -----------------------------
    def test_unbounded_authorization_is_needs_review(self):
        self.env["fleetflow.operating.authorization"].search([]).unlink()
        auth = self.env["fleetflow.operating.authorization"].create({
            "name": "AUTH-open", "company_id": self.company.id,
            "operating_mode": "chauffeur", "date_start": date.today() - timedelta(days=10)})
        auth.with_user(self.compliance).action_verify()  # verified, no end
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW, self._codes(result))
        self.assertIn("permit_unbounded", self._codes(result))

    def test_wrong_jurisdiction_authorization_not_matched(self):
        self.env["fleetflow.operating.authorization"].search([]).unlink()
        auth = self.env["fleetflow.operating.authorization"].create({
            "name": "AUTH-AUH", "company_id": self.company.id, "operating_mode": "chauffeur",
            "jurisdiction": "Abu Dhabi", "date_start": date.today() - timedelta(days=10),
            "date_end": date.today() + timedelta(days=300)})
        auth.with_user(self.compliance).action_verify()
        result = self.evaluate(user=self.dispatcher)  # request city Dubai
        self.assertEqual(result["status"], constants.NEEDS_REVIEW, self._codes(result))
        self.assertIn("permit_missing", self._codes(result))

    # -- Deterministic operator timezone ---------------------------------
    def test_operator_timezone_independent_of_requesting_user(self):
        self.dispatcher.tz = "America/New_York"
        self.fleet_manager.tz = "Asia/Tokyo"
        tz1 = self.evaluate(user=self.dispatcher)["interval"]["tz"]
        tz2 = self.evaluate(user=self.fleet_manager)["interval"]["tz"]
        self.assertEqual(tz1, tz2)
        self.assertNotIn(tz1, ("America/New_York", "Asia/Tokyo"))
