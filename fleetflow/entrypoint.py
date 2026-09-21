"""Run FleetFlow on the container image's coherent Odoo 16 core.

The Colonel94/odoo checkout mounted at /workspace is an older 16.0 snapshot
(baseline 7d63cda1, May 2023). The odoo:16.0 image ships a newer, maintained
16.0 (16.0-2025xxxx). Odoo's `odoo.addons` namespace uses pkgutil.extend_path,
which pulls the image's bundled addons off site-packages even when core is the
old checkout -- so new addons run against old core and fail at import
(e.g. `get_public_method`). Mixing the two is not supportable.

Resolution (deployment layer only; core Odoo is not modified): run ONE coherent
Odoo -- the image's maintained 16.0 core and bundled addons -- and load the
FleetFlow addon from /workspace/custom_addons. This is also the more secure
choice, matching the README's advice to track a maintained 16.0 release.
"""
import configparser
import os
from pathlib import Path
import sys

WORKSPACE = Path('/workspace')
# The image's coherent Odoo core + bundled community addons (web, mail, fleet).
CORE_ADDONS = '/usr/lib/python3/dist-packages/odoo/addons'
CUSTOM_ADDONS = str(WORKSPACE / 'custom_addons')


def configure():
    keys = ('FLEETFLOW_DB_PASSWORD', 'FLEETFLOW_MASTER_PASSWORD', 'FLEETFLOW_ADMIN_PASSWORD')
    for key in keys:
        if not os.environ.get(key):
            raise SystemExit('Missing ' + key + '. Run the local setup utility.')
    config = configparser.ConfigParser(interpolation=None)
    config['options'] = {
        'admin_passwd': os.environ['FLEETFLOW_MASTER_PASSWORD'],
        'db_host': 'db', 'db_port': '5432', 'db_user': 'fleetflow',
        'db_password': os.environ['FLEETFLOW_DB_PASSWORD'],
        'db_name': 'fleetflow', 'dbfilter': '^fleetflow$', 'list_db': 'False',
        'addons_path': CORE_ADDONS + ',' + CUSTOM_ADDONS,
        'data_dir': '/var/lib/odoo', 'http_interface': '0.0.0.0', 'http_port': '8069',
        'proxy_mode': 'False', 'workers': '0', 'max_cron_threads': '1',
        'limit_time_cpu': '120', 'limit_time_real': '240',
    }
    path = '/tmp/fleetflow.conf'
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        config.write(stream)
    return path


def shell_task(config_path, mode):
    # seed_demo lives beside this file; make it importable without touching the
    # odoo import (which must resolve to the image's core, not the checkout).
    sys.path.insert(0, str(WORKSPACE / 'fleetflow'))
    import odoo
    from odoo import api, SUPERUSER_ID
    odoo.tools.config.parse_config(['-c', config_path, '--no-http'])
    with odoo.registry('fleetflow').cursor() as cursor:
        env = api.Environment(cursor, SUPERUSER_ID, {})
        if mode == 'bootstrap':
            admin = env.ref('base.user_admin')
            admin.write({'login': 'admin', 'password': os.environ['FLEETFLOW_ADMIN_PASSWORD'],
                         'action_id': env.ref('fleetflow.action_workspace').id})
        elif mode == 'demo':
            from seed_demo import seed
            seed(env)
        elif mode == 'users':
            from seed_users import seed as seed_users
            seed_users(env)
        cursor.commit()


def main():
    path = configure()
    args = sys.argv[1:]
    if args and args[0] in ('bootstrap', 'demo', 'users'):
        shell_task(path, args[0])
    else:
        # Run the image's Odoo console script (coherent core + bundled addons).
        os.execv(sys.executable, [sys.executable, '/usr/bin/odoo', '-c', path, *args])


if __name__ == '__main__':
    main()
