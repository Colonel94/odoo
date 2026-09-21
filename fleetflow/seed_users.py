"""Create local evaluation users, one per FleetFlow role. Local eval only.

These are throwaway accounts for trying the role-based workflow on a disposable
local database. They are NOT the generated admin/master secrets in .env.
"""
ROLES = [
    ('ff_manager', 'FleetFlow Manager (eval)', 'fleetflow.group_manager'),
    ('ff_dispatcher', 'FleetFlow Dispatcher (eval)', 'fleetflow.group_dispatcher'),
    ('ff_tech', 'FleetFlow Technician (eval)', 'fleetflow.group_technician'),
]
PASSWORD = 'fleetflow'  # local evaluation only; not a production credential


def seed(env):
    admin = env.ref('base.user_admin')
    company = admin.company_id
    workspace = env.ref('fleetflow.action_workspace')
    for login, name, group_xmlid in ROLES:
        group = env.ref(group_xmlid)
        vals = {
            'name': name,
            'login': login,
            'password': PASSWORD,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'groups_id': [(4, group.id)],
            'action_id': workspace.id,
        }
        user = env['res.users'].search([('login', '=', login)], limit=1)
        if user:
            user.write(vals)
        else:
            user = env['res.users'].create(vals)
    # Give the technician a visible queue: assign the intake demo order to them.
    tech = env['res.users'].search([('login', '=', 'ff_tech')], limit=1)
    intake = env['fleetflow.order'].search([('stage', '=', 'intake')], limit=1)
    if tech and intake:
        intake.assignee_id = tech.id
    print('Eval users ready: ff_manager / ff_dispatcher / ff_tech  (password: %s)' % PASSWORD)
