# -*- coding: utf-8 -*-
"""Regression for product-specific channel eligibility (F03).

A channel approval must independently establish EACH required subject (both the
vehicle and the driver for a chauffeur shift), match the operating city, honour
recheck dates, and never let one approved record mask another subject's
suspension. Each requested product is evaluated independently and deterministically
so one product's data never stands in for another's.
"""
from datetime import date, timedelta

from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants


@tagged("post_install", "-at_install")
class TestEligibility(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()  # now approves BOTH vehicle and driver on Uber

    def _codes(self, result):
        return {r["code"] for r in result["reasons"]}

    def _uber(self, subject_field, subject):
        return self.env["fleetflow.channel.enrolment"].search([
            (subject_field, "=", subject.id), ("channel", "=", "uber")])

    def test_driver_only_channel_approval_is_not_ready(self):
        # The headline false positive: driver approved, vehicle not -> not ready.
        self._uber("vehicle_id", self.vehicle).unlink()
        result = self.evaluate(user=self.dispatcher)
        self.assertNotEqual(result["status"], constants.READY)
        self.assertIn("channel_missing", self._codes(result))

    def test_vehicle_only_channel_approval_is_not_ready(self):
        self._uber("driver_id", self.driver).unlink()
        result = self.evaluate(user=self.dispatcher)
        self.assertNotEqual(result["status"], constants.READY)
        self.assertIn("channel_missing", self._codes(result))

    def test_both_subjects_approved_is_ready(self):
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.READY, self._codes(result))

    def test_wrong_city_enrolment_does_not_satisfy(self):
        # A reviewed enrolment's city is frozen (it is part of what was approved),
        # so build the approvals for the WRONG city instead of re-pointing the
        # Dubai ones: a Dubai request is then not covered.
        self._uber("vehicle_id", self.vehicle).unlink()
        self._uber("driver_id", self.driver).unlink()
        self.make_channel("uber", "UberX", "vehicle_id", self.vehicle, city="Abu Dhabi")
        self.make_channel("uber", "UberX", "driver_id", self.driver, city="Abu Dhabi")
        result = self.evaluate(user=self.dispatcher)  # request city defaults to Dubai
        self.assertNotEqual(result["status"], constants.READY)
        self.assertIn("channel_missing", self._codes(result))

    def test_suspended_subject_not_masked_by_approved_other(self):
        self._uber("driver_id", self.driver).with_user(self.compliance).action_suspend()
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.BLOCKED)
        self.assertIn("channel_suspended", self._codes(result))

    def test_recheck_date_in_past_is_stale(self):
        self._uber("driver_id", self.driver).write({"recheck_date": date.today() - timedelta(days=1)})
        result = self.evaluate(user=self.dispatcher)
        self.assertEqual(result["status"], constants.NEEDS_REVIEW)
        self.assertIn("channel_stale", self._codes(result))

    def test_multi_product_each_evaluated_independently(self):
        self.make_channel("careem", "CareemBusiness", "driver_id", self.driver)
        self.make_channel("careem", "CareemBusiness", "vehicle_id", self.vehicle)
        both = [("uber", "UberX"), ("careem", "CareemBusiness")]
        self.assertEqual(
            self.evaluate(user=self.dispatcher, channel_products=both)["status"],
            constants.READY)
        # Drop Careem's vehicle approval: the Careem product fails on its own and
        # is NOT rescued by the fully-approved Uber product.
        self.env["fleetflow.channel.enrolment"].search([
            ("vehicle_id", "=", self.vehicle.id), ("channel", "=", "careem")]).unlink()
        result = self.evaluate(user=self.dispatcher, channel_products=both)
        self.assertNotEqual(result["status"], constants.READY)
        self.assertIn("channel_missing", self._codes(result))

    def test_product_order_does_not_change_verdict(self):
        self.make_channel("careem", "CareemBusiness", "driver_id", self.driver)
        self.make_channel("careem", "CareemBusiness", "vehicle_id", self.vehicle)
        r1 = self.evaluate(user=self.dispatcher,
                           channel_products=[("uber", "UberX"), ("careem", "CareemBusiness")])
        r2 = self.evaluate(user=self.dispatcher,
                           channel_products=[("careem", "CareemBusiness"), ("uber", "UberX")])
        self.assertEqual(r1["status"], r2["status"])
