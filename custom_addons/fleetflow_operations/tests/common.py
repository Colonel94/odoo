# -*- coding: utf-8 -*-
from datetime import date, timedelta

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
