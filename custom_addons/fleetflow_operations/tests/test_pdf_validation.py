# -*- coding: utf-8 -*-
"""Structural PDF (and image) evidence-file acceptance policy.

Positives are genuinely valid PDFs (one/multi page, image-based) and images;
negatives are malformed documents or ones carrying a prohibited feature reachable
only through the parsed object graph (indirection, hex-escaped name, incremental
update, embedded file, encryption). Validation runs on the real bytes at binding
and again at verification, using the runtime parser (PyPDF2 1.26.0). No active
content is executed.
"""
import io

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import OperationsCase
from .pdf_fixtures import VALID_PDFS, BAD_PDFS, ONE_PAGE_PDF


@tagged("post_install", "-at_install")
class TestPdfValidation(OperationsCase):

    def _bind(self, data, name="e.pdf"):
        """Create an attachment with `data` and bind it as draft evidence. Binding
        runs the full file policy on the real bytes."""
        att = self.env["ir.attachment"].create({"name": name, "raw": data})
        return self.env["fleetflow.credential"].create({
            "name": "pdf-%s" % name, "doc_kind": "driver_licence",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": att.id})

    # -- positives -------------------------------------------------------
    def test_valid_pdfs_bind_and_verify(self):
        for name, data in VALID_PDFS.items():
            with self.subTest(pdf=name), self.cr.savepoint():
                cred = self._bind(data, "%s.pdf" % name)
                cred.with_user(self.compliance).action_verify()
                self.assertEqual(cred.state, "verified", name)

    def test_harmless_keyword_text_is_accepted(self):
        # A page whose text literally spells /JavaScript and /Launch is NOT an
        # executable feature and must be accepted (no raw-substring rejection).
        cred = self._bind(VALID_PDFS["text_keyword"], "keyword.pdf")
        cred.with_user(self.compliance).action_verify()
        self.assertEqual(cred.state, "verified")

    def test_valid_png_and_jpeg_accepted(self):
        from PIL import Image
        for fmt, ext in (("PNG", "png"), ("JPEG", "jpg")):
            with self.subTest(fmt=fmt), self.cr.savepoint():
                buf = io.BytesIO()
                Image.new("RGB", (8, 8), (120, 120, 120)).save(buf, fmt)
                cred = self._bind(buf.getvalue(), "img.%s" % ext)
                cred.with_user(self.compliance).action_verify()
                self.assertEqual(cred.state, "verified", fmt)

    # -- negatives -------------------------------------------------------
    def test_bad_pdfs_are_rejected_as_business_errors(self):
        for name, data in BAD_PDFS.items():
            with self.subTest(pdf=name), self.cr.savepoint():
                with self.assertRaises(UserError, msg="accepted bad PDF: %s" % name):
                    self._bind(data, "%s.pdf" % name)

    def test_non_document_content_rejected(self):
        for data in (b"", b"hello, not a document", b"MZ\x90\x00fake exe"):
            with self.cr.savepoint():
                with self.assertRaises(UserError):
                    self._bind(data, "junk.bin")

    def test_oversize_pdf_rejected_before_parse(self):
        big = b"%PDF-1.5\n" + b"0" * (15 * 1024 * 1024 + 1)
        with self.assertRaises(UserError):
            self._bind(big, "big.pdf")

    def test_file_changed_after_link_fails_at_verify(self):
        # Bind a valid PDF (allowed), swap the bytes for a malformed one while still
        # a draft, then verify: the CURRENT bytes are re-validated and rejected.
        cred = self._bind(ONE_PAGE_PDF, "ok.pdf")
        cred.attachment_id.sudo().write({"raw": BAD_PDFS["fake_header"]})
        with self.assertRaises(UserError):
            cred.with_user(self.compliance).action_verify()
        self.assertNotEqual(cred.state, "verified")

    def test_prohibited_feature_change_after_link_fails_at_verify(self):
        cred = self._bind(ONE_PAGE_PDF, "ok2.pdf")
        cred.attachment_id.sudo().write({"raw": BAD_PDFS["js_indirect"]})
        with self.assertRaises(UserError):
            cred.with_user(self.compliance).action_verify()
        self.assertNotEqual(cred.state, "verified")
