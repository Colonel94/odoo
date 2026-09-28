# -*- coding: utf-8 -*-
"""Verification vs. attachment-mutation race (task 3).

Reproduction with two independent, committed database connections under the real
Odoo/PostgreSQL isolation configuration (REPEATABLE READ; asserted below). The
hypothesis: a writer that observed the still-unverified credential on an older
snapshot commits a competing attachment mutation *after* another transaction
approves it, leaving verified evidence pointing at bytes that never passed
approval-time validation.

Forced ordering (events, not sleeps):
  1. the editor opens a transaction and observes the draft/unverified credential
     (pinning its REPEATABLE READ snapshot),
  2. a reviewer verifies the credential and commits,
  3. the editor then attempts its mutation and commits.

Required outcome after both commit (asserted from a fresh transaction, comparing
source identity and byte hashes -- not just the verified flag): the approved
credential still references the exact validated source, its bytes are unchanged,
and the source is neither deleted, rebound nor published. A losing editor aborts
with a serialization failure and, on retry in a fresh transaction, is cleanly
refused by the durable freeze. The reverse ordering (a valid edit that commits
before verification) is also covered: verification then validates the committed
bytes.

The editor genuinely holds pre-approval write permission (a compliance reviewer
editing a not-yet-approved draft's file); this is not an unrelated ACL denial.
These tests fail on the pre-fix code (verification took only a transient FOR
UPDATE lock and left no committed change on the source row, so the editor's write
did not conflict) and pass with the source-lock bump.
"""
import hashlib
import threading
from datetime import date, timedelta

from psycopg2 import errors as pg_errors

from odoo import api, registry, SUPERUSER_ID
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from .pdf_fixtures import ONE_PAGE_PDF, MULTI_PAGE_PDF

APPROVED = ONE_PAGE_PDF
REPLACEMENT = MULTI_PAGE_PDF  # a different but genuinely-valid document


def _classify(exc):
    if isinstance(exc, pg_errors.SerializationFailure):
        return "serialization"
    return type(exc).__name__


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@tagged("post_install", "-at_install")
class TestVerificationRace(TransactionCase):

    def test_isolation_is_repeatable_read(self):
        """Record the isolation configuration the reproduction relies on."""
        reg = registry(self.env.cr.dbname)
        with reg.cursor() as cr:
            cr.execute("SHOW transaction_isolation")
            level = cr.fetchone()[0]
        self.assertEqual(level, "repeatable read",
                         "the race analysis assumes REPEATABLE READ; got %s" % level)

    # -- seeding ---------------------------------------------------------
    def _seed(self, reg, suffix):
        """Commit a DRAFT credential with a bound, valid attachment, plus a
        compliance reviewer who may edit the draft's file before approval."""
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            company = env.company
            compliance = env["res.users"].with_context(no_reset_password=True).create({
                "name": "race %s comp" % suffix, "login": "ff.race.%s.comp" % suffix,
                "email": "ff.race.%s.comp@example.com" % suffix,
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_compliance").id])]})
            driver = env["fleetflow.driver"].create({
                "name": "race %s driver" % suffix, "employee_ref": "RACE-%s" % suffix,
                "company_id": company.id})
            att = env["ir.attachment"].create({"name": "race-%s.pdf" % suffix, "raw": APPROVED})
            cred = env["fleetflow.credential"].create({
                "name": "race-%s" % suffix, "doc_kind": "driver_licence",
                "company_id": company.id, "driver_id": driver.id, "attachment_id": att.id})
            ids = {"cred": cred.id, "att": att.id, "driver": driver.id,
                   "compliance": compliance.id, "partner": compliance.partner_id.id}
            cr.commit()
        return ids

    def _cleanup(self, reg, ids):
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            # Deleting the credential (as superuser) also removes its bound
            # attachment; only unlink the attachment if it still exists.
            cred = env["fleetflow.credential"].browse(ids["cred"])
            if cred.exists():
                cred.sudo().unlink()
            att = env["ir.attachment"].browse(ids["att"])
            if att.exists():
                att.sudo().unlink()
            env["fleetflow.driver"].browse(ids["driver"]).unlink()
            env["res.users"].browse(ids["compliance"]).unlink()
            cr.commit()

    # -- the forced race -------------------------------------------------
    def _race(self, reg, ids, editor_work):
        """Editor observes the unverified credential, reviewer verifies+commits,
        then editor attempts `editor_work(env, ids)` and commits."""
        results = {}
        observed = threading.Event()
        verified = threading.Event()

        def editor():
            with reg.cursor() as cr:
                env = api.Environment(cr, ids["compliance"], {})
                # Pin the snapshot on the still-unverified credential.
                cr.execute("SELECT ever_verified FROM fleetflow_credential WHERE id = %s",
                           (ids["cred"],))
                seen = cr.fetchone()[0]
                results["observed_ever_verified"] = bool(seen)
                observed.set()
                if not verified.wait(timeout=20):
                    results["editor"] = "reviewer-timeout"
                    return
                try:
                    editor_work(env, ids)
                    cr.commit()
                    results["editor"] = "ok"
                except Exception as exc:  # pragma: no cover - exercised at runtime
                    cr.rollback()
                    results["editor"] = _classify(exc)

        def reviewer():
            with reg.cursor() as cr:
                env = api.Environment(cr, ids["compliance"], {})
                if not observed.wait(timeout=20):
                    results["reviewer"] = "editor-timeout"
                    verified.set()
                    return
                try:
                    env["fleetflow.credential"].browse(ids["cred"]).action_verify()
                    cr.commit()
                    results["reviewer"] = "ok"
                except Exception as exc:  # pragma: no cover - exercised at runtime
                    cr.rollback()
                    results["reviewer"] = _classify(exc)
                verified.set()

        threads = [threading.Thread(target=editor), threading.Thread(target=reviewer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=40)
        return results

    def _assert_source_intact(self, reg, ids):
        """From a FRESH transaction: verified, same source id, same bytes, private."""
        with reg.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cred = env["fleetflow.credential"].browse(ids["cred"])
            self.assertEqual(cred.state, "verified")
            self.assertTrue(cred.ever_verified)
            self.assertEqual(cred.attachment_id.id, ids["att"],
                             "the approved credential must still point at the validated source")
            att = env["ir.attachment"].browse(ids["att"])
            self.assertTrue(att.exists(), "the approved source must not be deleted")
            self.assertEqual(att.res_model, "fleetflow.credential")
            self.assertEqual(att.res_id, ids["cred"], "the source must not be rebound")
            self.assertFalse(att.public, "the source must not be newly published")
            self.assertFalse(att.access_token, "the source must not gain a token")
            self.assertEqual(_sha(att.raw), _sha(APPROVED),
                             "the approved bytes must not be overwritten")

    def _run_losing_editor(self, suffix, editor_work):
        reg = registry(self.env.cr.dbname)
        ids = self._seed(reg, suffix)
        try:
            results = self._race(reg, ids, editor_work)
            self.assertFalse(results.get("observed_ever_verified"),
                             "editor must observe the credential still unverified")
            self.assertEqual(results.get("reviewer"), "ok",
                             "reviewer verifies first: %s" % results)
            self.assertEqual(results.get("editor"), "serialization",
                             "the losing post-approval mutation must abort with a "
                             "serialization failure, not commit: %s" % results)
            self._assert_source_intact(reg, ids)
        finally:
            self._cleanup(reg, ids)

    def test_replace_bytes_after_approval_is_blocked(self):
        def work(env, ids):
            att = env["ir.attachment"].browse(ids["att"])
            att.write({"raw": REPLACEMENT})
            att.flush_recordset()
        self._run_losing_editor("bytes", work)

    def test_delete_source_after_approval_is_blocked(self):
        def work(env, ids):
            env["ir.attachment"].browse(ids["att"]).unlink()
        self._run_losing_editor("del", work)

    def test_rebind_source_after_approval_is_blocked(self):
        # Unbind the source from the credential. This is a mutation the compliance
        # editor is genuinely permitted to make on a not-yet-approved draft's file
        # (no unrelated ACL stands in the way), so a denial here proves the race
        # protection, not an accidental permission failure.
        def work(env, ids):
            att = env["ir.attachment"].browse(ids["att"])
            att.write({"res_model": False, "res_id": False})
            att.flush_recordset()
        self._run_losing_editor("rebind", work)

    def test_publish_source_after_approval_is_blocked(self):
        def work(env, ids):
            att = env["ir.attachment"].browse(ids["att"])
            att.write({"public": True, "access_token": "deadbeefdeadbeef1234"})
            att.flush_recordset()
        self._run_losing_editor("pub", work)

    def test_repoint_credential_pointer_after_approval_is_blocked(self):
        def work(env, ids):
            other = env["ir.attachment"].create({"name": "swap.pdf", "raw": REPLACEMENT})
            cred = env["fleetflow.credential"].browse(ids["cred"])
            cred.write({"attachment_id": other.id})
            cred.flush_recordset()
        self._run_losing_editor("repoint", work)

    # -- retry behaviour after the abort --------------------------------
    def test_losing_editor_is_cleanly_refused_on_retry(self):
        reg = registry(self.env.cr.dbname)
        ids = self._seed(reg, "retry")
        try:
            def work(env, ids):
                att = env["ir.attachment"].browse(ids["att"])
                att.write({"raw": REPLACEMENT})
                att.flush_recordset()
            results = self._race(reg, ids, work)
            self.assertEqual(results.get("editor"), "serialization", results)
            # Retry in a FRESH transaction: now the snapshot sees the approved
            # state, so the durable freeze refuses with a business AccessError
            # (not another serialization), and the bytes stay approved.
            from odoo.exceptions import AccessError
            with reg.cursor() as cr:
                env = api.Environment(cr, ids["compliance"], {})
                att = env["ir.attachment"].browse(ids["att"])
                with self.assertRaises(AccessError):
                    att.write({"raw": REPLACEMENT})
                    att.flush_recordset()
                cr.rollback()
            self._assert_source_intact(reg, ids)
        finally:
            self._cleanup(reg, ids)

    # -- reverse ordering: a valid edit that commits BEFORE verification -
    def test_valid_edit_before_verification_is_validated_then_approved(self):
        """The editor commits a valid replacement first; verification then runs on
        the committed bytes and approves THEM. Final state matches a safe serial
        order (verified evidence points at the validated replacement)."""
        reg = registry(self.env.cr.dbname)
        ids = self._seed(reg, "rev")
        results = {}
        edited = threading.Event()
        try:
            def editor():
                with reg.cursor() as cr:
                    env = api.Environment(cr, ids["compliance"], {})
                    try:
                        att = env["ir.attachment"].browse(ids["att"])
                        att.write({"raw": REPLACEMENT})   # allowed: still a draft
                        att.flush_recordset()
                        cr.commit()
                        results["editor"] = "ok"
                    except Exception as exc:  # pragma: no cover
                        cr.rollback()
                        results["editor"] = _classify(exc)
                    edited.set()

            def reviewer():
                with reg.cursor() as cr:
                    env = api.Environment(cr, ids["compliance"], {})
                    edited.wait(timeout=20)
                    try:
                        env["fleetflow.credential"].browse(ids["cred"]).action_verify()
                        cr.commit()
                        results["reviewer"] = "ok"
                    except Exception as exc:  # pragma: no cover
                        cr.rollback()
                        results["reviewer"] = _classify(exc)

            threads = [threading.Thread(target=editor), threading.Thread(target=reviewer)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=40)
            self.assertEqual(results.get("editor"), "ok", results)
            self.assertEqual(results.get("reviewer"), "ok", results)
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                cred = env["fleetflow.credential"].browse(ids["cred"])
                att = env["ir.attachment"].browse(ids["att"])
                self.assertEqual(cred.state, "verified")
                # Verification validated and approved the committed replacement bytes.
                self.assertEqual(_sha(att.raw), _sha(REPLACEMENT))
        finally:
            self._cleanup(reg, ids)
