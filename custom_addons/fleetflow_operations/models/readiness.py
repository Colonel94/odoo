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
                           channel_products, starts_at, ends_at):
        company = self._as_record("res.company", company)
        vehicle = self._as_record("fleet.vehicle", vehicle)
        driver = self._as_record("fleetflow.driver", driver) if driver else self.env["fleetflow.driver"]
        channel_products = channel_products or []

        tz = self._operator_tz(company)
        start = self._aware(starts_at, tz)
        end = self._aware(ends_at, tz)
        now = fields.Datetime.now()

        reasons = []
        if end <= start:
            reasons.append(self._reason("interval", constants.BLOCKED, "bad_interval",
                                        _("The requested end is not after the start.")))

        profile = self.env["fleetflow.operating.profile"]._match(
            company, operating_mode,
            channel_products[0][0] if channel_products else None,
            channel_products[0][1] if channel_products else None,
        )
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
                reasons.append(self._check_operating_authorization(company, operating_mode, start, end, tz))
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

        # -- Channel approvals --------------------------------------------
        if "channel_approval" in required:
            reasons += self._check_channels(company, vehicle, driver, channel_products, now, profile)

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

    def _check_operating_authorization(self, company, operating_mode, start, end, tz):
        auths = self.env["fleetflow.operating.authorization"].search([
            ("company_id", "=", company.id), ("operating_mode", "=", operating_mode),
        ])
        verified = auths.filtered(lambda a: a.state == "verified")
        # Whole-interval coverage using local-day boundaries.
        covering = verified.filtered(
            lambda a: (not a.date_start or start >= self._doc_start(a.date_start, tz))
            and (not a.date_end or end <= self._doc_end(a.date_end, tz)))
        if covering:
            return self._reason("operating_authorization", constants.READY, "permit_ok",
                                _("Operating permit valid for the interval."))
        if verified:
            return self._reason("operating_authorization", constants.BLOCKED, "permit_expired",
                                _("The operating permit does not cover the whole interval."))
        if auths:
            return self._reason("operating_authorization", constants.NEEDS_REVIEW, "permit_unverified",
                                _("Operating permit is present but not verified."))
        return self._reason("operating_authorization", constants.NEEDS_REVIEW, "permit_missing",
                            _("No operating permit on file for this activity."))

    def _check_document(self, subject_field, subject, doc_kind, start, end, tz):
        creds = self.env["fleetflow.credential"].search([
            (subject_field, "=", subject.id), ("doc_kind", "=", doc_kind),
        ])
        verified = creds.filtered(lambda c: c.state == "verified")
        covering = verified.filtered(lambda c: c._covers_interval(start, end, tz))
        if covering:
            # Warn if the covering document expires shortly after the interval.
            soonest = min(covering.mapped("date_end") or [False])
            if soonest and self._doc_end(soonest, tz) <= end + timedelta(days=WARN_WINDOW_DAYS):
                return self._reason(doc_kind, constants.WARNING, "expiring_soon",
                                    _("%s is valid but expires within %d days after the interval.")
                                    % (doc_kind, WARN_WINDOW_DAYS), ref=covering[:1])
            return self._reason(doc_kind, constants.READY, "doc_ok",
                                _("%s valid for the interval.") % doc_kind, ref=covering[:1])
        if verified:
            # Verified but not covering the whole interval => expires mid-interval.
            return self._reason(doc_kind, constants.BLOCKED, "doc_expired",
                                _("%s expires during the requested interval.") % doc_kind,
                                ref=verified[:1])
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
        # No individual end-of-use date on file: we do not invent a generic age
        # limit. If the category is unknown, applicability is unresolved.
        if vehicle.ff_official_category in (False, "unknown"):
            return self._reason("end_of_use", constants.NEEDS_REVIEW, "end_of_use_unknown",
                                _("Age applicability is unresolved (category unknown, no "
                                  "authorised end-of-use recorded)."))
        return self._reason("end_of_use", constants.READY, "end_of_use_na",
                            _("No individual end-of-use restriction recorded for this category."))

    def _check_channels(self, company, vehicle, driver, channel_products, now, profile):
        if not channel_products:
            return [self._reason("channel_approval", constants.NEEDS_REVIEW, "no_channel",
                                 _("Channel approval required but no channel/product requested."))]
        max_age = profile.channel_freshness_days if profile else 0
        out = []
        for channel, product in channel_products:
            domain = [("company_id", "=", company.id), ("channel", "=", channel),
                      ("product", "=", product),
                      "|", ("vehicle_id", "=", vehicle.id),
                      ("driver_id", "=", driver.id if driver else False)]
            enrolments = self.env["fleetflow.channel.enrolment"].search(domain)
            label = "%s/%s" % (channel, product)
            approved = enrolments.filtered(lambda e: e.state == "approved")
            if not enrolments:
                out.append(self._reason("channel_approval", constants.NEEDS_REVIEW, "channel_missing",
                                        _("No %s enrolment on file.") % label))
            elif enrolments.filtered(lambda e: e.state in ("suspended", "rejected")) and not approved:
                out.append(self._reason("channel_approval", constants.BLOCKED, "channel_suspended",
                                        _("%s enrolment is suspended/rejected.") % label))
            elif not approved:
                out.append(self._reason("channel_approval", constants.NEEDS_REVIEW, "channel_pending",
                                        _("%s enrolment is pending approval.") % label))
            elif not any(e._is_fresh(now, max_age) for e in approved):
                out.append(self._reason("channel_approval", constants.NEEDS_REVIEW, "channel_stale",
                                        _("%s approval is stale; re-verify the platform status.") % label))
            else:
                out.append(self._reason("channel_approval", constants.READY, "channel_ok",
                                        _("%s approved and fresh.") % label))
        return out

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
        name = (company.partner_id.tz if company and company.partner_id else False) \
            or self.env.user.tz or "Asia/Dubai"
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
