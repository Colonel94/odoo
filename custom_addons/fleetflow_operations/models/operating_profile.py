# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from . import constants


class FleetflowOperatingProfile(models.Model):
    """A bounded, versioned set of required checks for a mode/company/product.

    The profile selects, from a FINITE list of built-in checks, which ones are
    mandatory for a given operating mode (and optionally a channel/product). It
    never stores an executable expression. A required check cannot silently
    vanish because no profile was configured: if no PUBLISHED profile matches a
    request, readiness is Needs review (fail closed), not Ready.

    Source observations are drafts with provenance; only a compliance reviewer
    publishes a profile. Age policy is an explicit reviewed input, never a
    guessed universal limit.
    """
    _name = "fleetflow.operating.profile"
    _description = "FleetFlow Operating Profile"
    _inherit = ["mail.thread"]
    _check_company_auto = True
    _order = "operating_mode, channel, version desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True,
    )
    operating_mode = fields.Selection(constants.OPERATING_MODES, required=True)
    channel = fields.Selection(constants.CHANNELS, string="Channel (optional)")
    product = fields.Char(string="Product (optional)")
    version = fields.Integer(default=1, required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("published", "Published"), ("archived", "Archived")],
        default="draft", required=True, tracking=True, copy=False,
    )
    source_ref = fields.Char(string="Source", help="Provenance, e.g. S01/S03.")
    source_version = fields.Char()

    # Finite, built-in required checks (no expressions).
    require_operating_authorization = fields.Boolean(default=True)
    require_vehicle_registration = fields.Boolean(default=True)
    require_insurance = fields.Boolean(default=True)
    require_inspection = fields.Boolean(default=False)
    require_tracking_cert = fields.Boolean(default=False)
    require_driver_licence = fields.Boolean(default=True)
    require_professional_permit = fields.Boolean(default=True)
    require_channel_approval = fields.Boolean(default=True)
    require_category_evidence = fields.Boolean(default=False)
    enforce_end_of_use = fields.Boolean(
        default=True, string="Enforce authorised end-of-use",
        help="Block when a known authorised end-of-use is exceeded. Does not "
             "invent a generic age limit.",
    )
    channel_freshness_days = fields.Integer(
        default=30, string="Channel status freshness (days)",
        help="Maximum age of a platform status verification before it is stale.",
    )

    _sql_constraints = [
        ("mode_channel_version_company_uniq",
         "unique(company_id, operating_mode, channel, product, version)",
         "A profile with this mode/channel/product/version already exists."),
    ]

    # A published policy version is frozen: its scope and required checks are the
    # basis of confirmed decisions and cannot change under them. Corrections are
    # made by publishing a NEW version, never by editing a published one.
    _FROZEN_FIELDS = {
        "operating_mode", "channel", "product", "version",
        "require_operating_authorization", "require_vehicle_registration",
        "require_insurance", "require_inspection", "require_tracking_cert",
        "require_driver_licence", "require_professional_permit",
        "require_channel_approval", "require_category_evidence",
        "enforce_end_of_use", "channel_freshness_days",
    }

    def write(self, vals):
        if vals.get("state") == "published":
            raise AccessError(_(
                "Publish a profile through the Publish action, which archives the "
                "prior version; the published state is not set by a direct write."))
        if self._FROZEN_FIELDS & set(vals):
            for rec in self:
                if rec.state in ("published", "archived"):
                    raise UserError(_(
                        "Policy version %s is frozen (%s). Create a new version "
                        "and publish it; a published version is never edited in "
                        "place.") % (rec.name, rec.state))
        return super().write(vals)

    def _apply(self, vals):
        return super().write(vals)

    def action_publish(self):
        if not (self.env.user.has_group("fleetflow_operations.group_ops_compliance") or self.env.su):
            raise AccessError(_("Only a compliance reviewer can publish an operating profile."))
        for rec in self:
            # Supersede any currently published profile for the same key.
            others = self.search([
                ("company_id", "=", rec.company_id.id),
                ("operating_mode", "=", rec.operating_mode),
                ("channel", "=", rec.channel),
                ("product", "=", rec.product),
                ("state", "=", "published"),
                ("id", "!=", rec.id),
            ])
            others._apply({"state": "archived"})
        self._apply({"state": "published"})
        return True

    @api.model
    def _match(self, company, operating_mode, channel=None, product=None):
        """Return the best published profile for a request, or empty recordset.

        Preference: exact channel+product > channel-only > mode-only. Missing a
        published match is the caller's cue to fail closed to Needs review.
        """
        base = [("company_id", "=", company.id),
                ("operating_mode", "=", operating_mode),
                ("state", "=", "published")]
        candidates = [
            base + [("channel", "=", channel), ("product", "=", product)] if (channel and product) else None,
            base + [("channel", "=", channel), ("product", "in", (False, ""))] if channel else None,
            base + [("channel", "in", (False, ""))],
        ]
        for domain in candidates:
            if domain is None:
                continue
            found = self.search(domain, order="version desc", limit=1)
            if found:
                return found
        return self.browse()

    def required_checks(self):
        """Return the set of built-in check codes this profile mandates."""
        self.ensure_one()
        mapping = {
            "operating_authorization": self.require_operating_authorization,
            "vehicle_registration": self.require_vehicle_registration,
            "insurance": self.require_insurance,
            "inspection": self.require_inspection,
            "tracking_cert": self.require_tracking_cert,
            "driver_licence": self.require_driver_licence,
            "professional_permit": self.require_professional_permit,
            "channel_approval": self.require_channel_approval,
            "category_evidence": self.require_category_evidence,
            "end_of_use": self.enforce_end_of_use,
        }
        return {code for code, on in mapping.items() if on}
