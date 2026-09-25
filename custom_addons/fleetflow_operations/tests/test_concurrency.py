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

    # ==================================================================
    # F07 race pairs: every dispatch-invalidating change joins the SAME
    # shared vehicle/driver lock, so a concurrent checkout and such a
    # change cannot both commit on stale snapshots. The review named these
    # races explicitly; each asserts both workers finish, exactly one wins,
    # the loser fails with the expected serialization failure, and the
    # committed state is internally consistent (no partial history).
    # ==================================================================
    def _seed_confirmed_chauffeur(self, reg, suffix, channel_required=True):
        """Commit a fully-ready CONFIRMED chauffeur allocation whose window is
        open now (so checkout is inside it), with a dispatcher, a compliance
        reviewer, verified vehicle/driver evidence and (optionally) approved Uber
        enrolments for both subjects. Returns the committed record ids."""
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            company = env.company
            dispatcher = env["res.users"].with_context(no_reset_password=True).create({
                "name": "conc %s disp" % suffix, "login": "ff.conc.%s.disp" % suffix,
                "email": "ff.conc.%s.disp@example.com" % suffix,
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_dispatcher").id])]})
            compliance = env["res.users"].with_context(no_reset_password=True).create({
                "name": "conc %s comp" % suffix, "login": "ff.conc.%s.comp" % suffix,
                "email": "ff.conc.%s.comp@example.com" % suffix,
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_compliance").id])]})
            brand = env["fleet.vehicle.model.brand"].create({"name": "conc %s brand" % suffix})
            model = env["fleet.vehicle.model"].create({"name": "conc %s model" % suffix, "brand_id": brand.id})
            vehicle = env["fleet.vehicle"].create({
                "model_id": model.id, "license_plate": "CONC-%s" % suffix, "company_id": company.id,
                "ff_operator_company_id": company.id, "ff_operational_state": "reviewed"})
            driver = env["fleetflow.driver"].create({
                "name": "conc %s driver" % suffix, "employee_ref": "CONC-%s-D" % suffix,
                "company_id": company.id})
            profile = env["fleetflow.operating.profile"].create({
                "name": "conc %s chauffeur" % suffix, "company_id": company.id,
                "operating_mode": "chauffeur",
                "require_operating_authorization": False, "require_vehicle_registration": True,
                "require_insurance": True, "require_driver_licence": True,
                "require_professional_permit": False,
                "require_channel_approval": channel_required, "enforce_end_of_use": False})
            profile.action_publish()
            for kind, field, subj in (("vehicle_registration", "vehicle_id", vehicle),
                                      ("insurance", "vehicle_id", vehicle),
                                      ("driver_licence", "driver_id", driver)):
                env["fleetflow.credential"].create({
                    "name": "%s-%s" % (kind, suffix), "doc_kind": kind, "company_id": company.id,
                    field: subj.id, "date_start": date.today() - timedelta(days=10),
                    "date_end": date.today() + timedelta(days=365)}).action_verify()
            veh_enr = drv_enr = env["fleetflow.channel.enrolment"]
            if channel_required:
                veh_enr = env["fleetflow.channel.enrolment"].create({
                    "company_id": company.id, "channel": "uber", "product": "UberX",
                    "city": "Dubai", "vehicle_id": vehicle.id})
                veh_enr.action_approve()
                drv_enr = env["fleetflow.channel.enrolment"].create({
                    "company_id": company.id, "channel": "uber", "product": "UberX",
                    "city": "Dubai", "driver_id": driver.id})
                drv_enr.action_approve()
            now = datetime.utcnow()
            alloc = env["fleetflow.allocation"].create({
                "company_id": company.id, "operating_mode": "chauffeur",
                "vehicle_id": vehicle.id, "driver_id": driver.id,
                "planned_start": now - timedelta(hours=1), "planned_end": now + timedelta(hours=8)})
            if channel_required:
                alloc.channel_enrolment_ids = [(6, 0, (veh_enr + drv_enr).ids)]
            alloc.action_confirm()
            ids = {"alloc": alloc.id, "vehicle": vehicle.id, "driver": driver.id,
                   "dispatcher": dispatcher.id, "compliance": compliance.id,
                   "profile": profile.id, "veh_enr": veh_enr.id, "drv_enr": drv_enr.id}
            cr.commit()
        return ids

    def _cleanup(self, reg, ids):
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["fleetflow.vehicle.hold"].search([("vehicle_id", "=", ids["vehicle"])]).unlink()
            env["fleetflow.allocation"].search([
                "|", ("vehicle_id", "=", ids["vehicle"]), ("driver_id", "=", ids["driver"])]).unlink()
            env["fleetflow.channel.enrolment"].search([
                "|", ("vehicle_id", "=", ids["vehicle"]), ("driver_id", "=", ids["driver"])]).unlink()
            env["fleetflow.credential"].search([
                "|", ("vehicle_id", "=", ids["vehicle"]), ("driver_id", "=", ids["driver"])]).unlink()
            env["fleet.vehicle"].browse(ids["vehicle"]).unlink()
            env["fleetflow.driver"].browse(ids["driver"]).unlink()
            env["res.users"].browse([ids["dispatcher"], ids["compliance"]]).unlink()
            env["fleetflow.operating.profile"].browse(ids["profile"]).unlink()
            cr.commit()

    def _race(self, reg, work_a, work_b):
        """Run two callables on two separate committed connections, released
        together by a barrier. Each callable is `(env) -> None` and raises to
        signal failure. Returns {"a": <"ok"|error-name>, "b": ...}."""
        results = {}
        barrier = threading.Barrier(2)

        def run(tag, uid, work):
            with reg.cursor() as cr:
                env = api.Environment(cr, uid, {})
                try:
                    barrier.wait(timeout=15)
                    work(env)
                    cr.commit(); results[tag] = "ok"
                except Exception as exc:  # pragma: no cover - exercised at runtime
                    cr.rollback(); results[tag] = _classify(exc)

        threads = [threading.Thread(target=run, args=("a", work_a[0], work_a[1])),
                   threading.Thread(target=run, args=("b", work_b[0], work_b[1]))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return results

    def test_duplicate_checkout_only_one_wins(self):
        """Two dispatchers check out the same custody at once: exactly one takes
        custody, the duplicate fails with a serialization failure (never a second
        physical handover)."""
        reg = registry(self.env.cr.dbname)
        ids = self._seed_confirmed_chauffeur(reg, "dup", channel_required=False)
        try:
            def checkout(env):
                env["fleetflow.allocation"].browse(ids["alloc"]).action_checkout(odometer=120)
            results = self._race(reg, (ids["dispatcher"], checkout), (ids["dispatcher"], checkout))
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "exactly one duplicate checkout may win: %s" % results)
            self.assertEqual([v for v in results.values() if v != "ok"], ["serialization"],
                             "the losing duplicate checkout must fail with serialization: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                alloc = env["fleetflow.allocation"].browse(ids["alloc"])
                self.assertEqual(alloc.state, "checked_out")
                self.assertTrue(alloc.custody_out_at)
        finally:
            self._cleanup(reg, ids)

    def test_checkout_and_channel_suspension_serialise(self):
        """A checkout and a concurrent channel suspension on the driver serialise
        on the shared lock: they never both commit on stale snapshots."""
        reg = registry(self.env.cr.dbname)
        ids = self._seed_confirmed_chauffeur(reg, "susp", channel_required=True)
        try:
            def checkout(env):
                env["fleetflow.allocation"].browse(ids["alloc"]).action_checkout(odometer=120)

            def suspend(env):
                env["fleetflow.channel.enrolment"].browse(ids["drv_enr"]).action_suspend()
            results = self._race(reg, (ids["dispatcher"], checkout), (ids["compliance"], suspend))
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "checkout and suspension must not both commit: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                alloc = env["fleetflow.allocation"].browse(ids["alloc"])
                enr = env["fleetflow.channel.enrolment"].browse(ids["drv_enr"])
                if results["a"] == "ok":  # checkout won
                    self.assertEqual(alloc.state, "checked_out")
                    self.assertEqual(enr.state, "approved")
                    self.assertEqual(results["b"], "serialization")
                else:  # suspension won
                    self.assertEqual(alloc.state, "confirmed")
                    self.assertEqual(enr.state, "suspended")
                    self.assertEqual(results["a"], "serialization")
        finally:
            self._cleanup(reg, ids)

    def test_checkout_and_evidence_revocation_serialise(self):
        """A checkout and a concurrent evidence revocation on the vehicle serialise
        on the shared lock (a rejected credential bumps the same vehicle lock a
        checkout takes)."""
        reg = registry(self.env.cr.dbname)
        ids = self._seed_confirmed_chauffeur(reg, "rev", channel_required=False)
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cred_id = env["fleetflow.credential"].search([
                ("vehicle_id", "=", ids["vehicle"]), ("doc_kind", "=", "insurance")], limit=1).id
        try:
            def checkout(env):
                env["fleetflow.allocation"].browse(ids["alloc"]).action_checkout(odometer=120)

            def revoke(env):
                env["fleetflow.credential"].browse(cred_id).action_reject()
            results = self._race(reg, (ids["dispatcher"], checkout), (ids["compliance"], revoke))
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "checkout and revocation must not both commit: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                alloc = env["fleetflow.allocation"].browse(ids["alloc"])
                cred = env["fleetflow.credential"].browse(cred_id)
                if results["a"] == "ok":  # checkout won
                    self.assertEqual(alloc.state, "checked_out")
                    self.assertEqual(cred.state, "verified")
                    self.assertEqual(results["b"], "serialization")
                else:  # revocation won
                    self.assertEqual(alloc.state, "confirmed")
                    self.assertEqual(cred.state, "rejected")
                    self.assertEqual(results["a"], "serialization")
        finally:
            self._cleanup(reg, ids)

    def test_checkout_and_cancel_serialise(self):
        """A checkout and a concurrent cancel of the same allocation cannot both
        win: they contend on the allocation row itself, so the state is never both
        checked out and cancelled."""
        reg = registry(self.env.cr.dbname)
        ids = self._seed_confirmed_chauffeur(reg, "cxl", channel_required=False)
        try:
            def checkout(env):
                env["fleetflow.allocation"].browse(ids["alloc"]).action_checkout(odometer=120)

            def cancel(env):
                env["fleetflow.allocation"].browse(ids["alloc"]).action_cancel()
            results = self._race(reg, (ids["dispatcher"], checkout), (ids["dispatcher"], cancel))
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "checkout and cancel must not both commit: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                alloc = env["fleetflow.allocation"].browse(ids["alloc"])
                self.assertIn(alloc.state, ("checked_out", "cancelled"))
                loser = results["b"] if results["a"] == "ok" else results["a"]
                self.assertEqual(loser, "serialization",
                                 "the loser must fail with serialization: %s" % results)
        finally:
            self._cleanup(reg, ids)

    def test_reschedule_and_reservation_serialise(self):
        """Rescheduling one confirmed allocation onto an interval while another is
        confirmed onto an overlapping interval for the same vehicle cannot both
        win: they serialise on the vehicle lock, so no double-booking survives."""
        reg = registry(self.env.cr.dbname)
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            company = env.company
            dispatcher = env["res.users"].with_context(no_reset_password=True).create({
                "name": "conc resched disp", "login": "ff.conc.resched.disp",
                "email": "ff.conc.resched.disp@example.com",
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_dispatcher").id])]})
            brand = env["fleet.vehicle.model.brand"].create({"name": "conc resched brand"})
            model = env["fleet.vehicle.model"].create({"name": "conc resched model", "brand_id": brand.id})
            vehicle = env["fleet.vehicle"].create({
                "model_id": model.id, "license_plate": "CONC-RESCHED", "company_id": company.id,
                "ff_operator_company_id": company.id, "ff_operational_state": "reviewed"})
            profile = env["fleetflow.operating.profile"].create({
                "name": "conc resched rental", "company_id": company.id, "operating_mode": "rental",
                "require_operating_authorization": False, "require_vehicle_registration": True,
                "require_insurance": True, "require_driver_licence": False,
                "require_professional_permit": False, "require_channel_approval": False,
                "enforce_end_of_use": False})
            profile.action_publish()
            for kind in ("vehicle_registration", "insurance"):
                env["fleetflow.credential"].create({
                    "name": "%s-resched" % kind, "doc_kind": kind, "company_id": company.id,
                    "vehicle_id": vehicle.id, "date_start": date.today() - timedelta(days=10),
                    "date_end": date.today() + timedelta(days=365)}).action_verify()
            day = date.today() + timedelta(days=2)
            a_start = datetime.combine(day, time(8, 0))
            a = env["fleetflow.allocation"].create({
                "company_id": company.id, "operating_mode": "rental", "vehicle_id": vehicle.id,
                "planned_start": a_start, "planned_end": datetime.combine(day, time(12, 0))})
            a.action_confirm()
            b = env["fleetflow.allocation"].create({
                "company_id": company.id, "operating_mode": "rental", "vehicle_id": vehicle.id,
                "planned_start": datetime.combine(day, time(13, 0)),
                "planned_end": datetime.combine(day, time(17, 0))})  # draft, non-overlapping
            new_a_start = datetime.combine(day, time(14, 0))  # overlaps b once applied
            new_a_end = datetime.combine(day, time(16, 0))
            ids = {"a": a.id, "b": b.id, "vehicle": vehicle.id,
                   "dispatcher": dispatcher.id, "profile": profile.id}
            cr.commit()
        try:
            def reschedule(env):
                env["fleetflow.allocation"].browse(ids["a"]).action_reschedule(
                    {"planned_start": new_a_start, "planned_end": new_a_end})

            def reserve(env):
                env["fleetflow.allocation"].browse(ids["b"]).action_confirm()
            results = self._race(reg, (ids["dispatcher"], reschedule), (ids["dispatcher"], reserve))
            self.assertEqual(len(results), 2, "both threads must finish: %s" % results)
            self.assertEqual(list(results.values()).count("ok"), 1,
                             "reschedule and reservation must not both commit: %s" % results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                a = env["fleetflow.allocation"].browse(ids["a"])
                b = env["fleetflow.allocation"].browse(ids["b"])
                if results["a"] == "ok":  # reschedule won
                    self.assertEqual(a.planned_start, new_a_start)
                    self.assertEqual(b.state, "draft")
                    self.assertEqual(results["b"], "serialization")
                else:  # reservation won
                    self.assertEqual(b.state, "confirmed")
                    self.assertEqual(a.planned_start, a_start)
                    self.assertEqual(results["a"], "serialization")
        finally:
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["fleetflow.allocation"].search([("vehicle_id", "=", ids["vehicle"])]).unlink()
                env["fleetflow.credential"].search([("vehicle_id", "=", ids["vehicle"])]).unlink()
                env["fleet.vehicle"].browse(ids["vehicle"]).unlink()
                env["res.users"].browse(ids["dispatcher"]).unlink()
                env["fleetflow.operating.profile"].browse(ids["profile"]).unlink()
                cr.commit()
