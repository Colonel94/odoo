import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

STAGES = [
    ('intake', 'Intake'), ('approved', 'Scheduled'),
    ('in_progress', 'In progress'), ('quality', 'Release review'),
    ('done', 'Released'), ('cancelled', 'Cancelled'),
]
TERMINAL = {'done', 'cancelled'}
CHECKS = ('check_brakes', 'check_tyres', 'check_lights', 'check_leaks', 'check_road_test')
AUDIT = {'name', 'stage', 'approved_by', 'approved_at', 'released_by', 'released_at'}
WORK = {'diagnosis', 'repair_notes', 'actual_cost', *CHECKS}
PLANNING = {'title', 'description', 'vehicle_id', 'priority', 'service_kind',
            'assignee_id', 'scheduled_at', 'due_at', 'estimated_cost', 'estimate_notes'}


class FleetFlowOrder(models.Model):
    _name = 'fleetflow.order'
    _description = 'FleetFlow work order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, due_at asc, id desc'
    _check_company_auto = True
    _rec_names_search = ['name', 'title']

    name = fields.Char(default='New', readonly=True, copy=False, index=True)
    title = fields.Char(required=True, tracking=True)
    description = fields.Text()
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, check_company=True, tracking=True, ondelete='restrict')
    priority = fields.Selection([('0', 'Low'), ('1', 'Normal'), ('2', 'High'), ('3', 'Critical')], default='1', required=True, tracking=True, index=True)
    service_kind = fields.Selection([('repair', 'Repair'), ('preventive', 'Preventive maintenance'), ('inspection', 'Inspection')], default='repair', required=True)
    stage = fields.Selection(STAGES, default='intake', required=True, readonly=True, copy=False, tracking=True, index=True, group_expand='_expand_stage')
    assignee_id = fields.Many2one('res.users', string='Technician', check_company=True, tracking=True, domain=lambda s: [('share', '=', False), ('active', '=', True), ('groups_id', 'in', s.env.ref('fleetflow.group_technician').ids)])
    scheduled_at = fields.Datetime(string='Planned start', tracking=True)
    due_at = fields.Datetime(string='Target completion', required=True, default=lambda s: fields.Datetime.now() + timedelta(days=2), tracking=True, index=True)
    estimated_cost = fields.Monetary(tracking=True, group_operator=False)
    estimate_notes = fields.Text(string='Estimate / approval rationale')
    actual_cost = fields.Monetary(copy=False, tracking=True, group_operator=False)
    diagnosis = fields.Text(copy=False, tracking=True)
    repair_notes = fields.Text(copy=False, tracking=True)
    check_brakes = fields.Boolean(string='Brakes checked', copy=False, tracking=True)
    check_tyres = fields.Boolean(string='Tyres checked', copy=False, tracking=True)
    check_lights = fields.Boolean(string='Lights checked', copy=False, tracking=True)
    check_leaks = fields.Boolean(string='Fluid leaks checked', copy=False, tracking=True)
    check_road_test = fields.Boolean(string='Road test completed', copy=False, tracking=True)
    decision_notes = fields.Text(string='Cancellation / rework reason', copy=False, tracking=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    released_by = fields.Many2one('res.users', readonly=True, copy=False)
    released_at = fields.Datetime(readonly=True, copy=False, index=True)
    is_overdue = fields.Boolean(compute='_compute_overdue')
    can_plan = fields.Boolean(compute='_compute_permissions')

    _sql_constraints = [('unique_reference', 'unique(company_id, name)', 'Work order references must be unique within a company.')]

    @api.depends_context('uid')
    def _compute_permissions(self):
        for record in self:
            record.can_plan = self._has_role('dispatcher')

    @api.model
    def _expand_stage(self, stages, domain, order):
        return [key for key, label in STAGES]

    @api.depends('due_at', 'stage')
    def _compute_overdue(self):
        now = fields.Datetime.now()
        for record in self:
            record.is_overdue = bool(record.due_at and record.due_at < now and record.stage not in TERMINAL)

    def _has_role(self, role):
        return self.env.su or self.env.user.has_group('fleetflow.group_' + role)

    def _require_role(self, role):
        if not self._has_role(role):
            raise AccessError(_('You do not have permission to perform this operation.'))

    def _lock(self):
        # Lock before checking state: a second request must see the first transition.
        self.check_access_rights('write')
        self.check_access_rule('write')
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM fleetflow_order WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset()
            self.check_access_rule('write')

    @api.constrains('title', 'company_id', 'vehicle_id', 'assignee_id', 'scheduled_at', 'due_at', 'estimated_cost', 'actual_cost')
    def _validate_order(self):
        for record in self:
            if not (record.title or '').strip():
                raise ValidationError(_('Give the work order a descriptive title.'))
            if not record.vehicle_id.active:
                raise ValidationError(_('Select an active vehicle.'))
            if record.company_id != record.vehicle_id.company_id:
                raise ValidationError(_('The vehicle and work order must belong to the same company.'))
            if record.company_id not in self.env.companies:
                raise AccessError(_('This company is not selected in your current session.'))
            if any(not math.isfinite(record[field]) or record[field] < 0 for field in ('estimated_cost', 'actual_cost')):
                raise ValidationError(_('Costs must be finite, non-negative numbers.'))
            if record.scheduled_at and record.due_at and record.scheduled_at >= record.due_at:
                raise ValidationError(_('Target completion must be after the planned start.'))
            user = record.assignee_id
            if user and (user.share or not user.active or record.company_id not in user.company_ids or not user.has_group('fleetflow.group_technician')):
                raise ValidationError(_('Assign an active FleetFlow technician with access to this company.'))

    def _validate_cost_values(self, vals):
        for key in ('estimated_cost', 'actual_cost'):
            if key in vals:
                try:
                    value = float(vals[key] or 0)
                except (TypeError, ValueError, OverflowError):
                    raise ValidationError(_('Costs must be finite, non-negative numbers.'))
                if not math.isfinite(value) or value < 0:
                    raise ValidationError(_('Costs must be finite, non-negative numbers.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._require_role('dispatcher')
        clean = []
        for source in vals_list:
            vals = dict(source)
            self._validate_cost_values(vals)
            if vals.get('stage', 'intake') != 'intake' or any(vals.get(key) for key in AUDIT - {'name', 'stage'}):
                raise AccessError(_('New work orders must start in Intake without approval history.'))
            company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
            if company not in self.env.companies:
                raise AccessError(_('Select an allowed company.'))
            vals.update(company_id=company.id, stage='intake', name=self.env['ir.sequence'].with_company(company).next_by_code('fleetflow.order') or 'New')
            # Explicit values also override untrusted default_* RPC context keys.
            vals.update({key: False for key in AUDIT - {'name', 'stage'}})
            vals.update({key: False for key in CHECKS})
            vals.update(actual_cost=0, diagnosis=False, repair_notes=False)
            clean.append(vals)
        return super().create(clean)

    def write(self, vals):
        self._validate_cost_values(vals)
        protected = AUDIT | {'company_id', 'create_uid', 'create_date', 'write_uid', 'write_date'}
        if protected.intersection(vals):
            raise AccessError(_('Workflow history and company cannot be edited directly. Use the workflow buttons.'))
        self._lock()
        dispatcher = self._has_role('dispatcher')
        for record in self:
            if record.stage in TERMINAL:
                raise UserError(_('Released and cancelled work orders are read-only.'))
            if not dispatcher:
                self._require_role('technician')
                if record.assignee_id != self.env.user or set(vals) - WORK:
                    raise AccessError(_('Technicians may update repair evidence only on their assigned work orders.'))
            if WORK.intersection(vals) and record.stage != 'in_progress':
                raise UserError(_('Repair evidence can only be edited while work is in progress.'))
            planning = PLANNING.intersection(vals)
            if planning and record.stage != 'intake':
                if record.stage != 'approved' or planning - {'assignee_id', 'scheduled_at', 'due_at'}:
                    raise UserError(_('The approved scope is locked. Cancel and create a new order to change it.'))
            if record.stage == 'approved':
                for key in ('assignee_id', 'scheduled_at', 'due_at'):
                    if key in vals and not vals[key]:
                        raise ValidationError(_('Scheduled orders must keep a technician and complete schedule.'))
        return super().write(vals)

    def unlink(self):
        self._require_role('manager')
        self._lock()
        if any(record.stage != 'intake' for record in self):
            raise UserError(_('Only unapproved intake drafts can be deleted. History is retained for all other orders.'))
        return super().unlink()

    def _transition(self, source, target, role, extra=None):
        self.ensure_one()
        self._require_role(role)
        self._lock()
        if self.stage not in source:
            raise UserError(_('This action is no longer available. Refresh the work order.'))
        # Private method; bypass our public write guard, not ORM permissions or tracking.
        return super(FleetFlowOrder, self).write(dict(extra or {}, stage=target))

    def action_approve(self):
        self.ensure_one()
        self._require_role('manager')
        self._lock()
        self._validate_order()
        if not self.assignee_id or not self.scheduled_at or not (self.estimate_notes or '').strip():
            raise ValidationError(_('Set a technician, planned start, and estimate rationale before approval.'))
        return self._transition({'intake'}, 'approved', 'manager', {'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})

    def action_start(self):
        self.ensure_one()
        self._lock()
        if not self._has_role('dispatcher') and self.assignee_id != self.env.user:
            raise AccessError(_('Only the assigned technician or a dispatcher can start this work.'))
        self._validate_order()
        return self._transition({'approved'}, 'in_progress', 'technician')

    def action_submit_review(self):
        self.ensure_one()
        self._lock()
        if not self._has_role('dispatcher') and self.assignee_id != self.env.user:
            raise AccessError(_('Only the assigned technician or a dispatcher can submit this work.'))
        if not (self.diagnosis or '').strip() or not (self.repair_notes or '').strip() or not all(self[key] for key in CHECKS):
            raise ValidationError(_('Record the diagnosis, repair notes, and every inspection check before requesting release.'))
        return self._transition({'in_progress'}, 'quality', 'technician')

    def action_release(self):
        self.ensure_one()
        self._require_role('manager')
        self._lock()
        if not all(self[key] for key in CHECKS) or not (self.repair_notes or '').strip():
            raise ValidationError(_('The inspection evidence is incomplete.'))
        return self._transition({'quality'}, 'done', 'manager', {'released_by': self.env.uid, 'released_at': fields.Datetime.now()})

    def action_rework(self):
        self.ensure_one()
        self._require_role('manager')
        self._lock()
        if not (self.decision_notes or '').strip():
            raise ValidationError(_('Record the reason for rework first.'))
        return self._transition({'quality'}, 'in_progress', 'manager', {key: False for key in CHECKS})

    def action_cancel(self):
        self.ensure_one()
        self._require_role('manager')
        self._lock()
        if not (self.decision_notes or '').strip():
            raise ValidationError(_('Record the cancellation reason first.'))
        return self._transition({'intake', 'approved', 'in_progress', 'quality'}, 'cancelled', 'manager')

    @api.model
    def get_workspace_data(self):
        self._require_role('technician')
        self.check_access_rights('read')
        # No sudo: counts and rows use exactly the caller's record rules.
        opened = [('stage', 'not in', list(TERMINAL))]
        now = fields.Datetime.now()
        stages = [{'key': key, 'label': label, 'count': self.search_count([('stage', '=', key)])} for key, label in STAGES if key not in TERMINAL]
        rows = self.search_read(opened, ['name', 'title', 'vehicle_id', 'assignee_id', 'stage', 'priority', 'due_at'], limit=8, order='priority desc, due_at asc, id desc')
        for row in rows:
            row['overdue'] = bool(row['due_at'] and fields.Datetime.to_datetime(row['due_at']) < now)
        return {
            'open': self.search_count(opened),
            'approval': stages[0]['count'],
            'overdue': self.search_count(opened + [('due_at', '<', now)]),
            'released': self.search_count([('stage', '=', 'done'), ('released_at', '>=', now - timedelta(days=7))]),
            'stages': stages, 'orders': rows,
            'can_create': self._has_role('dispatcher'),
            'can_manage': self._has_role('manager'),
            # Server-computed cutoffs so dashboard drill-through domains match the
            # counts above regardless of the browser clock. A skewed client time
            # must not change which records a metric opens.
            'reference_time': fields.Datetime.to_string(now),
            'released_since': fields.Datetime.to_string(now - timedelta(days=7)),
        }
