# -*- coding: utf-8 -*-
"""Reproduction + regression for evidence lifecycle correctness (E01, E02, E05).

E01 - a future-effective LINKED renewal (via action_supersede) must not remove
      the predecessor's still-valid current coverage; the renewal covers only its
      own effective interval; real gaps and revoked predecessors are handled
      deterministically and never resurrect coverage.
E02 - rejection/revocation records its own attribution (never overwriting the
      original verification) and never unlocks the once-approved source file.
E05 - a file changed after linking is re-validated at verification and cannot
      slip past the approval-time policy.

Superuser builds fixtures; the reviewed actions run as an ordinary compliance
reviewer. The E01 coverage tests fail against the pre-fix code (which superseded
the predecessor immediately and dropped today's coverage).
"""
from datetime import date, datetime, time, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import OperationsCase
from ..models import constants

VALID_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@tagged("post_install", "-at_install")
class TestEvidenceLifecycle(OperationsCase):

    def setUp(self):
        super().setUp()
        self.ready_chauffeur_setup()
        self.enr = self.uber_enrolment()

    def _iv(self, days_ahead):
        day = date.today() + timedelta(days=days_ahead)
        return (datetime.combine(day, time(8, 0)), datetime.combine(day, time(18, 0)))

    def _reg(self):
        return self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id),
            ("doc_kind", "=", "vehicle_registration")], limit=1)

    # -- E01: future-effective linked renewal ----------------------------
    def test_future_effective_renewal_preserves_current_and_supplies_future(self):
        # Rebuild the registration deterministically: drop the fixture's long-dated
        # one and make a bounded predecessor the renewal genuinely takes over from.
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id),
            ("doc_kind", "=", "vehicle_registration")]).sudo().unlink()
        reg = self.make_credential("vehicle_registration", "vehicle_id", self.vehicle,
                                   start=date.today() - timedelta(days=30),
                                   end=date.today() + timedelta(days=30))
        nm_start = date.today() + timedelta(days=31)
        renewal = reg.browse(reg.with_user(self.compliance).action_supersede({
            "name": "reg-renewal", "date_start": nm_start,
            "date_end": nm_start + timedelta(days=365)}))
        renewal.with_user(self.compliance).action_verify()
        # Relationship + attribution preserved; predecessor effectively replaced.
        self.assertEqual(reg.state, "superseded")
        self.assertEqual(reg.superseded_by_id, renewal)
        self.assertEqual(renewal.supersedes_id, reg)
        self.assertTrue(reg.replaced_on)
        # TODAY (tomorrow's shift) is still covered by the predecessor's interval.
        s, e = self._iv(1)
        self.assertEqual(self.evaluate(user=self.dispatcher, start=s, end=e)["status"],
                         constants.READY)
        # A shift inside the renewal window is covered by the renewal.
        s2, e2 = self._iv(40)
        self.assertEqual(self.evaluate(user=self.dispatcher, start=s2, end=e2)["status"],
                         constants.READY)

    def test_real_gap_between_predecessor_and_renewal_is_not_ready(self):
        self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id),
            ("doc_kind", "=", "vehicle_registration")]).sudo().unlink()
        reg = self.make_credential("vehicle_registration", "vehicle_id", self.vehicle,
                                   start=date.today() - timedelta(days=30),
                                   end=date.today() + timedelta(days=10))
        gap_start = date.today() + timedelta(days=40)
        renewal = reg.browse(reg.with_user(self.compliance).action_supersede({
            "name": "reg-gap", "date_start": gap_start,
            "date_end": gap_start + timedelta(days=365)}))
        renewal.with_user(self.compliance).action_verify()
        # A shift in the gap (day+20) is covered by neither -> not Ready.
        s, e = self._iv(20)
        self.assertNotEqual(self.evaluate(user=self.dispatcher, start=s, end=e)["status"],
                            constants.READY)

    def test_revoked_predecessor_coverage_not_resurrected(self):
        reg = self._reg()
        reg.with_user(self.compliance).action_reject(reason="fraudulent scan")
        self.assertEqual(reg.state, "rejected")
        s, e = self._iv(1)
        self.assertNotEqual(self.evaluate(user=self.dispatcher, start=s, end=e)["status"],
                            constants.READY)

    # -- E02: revocation attribution + durable source protection ---------
    def test_reject_records_revocation_without_overwriting_verification(self):
        reg = self._reg()
        self.assertEqual(reg.verified_by, self.compliance)
        original_on = reg.verified_on
        reg.with_user(self.compliance).action_reject(reason="mismatch")
        self.assertEqual(reg.state, "rejected")
        self.assertEqual(reg.verified_by, self.compliance)   # unchanged
        self.assertEqual(reg.verified_on, original_on)       # unchanged
        self.assertEqual(reg.revoked_by, self.compliance)
        self.assertTrue(reg.revoked_on)
        self.assertEqual(reg.revoke_reason, "mismatch")
        self.assertTrue(reg.ever_verified)                   # durable

    def test_rejected_source_file_stays_immutable(self):
        att = self.env["ir.attachment"].create({"name": "d.pdf", "raw": VALID_PDF})
        cred = self.env["fleetflow.credential"].create({
            "name": "with-file", "doc_kind": "driver_licence",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": att.id})
        cred.with_user(self.compliance).action_verify()
        cred.with_user(self.compliance).action_reject(reason="revoked")
        self.assertEqual(cred.state, "rejected")
        self.assertTrue(cred.ever_verified)
        # The once-approved source is still frozen after revocation.
        for vals in ({"raw": b"%PDF-1.4 tampered\n%%EOF"}, {"public": True},
                     {"res_model": "res.partner"}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                att.with_user(self.compliance).write(vals)
        with self.assertRaises(AccessError), self.cr.savepoint():
            att.with_user(self.compliance).unlink()

    # -- E05: file changed after linking is caught at verification -------
    def test_file_changed_after_link_is_revalidated_at_verify(self):
        att = self.env["ir.attachment"].create({"name": "ok.pdf", "raw": VALID_PDF})
        cred = self.env["fleetflow.credential"].create({
            "name": "changed", "doc_kind": "driver_licence",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": att.id})
        # The draft's file is swapped for a malformed one after linking (allowed
        # while the credential is not yet approved)...
        att.sudo().write({"raw": b"%PDF-1.4 no eof marker here"})
        # ...verification re-validates the CURRENT bytes and refuses.
        with self.assertRaises(UserError):
            cred.with_user(self.compliance).action_verify()
        self.assertNotEqual(cred.state, "verified")
