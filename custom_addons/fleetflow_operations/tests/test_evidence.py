# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OperationsCase


@tagged("post_install", "-at_install")
class TestEvidence(OperationsCase):

    def test_pending_upload_cannot_self_approve(self):
        cred = self.env["fleetflow.credential"].create({
            "name": "REG-1", "doc_kind": "vehicle_registration",
            "company_id": self.company.id, "vehicle_id": self.vehicle.id,
            "state": "pending",
        })
        # Forged verified state via ordinary write is refused.
        with self.assertRaises(AccessError):
            cred.write({"state": "verified"})
        with self.assertRaises(AccessError):
            cred.write({"verified_by": self.compliance.id})
        self.assertEqual(cred.state, "pending")

    def test_create_cannot_start_verified_or_forge_history(self):
        # Explicit vals and default_* context keys are both stripped.
        cred = self.env["fleetflow.credential"].with_context(
            default_state="verified", default_verified_by=self.compliance.id,
        ).create({
            "name": "INS-1", "doc_kind": "insurance",
            "company_id": self.company.id, "vehicle_id": self.vehicle.id,
            "state": "verified", "verified_by": self.compliance.id,
        })
        self.assertEqual(cred.state, "draft")
        self.assertFalse(cred.verified_by)

    def test_verify_requires_compliance(self):
        cred = self.env["fleetflow.credential"].create({
            "name": "REG-2", "doc_kind": "vehicle_registration",
            "company_id": self.company.id, "vehicle_id": self.vehicle.id,
        })
        with self.assertRaises(AccessError):
            cred.with_user(self.dispatcher).action_verify()
        cred.with_user(self.compliance).action_verify()
        self.assertEqual(cred.state, "verified")
        self.assertEqual(cred.verified_by, self.compliance)

    def test_exactly_one_subject(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["fleetflow.credential"].create({
                "name": "X", "doc_kind": "insurance", "company_id": self.company.id,
                "vehicle_id": self.vehicle.id, "driver_id": self.driver.id,
            })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["fleetflow.credential"].create({
                "name": "Y", "doc_kind": "insurance", "company_id": self.company.id,
            })

    def test_subject_company_consistency(self):
        other_driver = self.env["fleetflow.driver"].create({
            "name": "Other co driver", "company_id": self.other_company.id,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["fleetflow.credential"].create({
                "name": "Z", "doc_kind": "driver_licence", "company_id": self.company.id,
                "driver_id": other_driver.id,
            })

    def test_verified_immutable_until_superseded(self):
        cred = self.make_credential("vehicle_registration", "vehicle_id", self.vehicle,
                                    end=date.today() + timedelta(days=10))
        with self.assertRaises(UserError):
            cred.write({"date_end": date.today() + timedelta(days=400)})
        # Supersede with a renewal; history is retained.
        renewal = cred.with_user(self.compliance).action_supersede({
            "name": "REG-renewal", "date_start": date.today(),
            "date_end": date.today() + timedelta(days=400),
        })
        self.assertEqual(cred.state, "superseded")
        self.assertEqual(cred.superseded_by_id, renewal)
        self.assertEqual(renewal.supersedes_id, cred)
        self.assertEqual(renewal.state, "draft")

    def test_covers_whole_interval_local_boundary(self):
        import pytz
        tz = pytz.timezone("Asia/Dubai")
        cred = self.make_credential(
            "insurance", "vehicle_id", self.vehicle,
            start=date.today() - timedelta(days=1), end=date.today() + timedelta(days=1),
        )
        from datetime import datetime, time
        # A shift entirely within validity is covered.
        start = tz.localize(datetime.combine(date.today(), time(8, 0)))
        end = tz.localize(datetime.combine(date.today(), time(18, 0)))
        self.assertTrue(cred._covers_interval(start, end, tz))
        # An interval crossing the day AFTER date_end is not covered (mid-expiry).
        late_end = tz.localize(datetime.combine(date.today() + timedelta(days=2), time(9, 0)))
        self.assertFalse(cred._covers_interval(start, late_end, tz))

    def test_dispatcher_cannot_download_evidence_attachment(self):
        cred = self.make_credential("driver_licence", "driver_id", self.driver)
        attachment = self.env["ir.attachment"].create({
            "name": "licence.pdf", "res_model": "fleetflow.credential", "res_id": cred.id,
            "raw": b"%PDF-1.4 fake",
        })
        # Compliance can read the file; a dispatcher cannot.
        attachment.with_user(self.compliance).check("read")
        with self.assertRaises(AccessError):
            attachment.with_user(self.dispatcher).check("read")
