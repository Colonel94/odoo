# -*- coding: utf-8 -*-
"""Reproduction + regression for safe document ownership (R03).

Binding a document to a credential must never take ownership of another user's,
company's or record's private file, and must never expose or overwrite a file
that already backs verified evidence. Uploads are limited to genuine document
types judged by their actual bytes. A rejected link leaves the original file
completely unchanged.

These are ORM/model-level checks with ordinary role accounts; the authenticated
HTTP/binary/download variants live in test_http_boundary.py (ff_http).
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import OperationsCase

PDF = b"%PDF-1.4 synthetic evidence body"


@tagged("post_install", "-at_install")
class TestDocumentOwnership(OperationsCase):

    def _att(self, user, **vals):
        base = {"name": "doc.pdf", "raw": PDF}
        base.update(vals)
        return self.env["ir.attachment"].with_user(user).create(base)

    def _cred(self, user, attachment_id, subject=None):
        return self.env["fleetflow.credential"].with_user(user).create({
            "name": "C", "doc_kind": "driver_licence", "company_id": self.company.id,
            "driver_id": (subject or self.driver).id, "attachment_id": attachment_id})

    # -- positive: an authorized own upload binds ------------------------
    def test_own_unbound_upload_binds_and_privatises(self):
        att = self._att(self.compliance)  # compliance's own unbound upload
        cred = self._cred(self.compliance, att.id)
        att.invalidate_recordset()
        self.assertEqual(att.res_model, "fleetflow.credential")
        self.assertEqual(att.res_id, cred.id)
        self.assertFalse(att.public)
        with self.assertRaises(AccessError):
            att.with_user(self.dispatcher).check("read")

    # -- reject foreign / already-bound / wrong-company / bad content ----
    def test_foreign_file_bound_elsewhere_is_rejected_and_unchanged(self):
        # A file already bound to another record must not be stolen by referencing
        # its id from a credential. (Built via sudo so the fixture itself does not
        # trip res.partner write rules; the ACTION under test is run as compliance.)
        att = self.env["ir.attachment"].sudo().create({
            "name": "foreign.pdf", "raw": PDF,
            "res_model": "res.partner", "res_id": self.dispatcher.partner_id.id})
        before = (att.res_model, att.res_id, att.public)
        # This image's assertRaises does not accept a tuple of types, so match
        # either denial (AccessError from the file check, UserError from the
        # bound-elsewhere check) with an explicit try/except.
        raised = None
        try:
            with self.cr.savepoint():
                self._cred(self.compliance, att.id)
        except (AccessError, UserError) as exc:
            raised = exc
        self.assertTrue(raised, "binding a file bound elsewhere must be rejected")
        att.invalidate_recordset()
        self.assertEqual((att.res_model, att.res_id, att.public), before)

    def test_attachment_bound_to_other_credential_is_rejected(self):
        first = self._att(self.compliance)
        c1 = self._cred(self.compliance, first.id)  # binds to c1
        with self.assertRaises(UserError), self.cr.savepoint():
            self._cred(self.compliance, first.id)   # try to reuse the same file
        first.invalidate_recordset()
        self.assertEqual(first.res_id, c1.id)

    def test_foreign_company_file_is_rejected(self):
        att = self._att(self.compliance)
        att.sudo().write({"company_id": self.other_company.id})  # simulate a foreign file
        with self.assertRaises(UserError), self.cr.savepoint():
            self._cred(self.compliance, att.id)

    def test_active_content_is_rejected(self):
        att = self._att(self.compliance, name="x.html",
                        raw=b"<html><script>alert(1)</script></html>")
        with self.assertRaises(UserError), self.cr.savepoint():
            self._cred(self.compliance, att.id)

    def test_empty_file_is_rejected(self):
        att = self._att(self.compliance, raw=b"")
        with self.assertRaises(UserError), self.cr.savepoint():
            self._cred(self.compliance, att.id)

    # -- a verified source is immutable ----------------------------------
    def test_verified_evidence_source_cannot_be_mutated_or_deleted(self):
        att = self._att(self.compliance)
        cred = self._cred(self.compliance, att.id)
        cred.with_user(self.compliance).action_verify()
        for vals in ({"raw": b"%PDF-1.4 tampered"}, {"public": True},
                     {"res_model": "res.partner"}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                att.with_user(self.compliance).write(vals)
        with self.assertRaises(AccessError), self.cr.savepoint():
            att.with_user(self.compliance).unlink()

    def test_other_company_reviewer_cannot_read_evidence_file(self):
        att = self._att(self.compliance)
        cred = self._cred(self.compliance, att.id)
        cred.with_user(self.compliance).action_verify()
        other = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Co-B compliance", "login": "ff.ob.comp",
            "email": "ff.ob.comp@example.com",
            "company_id": self.other_company.id,
            "company_ids": [(6, 0, [self.other_company.id])],
            "groups_id": [(6, 0, [self.env.ref(
                "fleetflow_operations.group_ops_compliance").id])]})
        # A compliance reviewer of ANOTHER company cannot fetch this company's file.
        with self.assertRaises(AccessError):
            att.with_user(other).check("read")
        # The owning company's reviewer still can.
        att.with_user(self.compliance).check("read")

    def test_verified_source_cannot_be_rebound(self):
        att = self._att(self.compliance)
        cred = self._cred(self.compliance, att.id)
        cred.with_user(self.compliance).action_verify()
        # A generic rebind of the frozen source to another record is refused.
        with self.assertRaises(AccessError), self.cr.savepoint():
            att.with_user(self.compliance).write({"res_model": "res.partner"})
        att.invalidate_recordset()
        self.assertEqual((att.res_model, att.res_id), ("fleetflow.credential", cred.id))
