"""Explicit, idempotent fictional data for local UI exploration; no new login users.

Safety (see OPS-1 O1.09): refuses to run on a database that already holds real
(non-demo) work orders unless FLEETFLOW_ALLOW_DEMO is set, so it cannot pollute
an operational database. Every record it creates is clearly marked fictional.
"""
import os
from datetime import timedelta
from odoo import fields

# Marker every demo work order carries (kept in sync with seed_users.py).
DEMO_MARKER = 'FICTIONAL DEMO ONLY'


def seed(env):
    params = env['ir.config_parameter']
    if params.get_param('fleetflow.demo_seeded'):
        print('Demo data already exists; no duplicate records added.')
        return
    real_orders = env['fleetflow.order'].search_count(
        [('description', 'not like', DEMO_MARKER + '%')]
    )
    if real_orders and not os.environ.get('FLEETFLOW_ALLOW_DEMO'):
        print(
            'Refusing to seed demo data: %d real (non-demo) work order(s) present. '
            'Run only against a disposable database, or set FLEETFLOW_ALLOW_DEMO=1 '
            'to force.' % real_orders
        )
        return
    admin = env.ref('base.user_admin')
    company = admin.company_id
    env = env(context=dict(env.context, allowed_company_ids=[company.id]))
    brand = env['fleet.vehicle.model.brand'].create({'name': 'FleetFlow Demo'})
    model = env['fleet.vehicle.model'].create({'name': 'Service Van', 'brand_id': brand.id})
    samples = [
        ('Brake vibration reported', '3', 'intake', -3),
        ('Air conditioning diagnosis', '2', 'approved', 8),
        ('Scheduled maintenance service', '1', 'in_progress', 16),
        ('Headlamp replacement check', '1', 'quality', 24),
        ('Fluid leak investigation', '2', 'in_progress', 5),
        ('Routine vehicle inspection', '0', 'done', 32),
    ]
    for index, (title, priority, target, hours) in enumerate(samples, 1):
        vehicle = env['fleet.vehicle'].create({'model_id': model.id, 'license_plate': f'DEMO-{index:03}', 'company_id': company.id, 'location': 'Fictional demo workshop'})
        now = fields.Datetime.now()
        order = env['fleetflow.order'].create({
            'title': title, 'description': 'FICTIONAL DEMO ONLY — not a real maintenance record.',
            'vehicle_id': vehicle.id, 'company_id': company.id, 'priority': priority,
            'assignee_id': admin.id, 'scheduled_at': now - timedelta(hours=6),
            'due_at': now + timedelta(hours=hours), 'estimated_cost': 250,
            'estimate_notes': 'Fictional demonstration estimate, in company currency.',
        })
        if target != 'intake':
            order.action_approve()
        if target in ('in_progress', 'quality', 'done'):
            order.action_start()
        if target in ('quality', 'done'):
            order.write(dict(diagnosis='Fictional demo diagnosis.', repair_notes='Fictional demo repair evidence.', actual_cost=220,
                             check_brakes=True, check_tyres=True, check_lights=True, check_leaks=True, check_road_test=True))
            order.action_submit_review()
        if target == 'done':
            order.action_release()
    params.set_param('fleetflow.demo_seeded', '1')
    print('Created six fictional demo work orders through the real workflow actions.')
