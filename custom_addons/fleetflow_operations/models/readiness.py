# -*- coding: utf-8 -*-
"""The readiness engine: can this vehicle+driver operate for this company, in
this mode/channel, for the WHOLE requested interval -- and if not, why?

Design rules honoured here:
- Blocked = a known-invalid requirement (expired/wrong/exceeded). Needs review =
  a mandatory requirement that is missing, unverified or ambiguous. Both forbid
  confirm/checkout. Warning = an explicitly non-blocking item (e.g. a renewal
  falling just after the interval) that may proceed only with acknowledgement.
- No published operating profile for the request => Needs review (fail closed).
  Required checks never silently vanish.
- Whole-interval evaluation with a local-day boundary; a document expiring mid
  interval blocks, a later renewal outside the interval does not.
- The result carries only non-sensitive references (doc kind, state, dates),
  never private attachment content, so it is safe to show a dispatcher.
- Runs with the caller's own record rules; no sudo.
"""
from datetime import timedelta

import pytz

from odoo import api, fields, models, _

from . import constants

WARN_WINDOW_DAYS = 7  # a required doc expiring within this window AFTER the interval warns


class FleetflowReadiness(models.AbstractModel):
    _name = "fleetflow.readiness"
    _description = "FleetFlow Readiness Service"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def evaluate_readiness(self, company, vehicle, driver, operating_mode,
                           channel_products, starts_at, ends_at, city="Dubai"):
        company = self._as_record("res.company", company)
        vehicle = self._as_record("fleet.vehicle", vehicle)
        driver = self._as_record("fleetflow.driver", driver) if driver else self.env["fleetflow.driver"]
        # Deterministic, de-duplicated products: ordering must not affect policy
        # selection or the verdict (it previously came from an unordered set).
        channel_products = sorted(set(tuple(cp) for cp in (channel_products or [])))
        city = city or "Dubai"

        tz = self._operator_tz(company)
        start = self._aware(starts_at, tz)
        end = self._aware(ends_at, tz)
        now = fields.Datetime.now()

        reasons = []
        if end <= start:
            reasons.append(self._reason("interval", constants.BLOCKED, "bad_interval",
                                        _("The requested end is not after the start.")))

        # Mode-level policy: which document/authority checks apply and WHETHER
        # channel approval is required at all. Channel coverage is then evaluated
        # per requested product below, so one product's data never stands in for
        # another product's.
        profile = self.env["fleetflow.operating.profile"]._match(
            company, operating_mode, None, None)
        if not profile:
            reasons.append(self._reason(
                "policy", constants.NEEDS_REVIEW, "no_policy",
                _("No published operating profile for %s in this company. A "
                  "compliance reviewer must publish one.") % operating_mode))
            required = set()
        else:
            required = profile.required_checks()

        # -- Asset & driver existence/authority ---------------------------
        reasons += self._check_asset(company, vehicle)
        if operating_mode == "chauffeur":
            reasons += self._check_driver(company, driver)

        # -- Active dispatch-blocking hold (always enforced) --------------
        reasons.append(self._check_hold(vehicle))

        # -- Document requirements (whole interval) -----------------------
        doc_map = [
            ("operating_authorization", None),  # handled specially below
            ("vehicle_registration", ("vehicle_id", vehicle, "vehicle_registration")),
            ("insurance", ("vehicle_id", vehicle, "insurance")),
            ("inspection", ("vehicle_id", vehicle, "inspection")),
            ("tracking_cert", ("vehicle_id", vehicle, "tracking_cert")),
            ("driver_licence", ("driver_id", driver, "driver_licence")),
            ("professional_permit", ("driver_id", driver, "professional_permit")),
        ]
        for code, spec in doc_map:
            if code not in required:
                continue
            if code == "operating_authorization":
                reasons.append(self._check_operating_authorization(
                    company, operating_mode, start, end, tz, city))
                continue
            subject_field, subject, doc_kind = spec
            if not subject:
                reasons.append(self._reason(code, constants.NEEDS_REVIEW, "no_subject",
                                            _("%s required but no subject provided.") % doc_kind))
                continue
            reasons.append(self._check_document(subject_field, subject, doc_kind, start, end, tz))

        # -- Official category evidence -----------------------------------
        if "category_evidence" in required:
            reasons.append(self._check_category(vehicle, start, end, tz))

        # -- Authorised end-of-use ----------------------------------------
        if "end_of_use" in required:
            reasons.append(self._check_end_of_use(vehicle, end, tz))

        # -- Channel approvals (per requested product, per subject) -------
        if "channel_approval" in required:
            reasons += self._check_channels(
                company, vehicle, driver, operating_mode, channel_products, now, city)

        status = constants.worst(r["status"] for r in reasons) if reasons else constants.READY
        return {
            "status": status,
            "can_confirm": status in (constants.READY, constants.WARNING),
            "requires_ack": status == constants.WARNING,
            "reasons": reasons,
            "next_actions": self._next_actions(reasons),
            "interval": {"start": fields.Datetime.to_string(self._to_utc_naive(start)),
                         "end": fields.Datetime.to_string(self._to_utc_naive(end)),
                         "tz": str(tz)},
            "evaluated_at": fields.Datetime.to_string(now),
            "profile": ({"id": profile.id, "name": profile.name, "version": profile.version,
                         "source": profile.source_ref} if profile else None),
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------
    def _check_asset(self, company, vehicle):
        out = []
        if not vehicle:
            return [self._reason("asset", constants.BLOCKED, "no_vehicle", _("No vehicle specified."))]
        if not vehicle.active:
            out.append(self._reason("asset", constants.BLOCKED, "vehicle_inactive",
                                    _("Vehicle %s is archived/retired.") % vehicle.display_name))
        if vehicle.ff_operator_company_id and vehicle.ff_operator_company_id != company:
            out.append(self._reason("asset", constants.BLOCKED, "vehicle_wrong_operator",
                                    _("Vehicle %s is operated by another company.") % vehicle.display_name))
        elif not vehicle.ff_operator_company_id:
            out.append(self._reason("asset", constants.NEEDS_REVIEW, "vehicle_no_operator",
                                    _("Vehicle %s has no reviewed operating company.") % vehicle.display_name))
        if vehicle.ff_operational_state != "reviewed":
            out.append(self._reason("asset", constants.NEEDS_REVIEW, "vehicle_unreviewed",
                                    _("Vehicle %s is operationally unreviewed.") % vehicle.display_name))
        return out or [self._reason("asset", constants.READY, "asset_ok", _("Vehicle is active and authorised."))]

    def _check_hold(self, vehicle):
        if not vehicle:
            return self._reason("hold", constants.READY, "hold_na", _("No vehicle."))
        blocking = self.env["fleetflow.vehicle.hold"].search([
            ("vehicle_id", "=", vehicle.id), ("state", "=", "active"),
            ("dispatch_blocking", "=", True)])
        if blocking:
            return self._reason("hold", constants.BLOCKED, "vehicle_on_hold",
                                _("Vehicle has %d active dispatch-blocking hold(s).") % len(blocking))
        return self._reason("hold", constants.READY, "no_hold", _("No blocking holds."))

    def _check_driver(self, company, driver):
        if not driver:
            return [self._reason("driver", constants.BLOCKED, "no_driver", _("This mode requires a driver."))]
        out = []
        if not driver.active:
            out.append(self._reason("driver", constants.BLOCKED, "driver_inactive",
                                    _("Driver %s is inactive.") % driver.name))
        if driver.company_id != company:
            out.append(self._reason("driver", constants.BLOCKED, "driver_wrong_employer",
                                    _("Driver %s is employed by another company.") % driver.name))
        if not driver.available:
            out.append(self._reason("driver", constants.BLOCKED, "driver_unavailable",
                                    _("Driver %s is marked unavailable.") % driver.name))
        return out or [self._reason("driver", constants.READY, "driver_ok", _("Driver is active and employed here."))]

    def _check_operating_authorization(self, company, operating_mode, start, end, tz, city):
        # The permit must match the operating jurisdiction (city), not just the
        # company and mode.
        auths = self.env["fleetflow.operating.authorization"].search([
            ("company_id", "=", company.id), ("operating_mode", "=", operating_mode),
            ("jurisdiction", "=", city),
        ])
        verified = auths.filtered(lambda a: a.state == "verified")
        covering = verified.filtered(lambda a: self._auth_covers(a, start, end, tz))
        if covering:
            return self._reason("operating_authorization", constants.READY, "permit_ok",
                                _("Operating permit valid for the interval and jurisdiction."))
        # A verified permit with no end date (and not a reviewed non-expiring) has
        # unknown validity -- never treated as unlimited.
        unbounded = verified.filtered(lambda a: not a.date_end and not a.open_ended)
        expired = verified - covering - unbounded
        if expired:
            return self._reason("operating_authorization", constants.BLOCKED, "permit_expired",
                                _("The operating permit does not cover the whole interval."))
        if unbounded:
            return self._reason("operating_authorization", constants.NEEDS_REVIEW, "permit_unbounded",
                                _("The operating permit has no recorded expiry; record one or a "
                                  "reviewed non-expiring status."))
        if auths:
            return self._reason("operating_authorization", constants.NEEDS_REVIEW, "permit_unverified",
                                _("Operating permit is present but not verified."))
        return self._reason("operating_authorization", constants.NEEDS_REVIEW, "permit_missing",
                            _("No operating permit on file for this activity and jurisdiction."))

    def _auth_covers(self, auth, start, end, tz):
        if not auth.date_end and not auth.open_ended:
            return False  # unknown validity
        if auth.date_start and start < self._doc_start(auth.date_start, tz):
            return False
        if auth.date_end and end > self._doc_end(auth.date_end, tz):
            return False
        return True

    def _check_document(self, subject_field, subject, doc_kind, start, end, tz):
        creds = self.env["fleetflow.credential"].search([
            (subject_field, "=", subject.id), ("doc_kind", "=", doc_kind),
        ])
        states = {c.id: c._validity(start, end, tz) for c in creds}
        covering = creds.filtered(lambda c: states[c.id] == "covers")
        if covering:
            # Warn if the covering document expires shortly after the interval.
            ends = [d for d in covering.mapped("date_end") if d]
            soonest = min(ends) if ends else False
            if soonest and self._doc_end(soonest, tz) <= end + timedelta(days=WARN_WINDOW_DAYS):
                return self._reason(doc_kind, constants.WARNING, "expiring_soon",
                                    _("%s is valid but expires within %d days after the interval.")
                                    % (doc_kind, WARN_WINDOW_DAYS), ref=covering[:1])
            return self._reason(doc_kind, constants.READY, "doc_ok",
                                _("%s valid for the interval.") % doc_kind, ref=covering[:1])
        expired = creds.filtered(lambda c: states[c.id] == "expired")
        if expired:
            # Verified but not effective for the whole interval => expired/not yet valid.
            return self._reason(doc_kind, constants.BLOCKED, "doc_expired",
                                _("%s is not valid for the whole interval (expired or not "
                                  "yet effective).") % doc_kind, ref=expired[:1])
        unknown = creds.filtered(lambda c: states[c.id] == "unknown")
        if unknown:
            # Verified but with a blank 'valid until' (not a reviewed non-expiring)
            # or an imprecise date => validity is unknown, never treated as unlimited.
            return self._reason(doc_kind, constants.NEEDS_REVIEW, "doc_validity_unknown",
                                _("%s is verified but its validity is unknown (no expiry on "
                                  "file, or an imprecise date). Record a precise expiry or a "
                                  "reviewed non-expiring status.") % doc_kind, ref=unknown[:1])
        if creds:
            return self._reason(doc_kind, constants.NEEDS_REVIEW, "doc_unverified",
                                _("%s is present but not verified.") % doc_kind, ref=creds[:1])
        return self._reason(doc_kind, constants.NEEDS_REVIEW, "doc_missing",
                            _("Required %s is missing.") % doc_kind)

    def _check_category(self, vehicle, start, end, tz):
        if vehicle.ff_official_category in (False, "unknown"):
            return self._reason("category_evidence", constants.NEEDS_REVIEW, "category_unknown",
                                _("Official vehicle category is not classified."))
        cred = self.env["fleetflow.credential"].search([
            ("vehicle_id", "=", vehicle.id), ("doc_kind", "=", "category_classification"),
            ("state", "=", "verified")], limit=1)
        if not cred:
            return self._reason("category_evidence", constants.NEEDS_REVIEW, "category_unverified",
                                _("Vehicle category is set but not backed by verified evidence."))
        return self._reason("category_evidence", constants.READY, "category_ok",
                            _("Official category classification is verified."))

    def _check_end_of_use(self, vehicle, end, tz):
        if vehicle.ff_authorized_end_of_use:
            boundary = self._doc_end(vehicle.ff_authorized_end_of_use, tz)
            if end > boundary:
                return self._reason("end_of_use", constants.BLOCKED, "end_of_use_exceeded",
                                    _("The interval exceeds the authorised end-of-use date."))
            if end > boundary - timedelta(days=WARN_WINDOW_DAYS):
                return self._reason("end_of_use", constants.WARNING, "end_of_use_near",
                                    _("The interval is close to the authorised end-of-use date."))
            return self._reason("end_of_use", constants.READY, "end_of_use_ok",
                                _("Within the authorised end-of-use date."))
        # A reviewer may record that no end-of-use restriction applies (with
        # provenance) -- that is an explicit determination, distinct from a blank.
        if vehicle.ff_end_of_use_exempt:
            return self._reason("end_of_use", constants.READY, "end_of_use_exempt",
                                _("Reviewed: no end-of-use restriction applies to this vehicle."))
        # No authorised date and no reviewed exemption: applicability is
        # unresolved. We neither invent a generic age limit nor treat the blank
        # as 'no restriction'. Fail closed.
        return self._reason("end_of_use", constants.NEEDS_REVIEW, "end_of_use_unknown",
                            _("Age applicability is unresolved: record an authorised "
                              "end-of-use date, or a reviewed exemption with provenance."))

    def _check_channels(self, company, vehicle, driver, operating_mode, channel_products, now, city):
        """Evaluate EACH requested (channel, product) independently, and within it
        EACH required subject.

        A platform product needs both the vehicle and the driver approved for a
        chauffeur shift (the vehicle alone for a driverless rental). Approval must
        match the operating city, be fresh (per the product's profile) and past no
        recheck date, and an approval on one subject never masks a suspension on
        another. Missing coverage on any required subject fails closed."""
        if not channel_products:
            return [self._reason("channel_approval", constants.NEEDS_REVIEW, "no_channel",
                                 _("Channel approval required but no channel/product requested."))]
        out = []
        for channel, product in channel_products:
            cprofile = self.env["fleetflow.operating.profile"]._match(
                company, operating_mode, channel, product)
            max_age = cprofile.channel_freshness_days if cprofile else 0
            label = "%s/%s (%s)" % (channel, product, city)
            subjects = [("vehicle_id", vehicle, _("vehicle"))]
            if operating_mode == "chauffeur":
                subjects.append(("driver_id", driver, _("driver")))
            for field, subject, subj_label in subjects:
                out.append(self._check_channel_subject(
                    company, channel, product, city, field, subject, subj_label, now, max_age, label))
        return out

    def _check_channel_subject(self, company, channel, product, city, field, subject,
                               subj_label, now, max_age, label):
        if not subject:
            return self._reason("channel_approval", constants.BLOCKED, "channel_no_subject",
                                _("%s requires a %s, but none is set.") % (label, subj_label))
        enrolments = self.env["fleetflow.channel.enrolment"].search([
            ("company_id", "=", company.id), ("channel", "=", channel),
            ("product", "=", product), ("city", "=", city), (field, "=", subject.id)])
        if not enrolments:
            return self._reason("channel_approval", constants.NEEDS_REVIEW, "channel_missing",
                                _("No %s enrolment on file for the %s.") % (label, subj_label))
        # A suspension/rejection on this subject blocks, regardless of any other
        # approved record for the same subject (no masking).
        if enrolments.filtered(lambda e: e.state in ("suspended", "rejected")):
            return self._reason("channel_approval", constants.BLOCKED, "channel_suspended",
                                _("%s enrolment is suspended/rejected for the %s.") % (label, subj_label))
        approved = enrolments.filtered(lambda e: e.state == "approved")
        if not approved:
            return self._reason("channel_approval", constants.NEEDS_REVIEW, "channel_pending",
                                _("%s enrolment is pending approval for the %s.") % (label, subj_label))
        if not any(e._is_fresh(now, max_age) and self._recheck_ok(e) for e in approved):
            return self._reason("channel_approval", constants.NEEDS_REVIEW, "channel_stale",
                                _("%s approval for the %s is stale or past its recheck date; "
                                  "re-verify the platform status.") % (label, subj_label))
        return self._reason("channel_approval", constants.READY, "channel_ok",
                            _("%s approved and fresh for the %s.") % (label, subj_label))

    @staticmethod
    def _recheck_ok(enrolment):
        return not enrolment.recheck_date or enrolment.recheck_date >= fields.Date.today()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _reason(self, check, status, code, message, ref=None):
        data = {"check": check, "status": status, "code": code, "message": message}
        if ref:
            data["evidence_ref"] = {"model": ref._name, "id": ref.id,
                                    "kind": getattr(ref, "doc_kind", False),
                                    "state": getattr(ref, "state", False),
                                    "date_end": fields.Datetime.to_string(ref.date_end) if getattr(ref, "date_end", False) else False}
        return data

    def _next_actions(self, reasons):
        actions = []
        for r in reasons:
            if r["status"] in (constants.BLOCKED, constants.NEEDS_REVIEW):
                actions.append(r["message"])
        return actions

    def _as_record(self, model, value):
        if isinstance(value, models.BaseModel):
            return value
        return self.env[model].browse(int(value)) if value else self.env[model]

    def _operator_tz(self, company):
        # Deterministic operator timezone: derived from the operating company,
        # never the requesting user's preference (two staff must read the same
        # date-only evidence identically).
        name = (company.partner_id.tz if company and company.partner_id else False) \
            or "Asia/Dubai"
        try:
            return pytz.timezone(name)
        except Exception:
            return pytz.timezone("Asia/Dubai")

    def _aware(self, value, tz):
        dt = fields.Datetime.to_datetime(value)  # naive UTC (Odoo convention)
        return pytz.utc.localize(dt).astimezone(tz)

    def _to_utc_naive(self, aware_dt):
        return aware_dt.astimezone(pytz.utc).replace(tzinfo=None)

    def _doc_start(self, day, tz):
        from datetime import datetime, time
        return tz.localize(datetime.combine(day, time.min))

    def _doc_end(self, day, tz):
        from datetime import datetime, time
        return tz.localize(datetime.combine(day + timedelta(days=1), time.min))
