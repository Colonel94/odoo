from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

CHECKS = ('check_brakes', 'check_tyres', 'check_lights', 'check_leaks', 'check_road_test')


@tagged('post_install', '-at_install')
class TestFleetFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'FleetFlow other test company'})

        def make_user(login, role, company):
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'company_id': company.id,
                'company_ids': [(6, 0, company.ids)],
                'groups_id': [(6, 0, [cls.env.ref('fleetflow.group_' + role).id])],
            })

        cls.manager = make_user('ff.test.manager', 'manager', cls.company)
        cls.dispatcher = make_user('ff.test.dispatcher', 'dispatcher', cls.company)
        cls.technician = make_user('ff.test.technician', 'technician', cls.company)
        cls.second_technician = make_user('ff.test.second', 'technician', cls.company)
        cls.other_technician = make_user('ff.test.other', 'technician', cls.other_company)
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'FleetFlow test brand'})
        model = cls.env['fleet.vehicle.model'].create({'name': 'Test vehicle', 'brand_id': brand.id})
        cls.vehicle = cls.env['fleet.vehicle'].create({'model_id': model.id, 'license_plate': 'FF-TEST-1', 'company_id': cls.company.id})
        cls.other_vehicle = cls.env['fleet.vehicle'].with_company(cls.other_company).create({'model_id': model.id, 'license_plate': 'FF-TEST-2', 'company_id': cls.other_company.id})
        cls.Order = cls.env['fleetflow.order']

    def new_order(self, **extra):
        vals = dict(title='Test service', vehicle_id=self.vehicle.id, company_id=self.company.id,
                    assignee_id=self.technician.id, scheduled_at=fields.Datetime.now(),
                    due_at=fields.Datetime.now() + timedelta(days=1), estimated_cost=100,
                    estimate_notes='Inspection and workshop labour')
        vals.update(extra)
        return self.Order.with_user(self.manager).create(vals)

    def in_progress(self):
        order = self.new_order()
        order.action_approve()
        order.with_user(self.technician).action_start()
        return order

    def ready_for_review(self):
        order = self.in_progress()
        order.with_user(self.technician).write(dict(diagnosis='Loose connector', repair_notes='Connector secured and tested', actual_cost=75, **{key: True for key in CHECKS}))
        order.with_user(self.technician).action_submit_review()
        return order

    def test_complete_lifecycle_and_audit(self):
        order = self.ready_for_review()
        self.assertEqual(order.stage, 'quality')
        order.action_release()
        self.assertEqual(order.stage, 'done')
        self.assertEqual(order.approved_by, self.manager)
        self.assertEqual(order.released_by, self.manager)
        self.assertTrue(order.approved_at)
        self.assertTrue(order.released_at)
        self.assertTrue(order.message_ids)

    def test_cannot_forge_state_or_history(self):
        order = self.new_order()
        for values in ({'stage': 'done'}, {'approved_by': self.manager.id}, {'name': 'FORGED'}, {'create_uid': self.technician.id}, {'company_id': self.other_company.id}):
            with self.assertRaises(AccessError):
                order.with_context(fleetflow_internal=True, skip_checks=True).write(values)
        with self.assertRaises(AccessError):
            self.new_order(stage='done')
        with self.assertRaises(AccessError):
            self.new_order(approved_at=fields.Datetime.now())
        forged = self.Order.with_user(self.manager).with_context(default_stage='done', default_released_by=self.manager.id).create({'title': 'Context injection test', 'vehicle_id': self.vehicle.id})
        self.assertEqual(forged.stage, 'intake')
        self.assertFalse(forged.released_by)

    def test_approval_requires_manager_and_dispatch(self):
        order = self.new_order(assignee_id=False, scheduled_at=False)
        with self.assertRaises(AccessError):
            order.with_user(self.dispatcher).action_approve()
        with self.assertRaises(ValidationError):
            order.action_approve()
        order.write({'assignee_id': self.technician.id, 'scheduled_at': fields.Datetime.now(), 'estimate_notes': ''})
        with self.assertRaises(ValidationError):
            order.action_approve()
        self.assertEqual(order.stage, 'intake')

    def test_technician_cannot_change_planning_or_create(self):
        order = self.new_order()
        with self.assertRaises(AccessError):
            order.with_user(self.technician).write({'estimated_cost': 500})
        with self.assertRaises(AccessError):
            self.Order.with_user(self.technician).create({'title': 'Denied', 'vehicle_id': self.vehicle.id})
        self.assertFalse(order.with_user(self.technician).can_plan)
        self.assertTrue(order.with_user(self.dispatcher).can_plan)

    def test_unassigned_technician_cannot_read_or_transition(self):
        order = self.new_order()
        with self.assertRaises(AccessError):
            order.with_user(self.second_technician).read(['title'])
        order.action_approve()
        with self.assertRaises(AccessError):
            order.with_user(self.second_technician).action_start()
        self.assertEqual(order.stage, 'approved')

    def test_dashboard_respects_assignment(self):
        owned = self.new_order()
        hidden = self.new_order(assignee_id=self.second_technician.id)
        data = self.Order.with_user(self.technician).get_workspace_data()
        ids = [item['id'] for item in data['orders']]
        self.assertIn(owned.id, ids)
        self.assertNotIn(hidden.id, ids)
        self.assertEqual(data['open'], 1)
        self.assertFalse(data['can_create'])
        self.assertFalse(data['can_manage'])

    def test_company_isolation(self):
        other = self.Order.with_company(self.other_company).create({'title': 'Other company job', 'company_id': self.other_company.id, 'vehicle_id': self.other_vehicle.id, 'assignee_id': self.other_technician.id})
        with self.assertRaises(AccessError):
            other.with_user(self.manager).read(['title'])
        # A vehicle from another company must be rejected. Odoo 16.0's custom
        # assertRaises does not accept a tuple of exception types, so assert
        # manually; the rejection surfaces as a company-incompatibility
        # UserError or a ValidationError depending on which guard fires first.
        try:
            with self.cr.savepoint():
                self.new_order(vehicle_id=self.other_vehicle.id)
            self.fail('A work order must not accept a vehicle from another company.')
        except (AccessError, UserError, ValidationError):
            pass
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.new_order(company_id=self.other_company.id, vehicle_id=self.other_vehicle.id)
        data = self.Order.with_user(self.manager).get_workspace_data()
        self.assertNotIn(other.id, [row['id'] for row in data['orders']])

    def test_approved_scope_and_dispatch_required(self):
        order = self.new_order()
        order.action_approve()
        for values in ({'estimated_cost': 200}, {'vehicle_id': self.other_vehicle.id}, {'title': 'Changed scope'}):
            with self.assertRaises(UserError):
                order.write(values)
        with self.assertRaises(ValidationError):
            order.write({'assignee_id': False})
        order.write({'assignee_id': self.second_technician.id})
        self.assertEqual(order.assignee_id, self.second_technician)

    def test_inspection_and_rework_gates(self):
        order = self.in_progress()
        with self.assertRaises(ValidationError):
            order.with_user(self.technician).action_submit_review()
        order.with_user(self.technician).write(dict(diagnosis='Diagnosis', repair_notes='Repair', **{key: True for key in CHECKS}))
        order.with_user(self.technician).action_submit_review()
        with self.assertRaises(UserError):
            order.write({'repair_notes': 'Changed after review'})
        with self.assertRaises(AccessError):
            order.with_user(self.technician).action_release()
        with self.assertRaises(ValidationError):
            order.action_rework()
        order.write({'decision_notes': 'Repeat inspection with the vehicle under load'})
        order.action_rework()
        self.assertEqual(order.stage, 'in_progress')
        self.assertFalse(any(order[key] for key in CHECKS))

    def test_released_history_is_immutable(self):
        order = self.ready_for_review()
        order.action_release()
        with self.assertRaises(UserError):
            order.write({'decision_notes': 'Rewrite closed history'})
        with self.assertRaises(UserError):
            order.unlink()
        with self.assertRaises(UserError):
            order.action_release()
        self.assertEqual(order.stage, 'done')

    def test_cancellation_requires_reason_and_retains_history(self):
        order = self.new_order()
        with self.assertRaises(ValidationError):
            order.action_cancel()
        order.write({'decision_notes': 'Duplicate request'})
        order.action_cancel()
        self.assertEqual(order.stage, 'cancelled')
        with self.assertRaises(UserError):
            order.unlink()
        with self.assertRaises(UserError):
            order.action_start()

    def test_valid_costs_and_dates(self):
        for cost in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.new_order(estimated_cost=cost)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.new_order(due_at=fields.Datetime.now() - timedelta(days=1))
        order = self.in_progress()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            order.write({'actual_cost': -1})

    def test_overdue_matches_open_records_only(self):
        order = self.new_order(scheduled_at=fields.Datetime.now() - timedelta(days=2), due_at=fields.Datetime.now() - timedelta(days=1))
        self.assertTrue(order.is_overdue)
        self.assertEqual(self.Order.with_user(self.manager).get_workspace_data()['overdue'], 1)
        order.write({'decision_notes': 'Duplicate request'})
        order.action_cancel()
        self.assertFalse(order.is_overdue)
        self.assertEqual(self.Order.with_user(self.manager).get_workspace_data()['overdue'], 0)

    def test_ineligible_technician_and_inactive_vehicle(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.new_order(assignee_id=self.other_technician.id)
        self.vehicle.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.new_order()
