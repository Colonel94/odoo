# -*- coding: utf-8 -*-
"""Genuine multi-connection concurrency: two separate database connections race
to reserve the same vehicle for an overlapping interval. Exactly one wins; the
other fails cleanly with no partial state. This uses real committed cursors, not
sequential calls in one transaction (an in-memory mock would not prove locking).
"""
import threading
from datetime import datetime, time, timedelta, date

from odoo import api, registry, SUPERUSER_ID
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestConcurrency(TransactionCase):

    def test_two_connections_one_reservation_wins(self):
        dbname = self.env.cr.dbname
        reg = registry(dbname)
        created = []

        # --- Build committed fixtures visible to both connections ---------
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            company = env.company
            dispatcher = env["res.users"].with_context(no_reset_password=True).create({
                "name": "conc dispatcher", "login": "ff.conc.dispatcher",
                "email": "ff.conc.dispatcher@example.com",
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_dispatcher").id])],
            })
            brand = env["fleet.vehicle.model.brand"].create({"name": "conc brand"})
            model = env["fleet.vehicle.model"].create({"name": "conc model", "brand_id": brand.id})
            vehicle = env["fleet.vehicle"].create({
                "model_id": model.id, "license_plate": "CONC-1", "company_id": company.id,
                "ff_operator_company_id": company.id, "ff_operational_state": "reviewed"})
            profile = env["fleetflow.operating.profile"].create({
                "name": "conc rental", "company_id": company.id, "operating_mode": "rental",
                "require_operating_authorization": False, "require_vehicle_registration": True,
                "require_insurance": True, "require_driver_licence": False,
                "require_professional_permit": False, "require_channel_approval": False,
                "enforce_end_of_use": False})
            profile.action_publish()
            for kind in ("vehicle_registration", "insurance"):
                cred = env["fleetflow.credential"].create({
                    "name": "%s-conc" % kind, "doc_kind": kind, "company_id": company.id,
                    "vehicle_id": vehicle.id, "date_start": date.today() - timedelta(days=10),
                    "date_end": date.today() + timedelta(days=365)})
                cred.action_verify()
            day = date.today() + timedelta(days=1)
            s = datetime.combine(day, time(8, 0))
            e = datetime.combine(day, time(18, 0))

            def alloc():
                return env["fleetflow.allocation"].create({
                    "company_id": company.id, "operating_mode": "rental",
                    "vehicle_id": vehicle.id, "planned_start": s, "planned_end": e})
            alloc_a = alloc()
            alloc_b = alloc()
            created = [alloc_a.id, alloc_b.id, vehicle.id, dispatcher.id, profile.id]
            dispatcher_id = dispatcher.id
            cr.commit()

        # --- Two connections race to confirm ------------------------------
        results = {}
        barrier = threading.Barrier(2)

        def worker(alloc_id, idx):
            with reg.cursor() as cr:
                env = api.Environment(cr, dispatcher_id, {})
                alloc = env["fleetflow.allocation"].browse(alloc_id)
                try:
                    barrier.wait(timeout=15)
                    alloc.action_confirm()
                    cr.commit()
                    results[idx] = "ok"
                except Exception as exc:  # pragma: no cover - exercised at runtime
                    cr.rollback()
                    results[idx] = type(exc).__name__

        threads = [threading.Thread(target=worker, args=(created[0], 0)),
                   threading.Thread(target=worker, args=(created[1], 1))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # --- Exactly one reservation succeeded; no partial state ----------
        try:
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "Exactly one confirm must win, got: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                confirmed = env["fleetflow.allocation"].search_count([
                    ("id", "in", created[:2]), ("state", "=", "confirmed")])
                self.assertEqual(confirmed, 1)
        finally:
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["fleetflow.allocation"].browse(created[:2]).unlink()
                env["fleet.vehicle"].browse(created[2]).unlink()
                env["res.users"].browse(created[3]).unlink()
                env["fleetflow.operating.profile"].browse(created[4]).unlink()
                cr.commit()
