"""Create local evaluation users, one per FleetFlow role. Local eval only.

These are throwaway accounts for trying the role-based workflow on a disposable
local database. They are NOT the generated admin/master secrets in .env.

Safety (see OPS-1 O1.09): this helper refuses to modify a user it did not
create itself, so a login that collides with a real account is never silently
overwritten, and it only ever reassigns clearly-marked demo work orders.
"""
import json

# Marker every demo work order carries (kept in sync with seed_demo.py).
DEMO_MARKER = 'FICTIONAL DEMO ONLY'
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
    params = env['ir.config_parameter'].sudo()
    managed = set(json.loads(params.get_param('fleetflow.eval_user_ids', '[]')))
    for login, name, group_xmlid in ROLES:
        group = env.ref(group_xmlid)
        user = env['res.users'].search([('login', '=', login)], limit=1)
        if user and user.id not in managed:
            # A user with this login exists that this seeder did not create.
            # Refuse to touch it — it may be a real account.
            print('Refusing to modify existing non-seeded user %r; skipping.' % login)
            continue
        vals = {
            'name': name,
            'login': login,
            'password': PASSWORD,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'groups_id': [(4, group.id)],
            'action_id': workspace.id,
        }
        if user:
            user.write(vals)
        else:
            user = env['res.users'].create(vals)
        managed.add(user.id)
    params.set_param('fleetflow.eval_user_ids', json.dumps(sorted(managed)))
    # Give the technician a visible queue: assign a clearly-marked DEMO intake
    # order to them. Never reassign an ordinary (real) work order.
    tech = env['res.users'].search([('login', '=', 'ff_tech')], limit=1)
    demo_intake = env['fleetflow.order'].search(
        [('stage', '=', 'intake'), ('description', 'like', DEMO_MARKER + '%')], limit=1
    )
    if tech and tech.id in managed and demo_intake:
        demo_intake.assignee_id = tech.id
    print('Eval users ready: ff_manager / ff_dispatcher / ff_tech  (password: %s)' % PASSWORD)
