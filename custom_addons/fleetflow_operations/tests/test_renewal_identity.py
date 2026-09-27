# -*- coding: utf-8 -*-
"""Linked-renewal identity protection (C1).

action_supersede fixes a renewal's company, subject and document kind from the
predecessor at create time, but the create-time restriction alone did not protect
the whole workflow: credential.write allowed those identity fields to change while
the renewal was still draft/pending, and action_verify did not revalidate
continuity. A redirected renewal could therefore be approved as a continuation of
a claim it no longer matched.

A linked renewal must keep the predecessor's operating company, subject type,
exact subject and document kind for its whole lifecycle; dates, issuer/reference
and the replacement upload remain editable. A genuinely different claim is an
independent credential, never a redirected renewal. Enforced during writes and
again, under a row lock, at verification.
"""
from datetime import date, datetime, time, timedelta

import pytz

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..models import constants
from .common import OperationsCase

TZ = pytz.timezone("Asia/Dubai")


@tagged("post_install", "-at_install")
class TestRenewalIdentity(OperationsCase):

    def setUp(self):
        super().setUp()
        Vehicle = self.env["fleet.vehicle"]
        model = self.vehicle.model_id
        # Car B in the same company, and a vehicle owned by another company.
        self.vehicle_b = Vehicle.create({
            "model_id": model.id, "license_plate": "OPS-B", "company_id": self.company.id,
            "ff_operator_company_id": self.company.id})
        self.vehicle_other = Vehicle.create({
            "model_id": model.id, "license_plate": "OPS-O", "company_id": self.other_company.id,
            "ff_operator_company_id": self.other_company.id})
        # A reviewer allowed in BOTH internal companies.
        self.two_co = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "ff.ops.twoco", "login": "ff.ops.twoco", "email": "twoco@example.com",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id, self.other_company.id])],
            "groups_id": [(6, 0, [self.env.ref("fleetflow_operations.group_ops_compliance").id])]})
        # A verified registration for Car A is the predecessor.
        self.pred = self.make_credential(
            "vehicle_registration", "vehicle_id", self.vehicle,
            start=date.today() - timedelta(days=30), end=date.today() + timedelta(days=200))

    def _renewal(self, verify=False):
        nm = date.today() + timedelta(days=31)
        rid = self.pred.with_user(self.compliance).action_supersede({
            "name": "reg-renewal", "date_start": nm, "date_end": nm + timedelta(days=365)})
        renewal = self.pred.browse(rid)
        if verify:
            renewal.with_user(self.compliance).action_verify()
        return renewal

    # -- redirect attempts are refused, records unchanged ----------------
    def test_cannot_redirect_renewal_to_another_subject(self):
        r = self._renewal()
        with self.assertRaises(UserError):
            r.with_user(self.compliance).write({"vehicle_id": self.vehicle_b.id})
        r.invalidate_recordset()
        self.assertEqual(r.vehicle_id, self.vehicle)

    def test_cannot_change_renewal_document_kind(self):
        r = self._renewal()
        with self.assertRaises(UserError):
            r.with_user(self.compliance).write({"doc_kind": "insurance"})
        r.invalidate_recordset()
        self.assertEqual(r.doc_kind, "vehicle_registration")

    def test_cannot_change_renewal_subject_type(self):
        # Swapping the vehicle subject for a driver subject is a redirect too.
        r = self._renewal()
        with self.assertRaises(UserError):
            r.with_user(self.compliance).write(
                {"vehicle_id": False, "driver_id": self.driver.id})
        r.invalidate_recordset()
        self.assertEqual(r.vehicle_id, self.vehicle)
        self.assertFalse(r.driver_id)

    def test_two_company_reviewer_cannot_transfer_renewal(self):
        r = self._renewal()
        with self.assertRaises(UserError):
            r.with_user(self.two_co).write(
                {"company_id": self.other_company.id, "vehicle_id": self.vehicle_other.id})
        r.invalidate_recordset()
        self.assertEqual(r.company_id, self.company)
        self.assertEqual(r.vehicle_id, self.vehicle)

    def test_rejected_redirect_leaves_both_records_and_links_unchanged(self):
        r = self._renewal()
        before = (r.company_id, r.vehicle_id, r.doc_kind, r.supersedes_id,
                  self.pred.state, self.pred.superseded_by_id)
        with self.assertRaises(UserError):
            r.with_user(self.compliance).write({"vehicle_id": self.vehicle_b.id})
        r.invalidate_recordset()
        self.pred.invalidate_recordset()
        self.assertEqual(
            (r.company_id, r.vehicle_id, r.doc_kind, r.supersedes_id,
             self.pred.state, self.pred.superseded_by_id), before)

    # -- legitimate edits still work -------------------------------------
    def test_legitimate_pending_edits_and_verification_work(self):
        r = self._renewal()
        # Dates, issuer and reference remain editable on the draft renewal.
        r.with_user(self.compliance).write({
            "date_end": date.today() + timedelta(days=800),
            "issuer": "RTA", "reference": "REG-2027-0001"})
        r.with_user(self.compliance).action_verify()
        self.pred.invalidate_recordset()
        self.assertEqual(r.state, "verified")
        self.assertEqual(self.pred.state, "superseded")
        self.assertEqual(self.pred.superseded_by_id, r)
        self.assertEqual(r.supersedes_id, self.pred)

    def test_same_identity_renewal_covers_end_to_end(self):
        # Positive: an ordinary reviewer prepares, verifies and uses a legitimate
        # same-identity renewal; coverage is correct on both sides of the cutover.
        r = self._renewal(verify=True)
        cutover = date.today() + timedelta(days=31)

        def iv(day, h1=8, h2=18):
            return (TZ.localize(datetime.combine(day, time(h1))),
                    TZ.localize(datetime.combine(day, time(h2))))
        Cred = self.env["fleetflow.credential"]
        before = iv(cutover - timedelta(days=1))
        after = iv(cutover + timedelta(days=10))
        self.assertEqual(Cred._resolve_coverage(self.pred + r, *before, TZ), self.pred)
        self.assertEqual(Cred._resolve_coverage(self.pred + r, *after, TZ), r)

    # -- verification re-check (defence in depth) ------------------------
    def test_verification_refuses_a_diverged_renewal(self):
        # Simulate a renewal whose identity diverged through a path that bypassed
        # the write guard (ORM-level _apply). Verification must still refuse it.
        r = self._renewal()
        r._apply({"vehicle_id": self.vehicle_b.id})  # bypasses the public guard
        r.invalidate_recordset()
        with self.assertRaises(UserError):
            r.with_user(self.compliance).action_verify()
        r.invalidate_recordset()
        self.pred.invalidate_recordset()
        self.assertNotEqual(r.state, "verified")
        self.assertEqual(self.pred.state, "verified")   # predecessor not superseded

    # -- single unambiguous replacement, even after revocation -----------
    def test_second_approval_conflicts_even_if_first_successor_revoked(self):
        r1 = self._renewal()
        r2_id = self.pred.with_user(self.compliance).action_supersede({
            "name": "reg-renewal-2", "date_start": date.today() + timedelta(days=31),
            "date_end": date.today() + timedelta(days=400)})
        r2 = self.pred.browse(r2_id)
        r1.with_user(self.compliance).action_verify()
        self.pred.invalidate_recordset()
        self.assertEqual(self.pred.superseded_by_id, r1)
        # Revoke the first successor: the link remains, so a second approval must
        # still conflict (not judged solely on the predecessor's current state).
        r1.with_user(self.compliance).action_reject(reason="revoked")
        with self.assertRaises(UserError):
            r2.with_user(self.compliance).action_verify()
        self.pred.invalidate_recordset()
        self.assertEqual(self.pred.superseded_by_id, r1)

    # -- R1: a winning successor is recorded even when the predecessor was
    #        already REVOKED before either approval -----------------------
    def _iv_day(self, day, h1=8, h2=18):
        return (TZ.localize(datetime.combine(day, time(h1))),
                TZ.localize(datetime.combine(day, time(h2))))

    def test_revoked_predecessor_competing_approvals_only_one_wins(self):
        """R1 (public actions): the predecessor is revoked BEFORE either renewal is
        approved. The first approval still wins its slot; a competing sibling is
        refused; the predecessor stays rejected with its attribution and grants no
        coverage; revoking either record does not reopen the sibling; an
        independent credential is unaffected."""
        nm = date.today() + timedelta(days=31)
        r1_id = self.pred.with_user(self.compliance).action_supersede({
            "name": "r1", "date_start": nm, "date_end": nm + timedelta(days=365)})
        r2_id = self.pred.with_user(self.compliance).action_supersede({
            "name": "r2", "date_start": nm, "date_end": nm + timedelta(days=365)})
        r1 = self.pred.browse(r1_id)
        r2 = self.pred.browse(r2_id)
        # An independent, properly-verified credential on Car B (case C control).
        indep = self.make_credential(
            "vehicle_registration", "vehicle_id", self.vehicle_b,
            start=date.today() - timedelta(days=5), end=date.today() + timedelta(days=300))

        # Revoke the predecessor BEFORE approving either renewal.
        self.pred.with_user(self.compliance).action_reject(reason="predecessor revoked")
        v_by, v_on = self.pred.verified_by, self.pred.verified_on
        self.assertEqual(self.pred.state, "rejected")
        self.assertTrue(self.pred.revoked_by)

        # First approval wins the slot even though the predecessor is already dead.
        r1.with_user(self.compliance).action_verify()
        self.pred.invalidate_recordset()
        self.assertEqual(r1.state, "verified")
        self.assertEqual(self.pred.superseded_by_id, r1)   # winner recorded
        self.assertEqual(self.pred.state, "rejected")      # NOT resurrected
        self.assertEqual(self.pred.verified_by, v_by)      # attribution preserved
        self.assertEqual(self.pred.verified_on, v_on)
        self.assertTrue(self.pred.revoked_by)              # revocation attribution kept

        # The competing sibling approval is refused, and leaves NO partial change.
        with self.assertRaises(UserError), self.cr.savepoint():
            r2.with_user(self.compliance).action_verify()
        r2.invalidate_recordset()
        self.pred.invalidate_recordset()
        self.assertEqual(r2.state, "draft")   # never-approved sibling left untouched
        self.assertFalse(r2.verified_by)
        self.assertFalse(r2.verified_on)
        self.assertEqual(self.pred.superseded_by_id, r1)   # still the first winner

        # Coverage: exactly the first renewal survives as an accepted successor.
        Cred = self.env["fleetflow.credential"]
        succ = Cred.search([("supersedes_id", "=", self.pred.id), ("state", "=", "verified")])
        self.assertEqual(succ, r1)
        inside = self._iv_day(nm + timedelta(days=10))
        self.assertEqual(Cred._resolve_coverage(self.pred + r1 + r2, *inside, TZ), r1)
        # The revoked predecessor itself grants nothing before the renewal starts.
        self.assertFalse(Cred._resolve_coverage(
            self.pred + r1 + r2, *self._iv_day(date.today()), TZ))
        # The independent credential is untouched and still covers its own subject.
        self.assertEqual(Cred._resolve_coverage(indep, *self._iv_day(date.today()), TZ), indep)

        # Revoking the accepted successor must not erase the winner or reopen r2.
        r1.with_user(self.compliance).action_reject(reason="successor revoked")
        with self.assertRaises(UserError), self.cr.savepoint():
            r2.with_user(self.compliance).action_verify()
        self.pred.invalidate_recordset()
        self.assertEqual(self.pred.superseded_by_id, r1)
        r2.invalidate_recordset()
        self.assertEqual(r2.state, "draft")

    def test_revoked_predecessor_single_legitimate_renewal_still_approves(self):
        """A lone legitimate renewal of a revoked predecessor is still approved for
        its own validity period (the winner slot is recorded, not blocked)."""
        nm = date.today() + timedelta(days=31)
        r_id = self.pred.with_user(self.compliance).action_supersede({
            "name": "solo", "date_start": nm, "date_end": nm + timedelta(days=365)})
        r = self.pred.browse(r_id)
        self.pred.with_user(self.compliance).action_reject(reason="revoked")
        r.with_user(self.compliance).action_verify()
        self.pred.invalidate_recordset()
        self.assertEqual(r.state, "verified")
        self.assertEqual(self.pred.state, "rejected")
        self.assertEqual(self.pred.superseded_by_id, r)
        Cred = self.env["fleetflow.credential"]
        self.assertEqual(
            Cred._resolve_coverage(self.pred + r, *self._iv_day(nm + timedelta(days=5)), TZ), r)

    # -- inconsistent legacy chain grants no coverage --------------------
    def test_inconsistent_legacy_chain_flagged_not_covered(self):
        r = self._renewal(verify=True)
        # Force the (verified) successor's subject to diverge, mimicking a legacy
        # inconsistent chain that predates this guard.
        r._apply({"vehicle_id": self.vehicle_b.id})
        r.invalidate_recordset()
        self.pred.invalidate_recordset()
        self.assertIsNone(self.pred._cutover(TZ))

        def iv(day):
            return (TZ.localize(datetime.combine(day, time(8))),
                    TZ.localize(datetime.combine(day, time(18))))
        Cred = self.env["fleetflow.credential"]
        # The predecessor (superseded, ambiguous cutover) grants no coverage.
        self.assertFalse(Cred._resolve_coverage(self.pred, *iv(date.today()), TZ))

    # -- R2: the inconsistent SUCCESSOR itself grants no trusted coverage,
    #        detected on the successor (not only via the predecessor) ------
    def test_inconsistent_successor_grants_no_coverage_from_either_side(self):
        r = self._renewal(verify=True)
        # A legacy inconsistent chain: the verified successor was redirected to a
        # DIFFERENT vehicle (only reachable via ORM-level _apply, mimicking old
        # data). Its own validity window is [nm, nm+365].
        nm = date.today() + timedelta(days=31)
        r._apply({"vehicle_id": self.vehicle_b.id})
        r.invalidate_recordset()
        self.pred.invalidate_recordset()
        Cred = self.env["fleetflow.credential"]

        # Pick an interval INSIDE the successor's own validity window (testing only a
        # date before it starts would hide the defect).
        inside = self._iv_day(nm + timedelta(days=20))

        # 1) Directly through the successor's own validity/effective-interval helpers.
        self.assertFalse(r._effective_interval(TZ)[2], "inconsistent successor must be unreliable")
        self.assertEqual(r._validity(*inside, TZ), "unknown")

        # 2) The successor ALONE grants no coverage (its own subject, own window).
        self.assertFalse(Cred._resolve_coverage(r, *inside, TZ))

        # 3) Alongside its predecessor, in BOTH record orders.
        self.assertFalse(Cred._resolve_coverage(self.pred + r, *inside, TZ))
        self.assertFalse(Cred._resolve_coverage(r + self.pred, *inside, TZ))

        # 4) Through the ACTUAL readiness document check for the successor's subject
        #    (Car B). Assert the affected reason's status/code specifically, so an
        #    unrelated blocker cannot make the test pass by accident.
        reason = self.env["fleetflow.readiness"]._check_document(
            "vehicle_id", self.vehicle_b, "vehicle_registration", *inside, TZ)
        self.assertEqual(reason["check"], "vehicle_registration")
        self.assertEqual(reason["status"], constants.NEEDS_REVIEW)
        self.assertEqual(reason["code"], "doc_validity_unknown")

    def test_valid_same_identity_and_independent_controls_still_cover(self):
        """Controls for R2: a valid same-identity renewal of a revoked predecessor
        (case B) and an independent verified credential (case C) both still cover."""
        Cred = self.env["fleetflow.credential"]
        # Case B: same-identity renewal; revoke the predecessor, renewal still covers
        # its own window.
        r = self._renewal(verify=True)
        nm = date.today() + timedelta(days=31)
        self.pred.with_user(self.compliance).action_reject(reason="revoked after renewal")
        self.assertEqual(
            Cred._resolve_coverage(self.pred + r, *self._iv_day(nm + timedelta(days=10)), TZ), r)
        # Case C: an independent, properly-verified credential on Car B.
        indep = self.make_credential(
            "vehicle_registration", "vehicle_id", self.vehicle_b,
            start=date.today() - timedelta(days=5), end=date.today() + timedelta(days=300))
        self.assertFalse(indep.supersedes_id)
        self.assertEqual(Cred._resolve_coverage(indep, *self._iv_day(date.today()), TZ), indep)
        reason = self.env["fleetflow.readiness"]._check_document(
            "vehicle_id", self.vehicle_b, "vehicle_registration",
            *self._iv_day(date.today()), TZ)
        self.assertEqual(reason["status"], constants.READY)

    # -- copy path -------------------------------------------------------
    def test_copy_is_independent_not_a_linked_renewal(self):
        r = self._renewal()
        clone = r.copy()
        self.assertFalse(clone.supersedes_id)
        # Being independent, its subject is freely editable.
        clone.with_user(self.compliance).write({"vehicle_id": self.vehicle_b.id})
        self.assertEqual(clone.vehicle_id, self.vehicle_b)

    def test_supersedes_link_cannot_be_forged_by_write(self):
        # The link itself stays protected (unchanged behaviour).
        r = self._renewal()
        other = self.make_credential("insurance", "vehicle_id", self.vehicle)
        with self.assertRaises(AccessError):
            r.with_user(self.compliance).write({"supersedes_id": other.id})
