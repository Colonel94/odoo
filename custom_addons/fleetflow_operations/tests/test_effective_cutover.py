# -*- coding: utf-8 -*-
"""Effective-dated credential replacement (task 1).

An approved replacement establishes an explicit, attributable cutover (derived
from the successor's own effective start). Before the cutover the predecessor may
cover within its own validity; at/after the cutover it must NOT fall back for the
part of the interval assigned to its replacement, even though its printed expiry
is later. A continuous reviewed renewal chain covers an interval spanning the
cutover; a genuine gap does not; unrelated records are never bridged. Coverage is
computed with half-open local-day boundaries in the operator timezone and is
independent of record order.

These use real create/submit/verify/supersede actions (never direct injection of
protected state). The synthetic example is the one named in the task.
"""
from datetime import date, datetime, time, timedelta

import pytz

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import OperationsCase

TZ = pytz.timezone("Asia/Dubai")


@tagged("post_install", "-at_install")
class TestEffectiveCutover(OperationsCase):

    # -- helpers ---------------------------------------------------------
    def _make(self, kind, field, subj, start, end, precision="day", verify=True):
        cred = self.env["fleetflow.credential"].create({
            "name": "%s-%s" % (kind, subj.id), "doc_kind": kind,
            "company_id": self.company.id, field: subj.id,
            "date_start": start, "date_end": end, "date_precision": precision})
        if verify:
            cred.with_user(self.compliance).action_verify()
        return cred

    def _supersede(self, cred, start, end, precision="day", verify=True, name="renewal"):
        renewal = cred.browse(cred.with_user(self.compliance).action_supersede({
            "name": name, "date_start": start, "date_end": end,
            "date_precision": precision}))
        if verify:
            renewal.with_user(self.compliance).action_verify()
        return renewal

    def _iv(self, y, m, d, h1=8, h2=18):
        return (TZ.localize(datetime(y, m, d, h1, 0)),
                TZ.localize(datetime(y, m, d, h2, 0)))

    def _resolve(self, creds, start, end):
        return self.env["fleetflow.credential"]._resolve_coverage(creds, start, end, TZ)

    # -- the named synthetic example ------------------------------------
    def _synthetic(self):
        """Predecessor valid through 31 Dec 2026; successor approved 26 Sep 2026,
        effective 1 Oct 2026, valid through 31 Oct 2026."""
        pred = self._make("vehicle_registration", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        succ = self._supersede(pred, date(2026, 10, 1), date(2026, 10, 31))
        return pred, succ

    def test_synthetic_predecessor_covers_before_cutover(self):
        pred, succ = self._synthetic()
        creds = pred + succ
        s, e = self._iv(2026, 9, 30)
        self.assertEqual(self._resolve(creds, s, e), pred)

    def test_synthetic_successor_covers_at_and_after_cutover(self):
        pred, succ = self._synthetic()
        creds = pred + succ
        s, e = self._iv(2026, 10, 1)
        self.assertEqual(self._resolve(creds, s, e), succ)

    def test_synthetic_no_fallback_to_predecessor_after_cutover(self):
        # 1 Nov: successor already expired (through 31 Oct), predecessor must NOT
        # fall back even though its own expiry is 31 Dec 2026.
        pred, succ = self._synthetic()
        creds = pred + succ
        s, e = self._iv(2026, 11, 1)
        self.assertFalse(self._resolve(creds, s, e))
        # And the predecessor on its own is judged expired for that interval.
        self.assertEqual(pred._validity(s, e, TZ), "expired")

    def test_synthetic_continuous_interval_spans_cutover(self):
        pred, succ = self._synthetic()
        creds = pred + succ
        start = TZ.localize(datetime(2026, 9, 30, 8, 0))
        end = TZ.localize(datetime(2026, 10, 1, 18, 0))
        chain = self._resolve(creds, start, end)
        self.assertEqual(chain, pred + succ)
        self.assertEqual(chain[-1], succ)  # the record used at the interval end

    def test_exact_cutover_boundary_is_half_open(self):
        pred, succ = self._synthetic()
        creds = pred + succ
        cutover = TZ.localize(datetime(2026, 10, 1, 0, 0))
        # An interval ending exactly at the cutover is the predecessor's.
        self.assertEqual(self._resolve(creds, cutover - timedelta(hours=2), cutover), pred)
        # An interval starting exactly at the cutover is the successor's.
        self.assertEqual(self._resolve(creds, cutover, cutover + timedelta(hours=2)), succ)

    def test_revoking_successor_after_activation_does_not_restore_predecessor(self):
        pred, succ = self._synthetic()
        creds = pred + succ
        succ.with_user(self.compliance).action_reject(reason="successor revoked")
        self.assertEqual(succ.state, "rejected")
        self.assertEqual(pred.state, "superseded")     # cutover not erased
        # Before the cutover the predecessor still covers (its own status governs);
        # at/after the cutover nothing covers (predecessor is not resurrected).
        self.assertEqual(self._resolve(creds, *self._iv(2026, 9, 30)), pred)
        self.assertFalse(self._resolve(creds, *self._iv(2026, 10, 15)))
        self.assertFalse(self._resolve(creds, *self._iv(2026, 11, 1)))

    def test_successor_revoked_before_future_start_keeps_recorded_cutoff(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        future = date.today() + timedelta(days=20)
        succ = self._supersede(pred, future, future + timedelta(days=200))
        succ.with_user(self.compliance).action_reject(reason="revoked before start")
        self.assertEqual(pred.state, "superseded")
        cutover = TZ.localize(datetime(future.year, future.month, future.day))
        # Before the recorded cutoff: predecessor still governs and covers.
        self.assertEqual(pred._validity(cutover - timedelta(hours=4), cutover, TZ), "covers")
        # At/after the cutoff: no coverage (cutoff is not silently erased).
        self.assertEqual(pred._validity(cutover, cutover + timedelta(hours=4), TZ), "expired")

    # -- rejected/never-approved renewals -------------------------------
    def test_never_approved_rejected_renewal_leaves_coverage_intact(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        renewal = self._supersede(pred, date(2026, 10, 1), date(2027, 9, 30), verify=False)
        renewal.with_user(self.compliance).action_reject(reason="rejected renewal")
        self.assertEqual(pred.state, "verified")       # untouched
        self.assertEqual(self._resolve(pred + renewal, *self._iv(2026, 11, 1)), pred)

    def test_revoked_predecessor_before_future_successor_starts(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        renewal = self._supersede(pred, date(2026, 11, 1), date(2027, 10, 31), verify=False)
        pred.with_user(self.compliance).action_reject(reason="predecessor revoked")
        # Predecessor revoked, renewal still a draft -> nothing covers now.
        self.assertFalse(self._resolve(pred + renewal, *self._iv(2026, 6, 1)))
        # The renewal can still be approved independently (predecessor already
        # dead, so it is not superseded/resurrected); its own window then covers.
        renewal.with_user(self.compliance).action_verify()
        self.assertEqual(pred.state, "rejected")       # not resurrected
        self.assertEqual(self._resolve(pred + renewal, *self._iv(2026, 12, 1)), renewal)
        self.assertFalse(self._resolve(pred + renewal, *self._iv(2026, 6, 1)))

    # -- gaps, chains, boundaries ---------------------------------------
    def test_real_gap_between_predecessor_and_successor_not_covered(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 3, 31))
        self._supersede(pred, date(2026, 6, 1), date(2026, 12, 31))  # gap in April/May
        creds = self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", self.vehicle.id), ("doc_kind", "=", "insurance")])
        self.assertFalse(self._resolve(creds, *self._iv(2026, 5, 1)))   # in the gap
        self.assertTrue(self._resolve(creds, *self._iv(2026, 2, 1)))    # before
        self.assertTrue(self._resolve(creds, *self._iv(2026, 7, 1)))    # after

    def test_multi_revision_chain_covers_across_two_cutovers(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 6, 30))
        r1 = self._supersede(pred, date(2026, 7, 1), date(2026, 9, 30), name="r1")
        r2 = self._supersede(r1, date(2026, 10, 1), date(2026, 12, 31), name="r2")
        creds = pred + r1 + r2
        # A single point in each segment resolves to the correct single record.
        self.assertEqual(self._resolve(creds, *self._iv(2026, 3, 1)), pred)
        self.assertEqual(self._resolve(creds, *self._iv(2026, 8, 1)), r1)
        self.assertEqual(self._resolve(creds, *self._iv(2026, 11, 1)), r2)
        # An interval spanning both cutovers is covered by the whole chain.
        start = TZ.localize(datetime(2026, 6, 30, 8, 0))
        end = TZ.localize(datetime(2026, 10, 1, 18, 0))
        self.assertEqual(self._resolve(creds, start, end), pred + r1 + r2)

    def test_coverage_is_order_independent(self):
        pred, succ = self._synthetic()
        start = TZ.localize(datetime(2026, 9, 30, 8, 0))
        end = TZ.localize(datetime(2026, 10, 1, 18, 0))
        forward = self._resolve(pred + succ, start, end)
        reverse = self._resolve(succ + pred, start, end)
        self.assertEqual(set(forward.ids), set(reverse.ids))

    def test_unrelated_records_are_not_bridged(self):
        # Two unrelated verified records with a gap between them are NOT combined
        # into a chain to cover an interval sitting in the gap.
        a = self._make("insurance", "vehicle_id", self.vehicle,
                       date(2026, 1, 1), date(2026, 3, 31))
        b = self.env["fleetflow.credential"].create({
            "name": "unrelated-b", "doc_kind": "insurance", "company_id": self.company.id,
            "vehicle_id": self.vehicle.id, "date_start": date(2026, 6, 1),
            "date_end": date(2026, 12, 31)})
        b.with_user(self.compliance).action_verify()
        self.assertFalse(b.supersedes_id)  # genuinely unrelated
        self.assertFalse(self._resolve(a + b, *self._iv(2026, 5, 1)))  # gap not bridged

    # -- competing drafts / competing approvals (single-thread) ---------
    def test_competing_drafts_only_one_approval_forms_the_chain(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        r1 = self._supersede(pred, date(2026, 10, 1), date(2027, 9, 30),
                             verify=False, name="r1")
        r2 = self._supersede(pred, date(2026, 10, 1), date(2027, 9, 30),
                             verify=False, name="r2")
        # First approval wins and supersedes the predecessor.
        r1.with_user(self.compliance).action_verify()
        self.assertEqual(pred.state, "superseded")
        self.assertEqual(pred.superseded_by_id, r1)
        # The competing approval is refused: one unambiguous chain only.
        with self.assertRaises(UserError):
            r2.with_user(self.compliance).action_verify()
        self.assertEqual(pred.superseded_by_id, r1)

    # -- imprecise/missing effective date is not guessed ----------------
    def test_renewal_without_precise_effective_date_cannot_be_approved(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        # Missing effective (Valid from) date.
        no_start = pred.browse(pred.with_user(self.compliance).action_supersede({
            "name": "no-start", "date_end": date(2027, 6, 30)}))
        with self.assertRaises(UserError):
            no_start.with_user(self.compliance).action_verify()
        # Imprecise effective date.
        imprecise = pred.browse(pred.with_user(self.compliance).action_supersede({
            "name": "imprecise", "date_start": date(2026, 10, 1),
            "date_end": date(2027, 6, 30), "date_precision": "year"}))
        with self.assertRaises(UserError):
            imprecise.with_user(self.compliance).action_verify()
        self.assertEqual(pred.state, "verified")  # never superseded by an ambiguous one

    def test_ambiguous_legacy_cutover_surfaces_for_review(self):
        # Simulate a legacy chain whose successor lacks a precise effective date
        # (only reachable in old data; the approval guard now prevents creating
        # one). Such a predecessor grants NO coverage -> surfaced for review,
        # rather than silently reopening its old full range.
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        succ = self._supersede(pred, date(2026, 10, 1), date(2027, 9, 30))
        # Force the successor's effective date to imprecise at ORM level (bypassing
        # the frozen guard) to mimic legacy data.
        succ._apply({"date_precision": "year"})
        succ.invalidate_recordset()
        self.assertIsNone(pred._cutover(TZ))
        self.assertEqual(pred._validity(*self._iv(2026, 6, 1), TZ), "unknown")
        self.assertFalse(self._resolve(pred + succ, *self._iv(2026, 6, 1)))

    # -- forged replacement history rejected ----------------------------
    def test_ordinary_write_cannot_forge_replacement_links(self):
        pred = self._make("insurance", "vehicle_id", self.vehicle,
                          date(2026, 1, 1), date(2026, 12, 31))
        other = self._make("inspection", "vehicle_id", self.vehicle,
                           date(2026, 1, 1), date(2026, 12, 31))
        from odoo.exceptions import AccessError
        for vals in ({"superseded_by_id": other.id}, {"supersedes_id": other.id},
                     {"replaced_on": datetime(2026, 1, 1)}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                pred.with_user(self.compliance).write(vals)

    def test_copy_does_not_carry_replacement_history(self):
        pred, succ = self._synthetic()
        clone = pred.copy()
        self.assertEqual(clone.state, "draft")
        self.assertFalse(clone.superseded_by_id)
        self.assertFalse(clone.supersedes_id)
        self.assertFalse(clone.replaced_on)
        self.assertFalse(clone.ever_verified)
