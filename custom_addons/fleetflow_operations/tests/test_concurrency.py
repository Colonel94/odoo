# -*- coding: utf-8 -*-
"""Genuine multi-connection concurrency: two separate database connections race
to reserve the same vehicle for an overlapping interval. Exactly one wins; the
other fails cleanly with no partial state. This uses real committed cursors, not
sequential calls in one transaction (an in-memory mock would not prove locking).
"""
import threading
from datetime import datetime, time, timedelta, date

from psycopg2 import errors as pg_errors

from odoo import api, registry, SUPERUSER_ID
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def _classify(exc):
    """A losing transaction on the shared resource row must fail with a Postgres
    serialization failure (SQLSTATE 40001), not some unrelated error."""
    if isinstance(exc, pg_errors.SerializationFailure):
        return "serialization"
    return type(exc).__name__


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
                    results[idx] = _classify(exc)

        threads = [threading.Thread(target=worker, args=(created[0], 0)),
                   threading.Thread(target=worker, args=(created[1], 1))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # --- Exactly one reservation succeeded; no partial state ----------
        try:
            # Both threads must have finished (not hung on the barrier).
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "Exactly one confirm must win, got: %s" % results)
            # The loser fails with the expected serialization failure, nothing else.
            loser = [v for v in results.values() if v != "ok"]
            self.assertEqual(loser, ["serialization"],
                             "Loser must fail with a serialization failure, got: %s" % results)
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

    def test_checkout_and_hold_creation_serialise(self):
        """A checkout and a concurrent blocking-hold creation on the same vehicle
        must not both succeed on stale snapshots: they serialise on the shared
        vehicle lock, so exactly one wins and the state stays consistent (if the
        hold committed first, the checkout is refused; it is never checked out
        while an active blocking hold exists)."""
        reg = registry(self.env.cr.dbname)
        ids = {}
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            company = env.company
            dispatcher = env["res.users"].with_context(no_reset_password=True).create({
                "name": "conc2 dispatcher", "login": "ff.conc2.dispatcher",
                "email": "ff.conc2.dispatcher@example.com",
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_dispatcher").id])]})
            brand = env["fleet.vehicle.model.brand"].create({"name": "conc2 brand"})
            model = env["fleet.vehicle.model"].create({"name": "conc2 model", "brand_id": brand.id})
            vehicle = env["fleet.vehicle"].create({
                "model_id": model.id, "license_plate": "CONC2-1", "company_id": company.id,
                "ff_operator_company_id": company.id, "ff_operational_state": "reviewed"})
            driver = env["fleetflow.driver"].create({
                "name": "conc2 driver", "employee_ref": "CONC2-D", "company_id": company.id})
            profile = env["fleetflow.operating.profile"].create({
                "name": "conc2 chauffeur", "company_id": company.id, "operating_mode": "chauffeur",
                "require_operating_authorization": False, "require_vehicle_registration": True,
                "require_insurance": True, "require_driver_licence": True,
                "require_professional_permit": False, "require_channel_approval": False,
                "enforce_end_of_use": False})
            profile.action_publish()
            for kind, field, subj in (("vehicle_registration", "vehicle_id", vehicle),
                                      ("insurance", "vehicle_id", vehicle),
                                      ("driver_licence", "driver_id", driver)):
                env["fleetflow.credential"].create({
                    "name": "%s-conc2" % kind, "doc_kind": kind, "company_id": company.id,
                    field: subj.id, "date_start": date.today() - timedelta(days=10),
                    "date_end": date.today() + timedelta(days=365)}).action_verify()
            now = datetime.utcnow()
            alloc = env["fleetflow.allocation"].create({
                "company_id": company.id, "operating_mode": "chauffeur",
                "vehicle_id": vehicle.id, "driver_id": driver.id,
                "planned_start": now - timedelta(hours=1), "planned_end": now + timedelta(hours=8)})
            alloc.action_confirm()
            ids = {"alloc": alloc.id, "vehicle": vehicle.id, "driver": driver.id,
                   "dispatcher": dispatcher.id, "profile": profile.id}
            cr.commit()

        results = {}
        barrier = threading.Barrier(2)

        def do_checkout():
            with reg.cursor() as cr:
                env = api.Environment(cr, ids["dispatcher"], {})
                try:
                    barrier.wait(timeout=15)
                    env["fleetflow.allocation"].browse(ids["alloc"]).action_checkout(odometer=100)
                    cr.commit(); results["checkout"] = "ok"
                except Exception as exc:  # pragma: no cover - exercised at runtime
                    cr.rollback(); results["checkout"] = _classify(exc)

        def do_hold():
            with reg.cursor() as cr:
                env = api.Environment(cr, ids["dispatcher"], {})
                try:
                    barrier.wait(timeout=15)
                    env["fleetflow.vehicle.hold"].create({
                        "vehicle_id": ids["vehicle"], "hold_type": "safety",
                        "reason": "conc2 brake fault", "dispatch_blocking": True})
                    cr.commit(); results["hold"] = "ok"
                except Exception as exc:  # pragma: no cover - exercised at runtime
                    cr.rollback(); results["hold"] = _classify(exc)

        threads = [threading.Thread(target=do_checkout), threading.Thread(target=do_hold)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        try:
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "exactly one of checkout/hold must win: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                alloc = env["fleetflow.allocation"].browse(ids["alloc"])
                active = env["fleetflow.vehicle.hold"].search_count([
                    ("vehicle_id", "=", ids["vehicle"]), ("state", "=", "active"),
                    ("dispatch_blocking", "=", True)])
                if results.get("checkout") == "ok":
                    self.assertEqual(alloc.state, "checked_out")
                    self.assertEqual(active, 0)
                    self.assertEqual(results["hold"], "serialization")
                else:
                    self.assertEqual(alloc.state, "confirmed")
                    self.assertEqual(active, 1)
                    self.assertEqual(results["checkout"], "serialization")
        finally:
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["fleetflow.vehicle.hold"].search([("vehicle_id", "=", ids["vehicle"])]).unlink()
                env["fleetflow.allocation"].browse(ids["alloc"]).unlink()
                env["fleetflow.credential"].search([
                    "|", ("vehicle_id", "=", ids["vehicle"]), ("driver_id", "=", ids["driver"])]).unlink()
                env["fleet.vehicle"].browse(ids["vehicle"]).unlink()
                env["fleetflow.driver"].browse(ids["driver"]).unlink()
                env["res.users"].browse(ids["dispatcher"]).unlink()
                env["fleetflow.operating.profile"].browse(ids["profile"]).unlink()
                cr.commit()
