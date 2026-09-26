# -*- coding: utf-8 -*-
"""Genuinely-structured synthetic PDF fixtures for evidence-file validation tests.

Every positive fixture here is a REAL PDF: a binary header, numbered objects, a
correct cross-reference table, a trailer with /Root, and startxref/%%EOF. They
parse under the runtime parser (PyPDF2 1.26.0, the version bundled in the
odoo:16.0 image, Python 3.9). The negative fixtures are deliberately malformed or
carry a prohibited feature reachable only through the parsed object graph
(indirection, hex-escaped names, an incremental update), never a raw byte match.

This module imports nothing from Odoo so it can also be run standalone to
regenerate/verify the bytes against the real parser.
"""


def build_pdf(objects, root_ref="1 0 R", extra_trailer="", trailer_encrypt=None):
    """Assemble a structurally valid PDF from ``objects``.

    ``objects`` is an ordered list of ``(number, body_bytes)`` with numbers
    starting at 1 and contiguous. ``body_bytes`` is the object body WITHOUT the
    ``N 0 obj`` / ``endobj`` wrapper (for a stream object include the
    ``<< dict >>\\nstream\\n...\\nendstream`` yourself). Offsets and the xref
    table are computed for real, so the result parses.
    """
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")  # binary marker line
    offsets = {}
    for number, body in objects:
        offsets[number] = len(out)
        out += ("%d 0 obj\n" % number).encode("latin-1")
        out += body
        out += b"\nendobj\n"
    xref_pos = len(out)
    size = len(objects) + 1  # including the free object 0
    out += ("xref\n0 %d\n" % size).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for number, _ in objects:
        out += ("%010d 00000 n \n" % offsets[number]).encode("latin-1")
    trailer = "<< /Size %d /Root %s" % (size, root_ref)
    if trailer_encrypt:
        trailer += " /Encrypt %s" % trailer_encrypt
    if extra_trailer:
        trailer += " " + extra_trailer
    trailer += " >>"
    out += b"trailer\n" + trailer.encode("latin-1") + b"\n"
    out += b"startxref\n" + ("%d\n" % xref_pos).encode("latin-1") + b"%%EOF\n"
    return bytes(out)


# ---------------------------------------------------------------------------
# Positive fixtures (must be accepted)
# ---------------------------------------------------------------------------
_PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>"

ONE_PAGE_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
])

MULTI_PAGE_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"),
    (4, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"),
    (5, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"),
])

# A page whose only content is a 1x1 image XObject (an "image-based" PDF).
_IMG_CONTENT = b"q 100 0 0 100 0 0 cm /Im0 Do Q"
IMAGE_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        b"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"),
    (4, b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\n"
        b"stream\n\x00\nendstream"),
    (5, ("<< /Length %d >>\nstream\n" % len(_IMG_CONTENT)).encode("latin-1")
        + _IMG_CONTENT + b"\nendstream"),
])

# Harmless page text that literally spells a prohibited keyword inside a content
# stream. It is NOT an executable feature and must be accepted (no raw match).
_TEXT = b"BT /F1 12 Tf 72 720 Td (This licence mentions /JavaScript and /Launch as text) Tj ET"
TEXT_KEYWORD_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
    (4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    (5, ("<< /Length %d >>\nstream\n" % len(_TEXT)).encode("latin-1")
        + _TEXT + b"\nendstream"),
])

VALID_PDFS = {
    "one_page": ONE_PAGE_PDF,
    "multi_page": MULTI_PAGE_PDF,
    "image": IMAGE_PDF,
    "text_keyword": TEXT_KEYWORD_PDF,
}

# ---------------------------------------------------------------------------
# Negative fixtures (must be rejected as business validation errors)
# ---------------------------------------------------------------------------
# Plausible header + %%EOF, but no objects, xref or startxref: not a document.
FAKE_HEADER_PDF = b"%PDF-1.4\nthis is not really a pdf, just a prefix and a marker\n%%EOF\n"

# A truncated valid document (cut before the xref/trailer).
TRUNCATED_PDF = ONE_PAGE_PDF[: len(ONE_PAGE_PDF) // 2]

# Valid frame, but the catalog's /Pages points at a non-existent object.
BROKEN_REF_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 9 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
])

# JavaScript reached only by resolving an INDIRECT /OpenAction object.
JS_INDIRECT_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
    (4, b"<< /S /JavaScript /JS (app.alert\\(1\\)) >>"),
])

# An action subtype name that is hex-escaped (/Laun#63h == /Launch), reached
# through a link annotation. Nothing else here is a banned key, so ONLY the
# name-normalisation path can catch it (an escape must not bypass the policy).
JS_ESCAPED_NAME_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Annots [4 0 R] >>"),
    (4, b"<< /Type /Annot /Subtype /Link /Rect [0 0 10 10] "
        b"/A << /S /Laun#63h /F (calc.exe) >> >>"),
])

ACROFORM_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R /AcroForm 4 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
    (4, b"<< /Fields [] /NeedAppearances true >>"),
])

# An embedded file reached through the /Names -> /EmbeddedFiles name tree.
EMBEDDED_FILE_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R /Names 4 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
    (4, b"<< /EmbeddedFiles 5 0 R >>"),
    (5, b"<< /Names [ (evil.exe) 6 0 R ] >>"),
    (6, b"<< /Type /Filespec /F (evil.exe) /EF << /F 7 0 R >> >>"),
    (7, b"<< /Type /EmbeddedFile /Length 3 >>\nstream\nbad\nendstream"),
])

# A rich-media / screen annotation on the page.
RICHMEDIA_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Annots [4 0 R] >>"),
    (4, b"<< /Type /Annot /Subtype /Screen /Rect [0 0 10 10] /P 3 0 R >>"),
])

# A /Launch action on a link annotation.
LAUNCH_ANNOT_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Annots [4 0 R] >>"),
    (4, b"<< /Type /Annot /Subtype /Link /Rect [0 0 10 10] "
        b"/A << /S /Launch /F (calc.exe) >> >>"),
])

# Additional-actions dictionary on the catalog.
AA_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R /AA << /O << /S /JavaScript /JS (x) >> >> >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
])


def incremental_update_js_pdf():
    """A valid base document plus an incremental update that REDEFINES the catalog
    to add an /OpenAction JavaScript. The effective (latest) catalog carries the
    prohibited feature; only a parser that follows the last xref + /Prev sees it.
    """
    base = ONE_PAGE_PDF
    # startxref value of the base (its original xref offset).
    marker = base.rfind(b"startxref\n")
    base_xref = int(base[marker + len(b"startxref\n"):].split(b"\n", 1)[0])
    out = bytearray(base)
    obj_off = len(out)
    out += (b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R "
            b"/OpenAction << /S /JavaScript /JS (x) >> >>\nendobj\n")
    xref_off = len(out)
    out += b"xref\n1 1\n" + ("%010d 00000 n \n" % obj_off).encode("latin-1")
    out += b"trailer\n"
    out += ("<< /Size 4 /Root 1 0 R /Prev %d >>\n" % base_xref).encode("latin-1")
    out += b"startxref\n" + ("%d\n" % xref_off).encode("latin-1") + b"%%EOF\n"
    return bytes(out)


INCREMENTAL_UPDATE_JS_PDF = incremental_update_js_pdf()

# A trailer that declares /Encrypt: the parser reports the document as encrypted
# and it cannot be inspected, so it is rejected (no password handling is added).
ENCRYPTED_PDF = build_pdf([
    (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
    (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    (3, _PAGE),
    (4, b"<< /Filter /Standard /V 1 /R 2 "
        b"/O (00000000000000000000000000000000) "
        b"/U (00000000000000000000000000000000) /P -44 >>"),
], trailer_encrypt="4 0 R")

BAD_PDFS = {
    "fake_header": FAKE_HEADER_PDF,
    "truncated": TRUNCATED_PDF,
    "broken_ref": BROKEN_REF_PDF,
    "js_indirect": JS_INDIRECT_PDF,
    "js_escaped_name": JS_ESCAPED_NAME_PDF,
    "acroform": ACROFORM_PDF,
    "embedded_file": EMBEDDED_FILE_PDF,
    "richmedia": RICHMEDIA_PDF,
    "launch_annot": LAUNCH_ANNOT_PDF,
    "aa": AA_PDF,
    "incremental_update_js": INCREMENTAL_UPDATE_JS_PDF,
    "encrypted": ENCRYPTED_PDF,
}

# A small genuinely-valid PDF for use as an accepted evidence source across the
# lifecycle/HTTP tests (replaces the earlier structurally-invalid stubs).
VALID_PDF = ONE_PAGE_PDF
