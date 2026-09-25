# -*- coding: utf-8 -*-
"""Authenticated HTTP/JSON-RPC acceptance for the approval + document boundary.

Unlike the ORM tests, these drive the SAME public endpoints a browser or API
client would: real authenticated sessions (dispatcher, driver, compliance, fleet
manager, and a reviewer limited to a second company) call `/web/dataset/call_kw`
and `/web/content`. Superuser only builds fixtures; every action under test runs
as an ordinary role. We assert the RESPONSE BODY and the resulting DB state (an
HTTP 200 can still carry an application error), not just the transport status.

Tagged `ff_http` and excluded from the default `--no-http` model run; executed by
`python fleetflow/manage.py test-http` (and its CI job) with the HTTP server on.
"""
import base64
import json
from datetime import date, datetime, time, timedelta

from odoo.tests import tagged
from odoo.tests.common import HttpCase

# A minimal but structurally-valid PDF (has %%EOF, no active/embedded content).
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
PW = "boundary-http-pw"


@tagged("post_install", "-at_install", "ff_http")
class TestHttpBoundary(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.other_company = env["res.company"].create({"name": "HTTP other co"})

        def user(login, *groups, company=None):
            company = company or cls.company
            return env["res.users"].with_context(no_reset_password=True).create({
                "name": login, "login": login, "password": PW,
                "email": login + "@example.com", "company_id": company.id,
                "company_ids": [(6, 0, [company.id])],
                "groups_id": [(6, 0, [env.ref(g).id for g in groups])]})

        cls.dispatcher = user("http.disp", "fleetflow_operations.group_ops_dispatcher")
        cls.compliance = user("http.comp", "fleetflow_operations.group_ops_compliance")
        cls.manager = user("http.mgr", "fleetflow_operations.group_ops_fleet_manager")
        cls.other_comp = user("http.ocomp", "fleetflow_operations.group_ops_compliance",
                              company=cls.other_company)
        # A reviewer allowed in BOTH internal companies (for the transfer test).
        cls.two_comp = env["res.users"].with_context(no_reset_password=True).create({
            "name": "http.twoco", "login": "http.twoco", "password": PW,
            "email": "http.twoco@example.com", "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id, cls.other_company.id])],
            "groups_id": [(6, 0, [env.ref("fleetflow_operations.group_ops_compliance").id])]})

        brand = env["fleet.vehicle.model.brand"].create({"name": "HTTP brand"})
        model = env["fleet.vehicle.model"].create({"name": "HTTP model", "brand_id": brand.id})
        cls.vehicle = env["fleet.vehicle"].create({
            "model_id": model.id, "license_plate": "HTTP-1", "company_id": cls.company.id,
            "ff_operator_company_id": cls.company.id, "ff_operational_state": "reviewed"})
        cls.driver = env["fleetflow.driver"].create({
            "name": "HTTP driver", "employee_ref": "HTTP-D", "company_id": cls.company.id})

        cls.profile = env["fleetflow.operating.profile"].create({
            "name": "HTTP chauffeur", "company_id": cls.company.id, "operating_mode": "chauffeur",
            "require_operating_authorization": False, "require_vehicle_registration": True,
            "require_insurance": True, "require_driver_licence": True,
            "require_professional_permit": False, "require_channel_approval": True,
            "enforce_end_of_use": False})
        cls.profile.action_publish()

        def cred(kind, field, subj, attach=False):
            vals = {"name": "%s-http" % kind, "doc_kind": kind, "company_id": cls.company.id,
                    field: subj.id, "date_start": date.today() - timedelta(days=10),
                    "date_end": date.today() + timedelta(days=365)}
            if attach:
                att = env["ir.attachment"].create({"name": "%s.pdf" % kind, "raw": PDF})
                vals["attachment_id"] = att.id
            c = env["fleetflow.credential"].create(vals)
            c.action_verify()
            return c
        cls.reg = cred("vehicle_registration", "vehicle_id", cls.vehicle)
        cls.ins = cred("insurance", "vehicle_id", cls.vehicle)
        cls.lic = cred("driver_licence", "driver_id", cls.driver, attach=True)
        cls.evidence_att = cls.lic.attachment_id  # verified source, private

        def enrol(field, subj, state="approved", channel="uber", product="UberX"):
            e = env["fleetflow.channel.enrolment"].create({
                "company_id": cls.company.id, "channel": channel, "product": product,
                "city": "Dubai", field: subj.id})
            {"approved": e.action_approve, "suspended": e.action_suspend}[state]()
            return e
        cls.enr_v = enrol("vehicle_id", cls.vehicle)
        cls.enr_d = enrol("driver_id", cls.driver)
        # A suspended enrolment on a DIFFERENT product, so it does not pollute the
        # uber readiness used by B05 but still exercises the "lift suspension" path.
        cls.enr_suspended = enrol("driver_id", cls.driver, state="suspended",
                                  channel="careem", product="CareemX")

        # A foreign file already bound to another record (for the reject case).
        cls.foreign_att = env["ir.attachment"].create({
            "name": "foreign.pdf", "raw": PDF, "res_model": "res.partner",
            "res_id": cls.dispatcher.partner_id.id})

        # A hold on a SEPARATE vehicle (so it does not block the allocation below).
        cls.hold_vehicle = env["fleet.vehicle"].create({
            "model_id": model.id, "license_plate": "HTTP-HOLD", "company_id": cls.company.id,
            "ff_operator_company_id": cls.company.id, "ff_operational_state": "reviewed"})
        cls.hold = env["fleetflow.vehicle.hold"].create({
            "vehicle_id": cls.hold_vehicle.id, "hold_type": "safety",
            "reason": "http brake fault", "dispatch_blocking": True})

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _rpc(self, model, method, args, kwargs=None):
        """Authenticated JSON-RPC call. Returns the parsed body ('result'/'error')."""
        resp = self.url_open("/web/dataset/call_kw", data=json.dumps({
            "jsonrpc": "2.0", "method": "call",
            "params": {"model": model, "method": method, "args": args, "kwargs": kwargs or {}},
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 200, "transport should be 200; app errors live in the body")
        return resp.json()

    # Business exceptions we accept as a legitimate denial. An unrelated
    # programming error / HTTP 500 has a different data.name and must FAIL the test.
    _BUSINESS_ERRORS = (
        "odoo.exceptions.AccessError", "odoo.exceptions.UserError",
        "odoo.exceptions.ValidationError", "odoo.exceptions.AccessDenied",
        "odoo.exceptions.MissingError",
    )

    def _denied(self, body):
        """True if the body carries ANY application error (used only for the
        negative of success assertions, where a 500 should also fail the test)."""
        return isinstance(body, dict) and "error" in body

    def _error_name(self, body):
        if not (isinstance(body, dict) and "error" in body):
            return None
        return ((body["error"] or {}).get("data") or {}).get("name")

    def _assert_denied(self, body, *allowed):
        """Assert the call was denied by a BUSINESS exception (not a 500 / bug)."""
        allowed = allowed or self._BUSINESS_ERRORS
        name = self._error_name(body)
        self.assertIn(name, allowed,
                      "expected a business denial %s, got: %s" % (allowed, body))

    def _assert_ok(self, body):
        """Assert the call succeeded (no error payload at all)."""
        self.assertFalse(self._denied(body), body)
        return body.get("result")

    # ------------------------------------------------------------------
    # B01 -- dispatcher cannot transfer/relabel an approved enrolment or
    #        silently lift a suspension.
    # ------------------------------------------------------------------
    def test_B01_dispatcher_cannot_mutate_approved_or_lift_suspension(self):
        self.authenticate("http.disp", PW)
        self._assert_denied(self._rpc("fleetflow.channel.enrolment", "write",
                                      [[self.enr_d.id], {"city": "Abu Dhabi"}]))
        self._assert_denied(self._rpc("fleetflow.channel.enrolment", "write",
                                      [[self.enr_suspended.id], {"state": "pending"}]))
        self.enr_d.invalidate_recordset()
        self.enr_suspended.invalidate_recordset()
        self.assertEqual(self.enr_d.city, "Dubai")
        self.assertEqual(self.enr_suspended.state, "suspended")

    # ------------------------------------------------------------------
    # B02 -- legitimate writers cannot downgrade a verified credential or a
    #        published policy in place.
    # ------------------------------------------------------------------
    def test_B02_compliance_cannot_downgrade_history(self):
        self.authenticate("http.comp", PW)
        self._assert_denied(self._rpc(
            "fleetflow.credential", "write", [[self.reg.id], {"state": "draft"}]))
        self._assert_denied(self._rpc(
            "fleetflow.operating.profile", "write", [[self.profile.id], {"state": "draft"}]))
        self.reg.invalidate_recordset()
        self.profile.invalidate_recordset()
        self.assertEqual(self.reg.state, "verified")
        self.assertEqual(self.profile.state, "published")

    # ------------------------------------------------------------------
    # B03 -- create/default-context cannot fabricate reviewed states.
    # ------------------------------------------------------------------
    def test_B03_create_cannot_forge_review_state(self):
        self.authenticate("http.mgr", PW)
        body = self._rpc("fleet.vehicle", "create", [{
            "model_id": self.vehicle.model_id.id, "license_plate": "HTTP-FORGE",
            "company_id": self.company.id, "ff_operator_company_id": self.company.id,
            "ff_operational_state": "reviewed", "ff_end_of_use_exempt": True}])
        self.assertFalse(self._denied(body), body)
        v = self.env["fleet.vehicle"].browse(body["result"])
        self.assertEqual(v.ff_operational_state, "unreviewed")
        self.assertFalse(v.ff_end_of_use_exempt)

    # ------------------------------------------------------------------
    # B04 -- a decision-bearing hold cannot be deleted or silently made
    #        non-blocking; authorized clearance still works and is attributable.
    # ------------------------------------------------------------------
    def test_B04_hold_history_is_protected_but_clear_works(self):
        self.authenticate("http.mgr", PW)
        self._assert_denied(self._rpc(
            "fleetflow.vehicle.hold", "unlink", [[self.hold.id]]))
        self._assert_denied(self._rpc(
            "fleetflow.vehicle.hold", "write", [[self.hold.id], {"dispatch_blocking": False}]))
        self.hold.invalidate_recordset()
        self.assertTrue(self.hold.exists())
        self.assertTrue(self.hold.dispatch_blocking)
        # An authorized, attributable clearance succeeds.
        ok = self._rpc("fleetflow.vehicle.hold", "action_clear", [[self.hold.id]],
                       {"note": "http inspected and cleared"})
        self.assertFalse(self._denied(ok), ok)
        self.hold.invalidate_recordset()
        self.assertEqual(self.hold.state, "cleared")
        self.assertEqual(self.hold.cleared_by, self.manager)

    # ------------------------------------------------------------------
    # B05 -- a REAL linked future-effective renewal (via action_supersede):
    #        verifying next month's renewal does not drop today's coverage; the
    #        renewal covers only its own interval; attribution is preserved.
    # ------------------------------------------------------------------
    def _readiness(self, days_ahead):
        day = date.today() + timedelta(days=days_ahead)
        start = datetime.combine(day, time(8, 0)).strftime("%Y-%m-%d %H:%M:%S")
        end = datetime.combine(day, time(18, 0)).strftime("%Y-%m-%d %H:%M:%S")
        body = self._rpc("fleetflow.readiness", "evaluate_readiness",
                         [self.company.id, self.vehicle.id, self.driver.id, "chauffeur",
                          [["uber", "UberX"]], start, end], {"city": "Dubai"})
        return self._assert_ok(body)

    def test_B05_future_effective_linked_renewal_preserves_coverage(self):
        self.authenticate("http.comp", PW)
        nm_start = date.today() + timedelta(days=31)
        # Drive the ACTUAL supersede workflow over the API; it returns the id.
        renewal_id = self._assert_ok(self._rpc(
            "fleetflow.credential", "action_supersede", [[self.reg.id], {
                "name": "reg-http-renewal",
                "date_start": nm_start.isoformat(),
                "date_end": (nm_start + timedelta(days=365)).isoformat()}]))
        self.assertIsInstance(renewal_id, int)
        self.reg.invalidate_recordset()
        self.assertEqual(self.reg.state, "verified")   # not superseded yet
        original_verifier = self.reg.verified_by
        # Readiness today is Ready (predecessor covers) BEFORE the renewal exists.
        self.assertEqual(self._readiness(1)["status"], "ready")
        # Verify next month's renewal TODAY.
        self._assert_ok(self._rpc("fleetflow.credential", "action_verify", [[renewal_id]]))
        self.reg.invalidate_recordset()
        # Predecessor is now marked superseded WITH attribution preserved...
        self.assertEqual(self.reg.state, "superseded")
        self.assertEqual(self.reg.superseded_by_id.id, renewal_id)
        self.assertTrue(self.reg.replaced_on)
        self.assertEqual(self.reg.verified_by, original_verifier)  # unchanged
        # ...yet today is STILL Ready (predecessor's effective interval), and a
        # shift inside the renewal window is Ready via the renewal.
        self.assertEqual(self._readiness(1)["status"], "ready")
        self.assertEqual(self._readiness(40)["status"], "ready")

    # ------------------------------------------------------------------
    # B06 -- an own upload links; a foreign/bound file is rejected unchanged.
    # ------------------------------------------------------------------
    def test_B06_own_upload_links_foreign_rejected(self):
        self.authenticate("http.comp", PW)
        own_id = self._assert_ok(self._rpc("ir.attachment", "create", [{
            "name": "own.pdf", "datas": base64.b64encode(PDF).decode()}]))
        self._assert_ok(self._rpc("fleetflow.credential", "create", [{
            "name": "own-linked", "doc_kind": "professional_permit",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": own_id}]))
        att = self.env["ir.attachment"].browse(own_id)
        att.invalidate_recordset()
        self.assertEqual(att.res_model, "fleetflow.credential")
        self.assertFalse(att.public)
        # A file already bound to another record is refused; it stays unchanged.
        before = (self.foreign_att.res_model, self.foreign_att.res_id)
        self._assert_denied(self._rpc("fleetflow.credential", "create", [{
            "name": "steal", "doc_kind": "professional_permit",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": self.foreign_att.id}]))
        self.foreign_att.invalidate_recordset()
        self.assertEqual((self.foreign_att.res_model, self.foreign_att.res_id), before)

    # ------------------------------------------------------------------
    # B07 -- a verified source cannot be replaced/published via generic
    #        attachment endpoints.
    # ------------------------------------------------------------------
    def test_B07_verified_source_immutable_over_rpc(self):
        self.authenticate("http.comp", PW)
        for vals in ({"public": True}, {"datas": base64.b64encode(b"%PDF-1.4 tampered").decode()},
                     {"res_model": "res.partner"}):
            self._assert_denied(self._rpc(
                "ir.attachment", "write", [[self.evidence_att.id], vals]))
        self._assert_denied(self._rpc(
            "ir.attachment", "unlink", [[self.evidence_att.id]]))
        self.evidence_att.invalidate_recordset()
        self.assertFalse(self.evidence_att.public)
        self.assertEqual(self.evidence_att.res_model, "fleetflow.credential")

    # ------------------------------------------------------------------
    # B08 -- restricted content is not served to dispatcher/driver/other-company
    #        sessions through /web/content; the owning reviewer gets it, and the
    #        non-sensitive metadata stays readable.
    # ------------------------------------------------------------------
    def _get_content(self, att_id):
        return self.url_open("/web/content/%s" % att_id, timeout=30)

    def test_B08_binary_download_is_role_and_company_scoped(self):
        url_id = self.evidence_att.id
        for login in ("http.disp", "http.ocomp"):
            self.authenticate(login, PW)
            resp = self._get_content(url_id)
            self.assertFalse(resp.status_code == 200 and PDF in resp.content,
                             "%s must not receive the evidence bytes" % login)
        # The owning-company compliance reviewer does receive the file...
        self.authenticate("http.comp", PW)
        ok = self._get_content(url_id)
        self.assertEqual(ok.status_code, 200)
        self.assertIn(PDF, ok.content)
        # ...and a dispatcher can still read the non-sensitive metadata.
        self.authenticate("http.disp", PW)
        self._assert_ok(self._rpc(
            "fleetflow.credential", "read", [[self.lic.id], ["doc_kind", "state"]]))

    # ------------------------------------------------------------------
    # B09 -- public / access-token variants cannot bypass the private policy.
    # ------------------------------------------------------------------
    def test_B09_public_and_token_variants_are_forbidden(self):
        # Unauthenticated, and with a guessed access token: no protected bytes.
        self.url_open("/web/session/logout", timeout=30)
        for url in ("/web/content/%s" % self.evidence_att.id,
                    "/web/content/%s?access_token=deadbeefdeadbeef" % self.evidence_att.id):
            resp = self.url_open(url, timeout=30)
            self.assertNotIn(PDF, resp.content, "no protected bytes for %s" % url)

    # ------------------------------------------------------------------
    # B10 -- allowed actions still work and unrelated attachments are intact.
    # ------------------------------------------------------------------
    def test_B10_allowed_actions_still_work(self):
        # Compliance can verify a fresh draft credential.
        self.authenticate("http.comp", PW)
        draft_id = self._assert_ok(self._rpc("fleetflow.credential", "create", [{
            "name": "b10-draft", "doc_kind": "inspection",
            "company_id": self.company.id, "vehicle_id": self.vehicle.id}]))
        self._assert_ok(self._rpc("fleetflow.credential", "action_verify", [[draft_id]]))
        # A dispatcher can still create and read an ordinary (non-evidence)
        # attachment: the guard is scoped to credential files only.
        self.authenticate("http.disp", PW)
        att_id = self._assert_ok(self._rpc("ir.attachment", "create", [{
            "name": "note.txt", "datas": base64.b64encode(b"hello").decode()}]))
        self._assert_ok(self._rpc("ir.attachment", "read", [[att_id], ["name"]]))

    # ------------------------------------------------------------------
    # B11 -- rejecting/revoking evidence keeps its once-approved source frozen
    #        and preserves the original verification attribution (E02).
    # ------------------------------------------------------------------
    def test_B11_revoked_source_stays_immutable_over_rpc(self):
        self.authenticate("http.comp", PW)
        att_id = self._assert_ok(self._rpc("ir.attachment", "create", [{
            "name": "rev.pdf", "datas": base64.b64encode(PDF).decode()}]))
        cred_id = self._assert_ok(self._rpc("fleetflow.credential", "create", [{
            "name": "rev", "doc_kind": "driver_licence",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": att_id}]))
        self._assert_ok(self._rpc("fleetflow.credential", "action_verify", [[cred_id]]))
        self._assert_ok(self._rpc("fleetflow.credential", "action_reject", [[cred_id]],
                                  {"reason": "revoked over http"}))
        cred = self.env["fleetflow.credential"].browse(cred_id)
        cred.invalidate_recordset()
        self.assertEqual(cred.state, "rejected")
        self.assertTrue(cred.ever_verified)
        self.assertTrue(cred.verified_by)        # original verifier retained
        self.assertTrue(cred.revoked_by)
        # The once-approved source is still frozen after revocation.
        for vals in ({"public": True},
                     {"datas": base64.b64encode(b"%PDF-1.4 tampered\n%%EOF").decode()}):
            self._assert_denied(self._rpc("ir.attachment", "write", [[att_id], vals]))
        self._assert_denied(self._rpc("ir.attachment", "unlink", [[att_id]]))

    # ------------------------------------------------------------------
    # B12 -- a file changed after linking is re-validated at verification (E05).
    # ------------------------------------------------------------------
    def test_B12_file_changed_after_link_fails_verification(self):
        self.authenticate("http.comp", PW)
        att_id = self._assert_ok(self._rpc("ir.attachment", "create", [{
            "name": "ok.pdf", "datas": base64.b64encode(PDF).decode()}]))
        cred_id = self._assert_ok(self._rpc("fleetflow.credential", "create", [{
            "name": "changed", "doc_kind": "driver_licence",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": att_id}]))
        # The draft's file is swapped for a malformed one (allowed while draft)...
        self._assert_ok(self._rpc("ir.attachment", "write", [[att_id], {
            "datas": base64.b64encode(b"%PDF-1.4 no eof marker").decode()}]))
        # ...verification re-validates the CURRENT bytes and refuses.
        self._assert_denied(self._rpc("fleetflow.credential", "action_verify", [[cred_id]]))
        cred = self.env["fleetflow.credential"].browse(cred_id)
        cred.invalidate_recordset()
        self.assertNotEqual(cred.state, "verified")

    # ------------------------------------------------------------------
    # B13 -- a real access token issued BEFORE binding is voided by binding, and
    #        a protected source cannot regain a usable token (E06 lifecycle).
    # ------------------------------------------------------------------
    def test_B13_pre_binding_token_is_voided_by_binding(self):
        self.authenticate("http.comp", PW)
        att_id = self._assert_ok(self._rpc("ir.attachment", "create", [{
            "name": "tok.pdf", "datas": base64.b64encode(PDF).decode()}]))
        tokens = self._assert_ok(self._rpc(
            "ir.attachment", "generate_access_token", [[att_id]]))
        old_token = tokens[0]
        # Bind the file to a credential (this privatises it and drops the token).
        self._assert_ok(self._rpc("fleetflow.credential", "create", [{
            "name": "tok-cred", "doc_kind": "driver_licence",
            "company_id": self.company.id, "driver_id": self.driver.id,
            "attachment_id": att_id}]))
        # The pre-binding token no longer serves the file, even unauthenticated.
        self.url_open("/web/session/logout", timeout=30)
        resp = self.url_open("/web/content/%s?access_token=%s" % (att_id, old_token), timeout=30)
        self.assertNotIn(PDF, resp.content)

    # ------------------------------------------------------------------
    # B14 -- a reviewer allowed in BOTH internal companies cannot transfer an
    #        existing approval between them (E03).
    # ------------------------------------------------------------------
    def test_B14_two_company_reviewer_cannot_transfer_approval(self):
        self.authenticate("http.twoco", PW)
        self._assert_denied(self._rpc("fleetflow.channel.enrolment", "write",
                                      [[self.enr_d.id], {"company_id": self.other_company.id}]))
        self.enr_d.invalidate_recordset()
        self.assertEqual(self.enr_d.company_id, self.company)

    # ------------------------------------------------------------------
    # B15 -- default_state context cannot manufacture an approved enrolment (E04).
    # ------------------------------------------------------------------
    def test_B15_default_state_context_cannot_forge_approval(self):
        self.authenticate("http.disp", PW)
        for st in ("approved", "suspended", "rejected"):
            enr_id = self._assert_ok(self._rpc(
                "fleetflow.channel.enrolment", "create",
                [{"company_id": self.company.id, "channel": "careem",
                  "product": "B15-%s" % st, "driver_id": self.driver.id}],
                {"context": {"default_state": st}}))
            enr = self.env["fleetflow.channel.enrolment"].browse(enr_id)
            enr.invalidate_recordset()
            self.assertEqual(enr.state, "pending")
            self.assertFalse(enr.verified_as_of)
