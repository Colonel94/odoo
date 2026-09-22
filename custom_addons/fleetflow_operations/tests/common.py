# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class OperationsCase(TransactionCase):
    """Shared fixtures for FleetFlow Operations tests (synthetic data only)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({"name": "FF Ops other company"})

        def make_user(login, *groups):
            return cls.env["res.users"].with_context(no_reset_password=True).create({
                "name": login, "login": login,
                "company_id": cls.company.id, "company_ids": [(6, 0, cls.company.ids)],
                "groups_id": [(6, 0, [cls.env.ref(g).id for g in groups])],
            })

        cls.compliance = make_user("ff.ops.compliance", "fleetflow_operations.group_ops_compliance")
        cls.dispatcher = make_user("ff.ops.dispatcher", "fleetflow_operations.group_ops_dispatcher")
        cls.fleet_manager = make_user("ff.ops.fleet", "fleetflow_operations.group_ops_fleet_manager")

        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "FF Ops brand"})
        model = cls.env["fleet.vehicle.model"].create({"name": "FF Ops model", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": model.id, "license_plate": "OPS-1", "company_id": cls.company.id,
            "ff_operator_company_id": cls.company.id,
        })
        cls.driver = cls.env["fleetflow.driver"].create({
            "name": "Test Driver", "employee_ref": "DRV-1", "company_id": cls.company.id,
        })

    # -- helpers ---------------------------------------------------------
    def make_credential(self, doc_kind, subject_field, subject, start=None, end=None, verify=True):
        vals = {
            "name": "%s-%s" % (doc_kind, subject.id),
            "doc_kind": doc_kind,
            "company_id": self.company.id,
            subject_field: subject.id,
            "date_start": start or (date.today() - timedelta(days=30)),
            "date_end": end or (date.today() + timedelta(days=365)),
        }
        cred = self.env["fleetflow.credential"].create(vals)
        if verify:
            cred.with_user(self.compliance).action_verify()
        return cred

    def publish_profile(self, operating_mode="chauffeur", channel=None, product=None, **flags):
        vals = {
            "name": "Profile %s" % operating_mode, "company_id": self.company.id,
            "operating_mode": operating_mode, "channel": channel, "product": product,
            "source_ref": "synthetic-test",
        }
        vals.update(flags)
        profile = self.env["fleetflow.operating.profile"].create(vals)
        profile.with_user(self.compliance).action_publish()
        return profile

    def make_authorization(self, operating_mode="chauffeur", start=None, end=None, verify=True):
        auth = self.env["fleetflow.operating.authorization"].create({
            "name": "AUTH-%s" % operating_mode, "company_id": self.company.id,
            "operating_mode": operating_mode,
            "date_start": start or (date.today() - timedelta(days=30)),
            "date_end": end or (date.today() + timedelta(days=365)),
        })
        if verify:
            auth.with_user(self.compliance).action_verify()
        return auth

    def make_channel(self, channel, product, subject_field, subject, state="approved", fresh=True):
        enr = self.env["fleetflow.channel.enrolment"].create({
            "company_id": self.company.id, "channel": channel, "product": product,
            subject_field: subject.id, "state": state,
        })
        if state == "approved" and fresh:
            enr.verified_as_of = fields.Datetime.now()
        return enr

    def interval(self, start_hour=8, end_hour=18, days_ahead=1):
        """A synthetic shift interval, returned as naive-UTC datetimes."""
        from datetime import datetime, time
        day = date.today() + timedelta(days=days_ahead)
        start = datetime.combine(day, time(start_hour, 0))
        end = datetime.combine(day, time(end_hour, 0))
        return start, end

    def ready_chauffeur_setup(self):
        """A fully-eligible chauffeur setup; individual tests then break one thing."""
        self.vehicle.write({
            "ff_operator_company_id": self.company.id, "ff_operational_state": "reviewed",
        })
        self.publish_profile(
            "chauffeur", require_operating_authorization=True, require_vehicle_registration=True,
            require_insurance=True, require_driver_licence=True, require_professional_permit=True,
            require_channel_approval=True, enforce_end_of_use=False, require_category_evidence=False,
        )
        self.make_authorization("chauffeur")
        self.make_credential("vehicle_registration", "vehicle_id", self.vehicle)
        self.make_credential("insurance", "vehicle_id", self.vehicle)
        self.make_credential("driver_licence", "driver_id", self.driver)
        self.make_credential("professional_permit", "driver_id", self.driver)
        self.make_channel("uber", "UberX", "driver_id", self.driver)

    def evaluate(self, channel_products=None, mode="chauffeur", vehicle=None, driver=None,
                 start=None, end=None, user=None):
        if start is None or end is None:
            start, end = self.interval()
        svc = self.env["fleetflow.readiness"]
        if user:
            svc = svc.with_user(user)
        return svc.evaluate_readiness(
            self.company, vehicle or self.vehicle,
            driver if driver is not None else self.driver,
            mode, channel_products if channel_products is not None else [("uber", "UberX")],
            start, end,
        )
