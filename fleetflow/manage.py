"""Local FleetFlow lifecycle. Requires Python 3 and Docker Compose v2."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ENV = HERE / '.env'
KEYS = ('FLEETFLOW_POSTGRES_PASSWORD', 'FLEETFLOW_DB_PASSWORD',
        'FLEETFLOW_MASTER_PASSWORD', 'FLEETFLOW_ADMIN_PASSWORD')


def ensure_env():
    if ENV.exists():
        return
    content = ''.join(f'{key}={secrets.token_urlsafe(32)}\n' for key in KEYS)
    fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    print('Generated local secrets in fleetflow/.env. Keep this file private and backed up.')


def compose(args, project='fleetflow'):
    subprocess.run(['docker', 'compose', '--env-file', str(ENV), '-f', str(HERE / 'compose.yaml'),
                    '-p', project, *args], check=True, cwd=HERE.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'start', 'stop', 'logs', 'test', 'test-http', 'demo'])
    args = parser.parse_args()
    if not shutil.which('docker'):
        raise SystemExit('Docker is not available. Install and start Docker with Compose v2 first.')
    if not (HERE.parent / 'odoo-bin').is_file():
        raise SystemExit('Place custom_addons/ and fleetflow/ in the root of your Colonel94/odoo checkout.')
    subprocess.run(['docker', 'compose', 'version'], check=True)
    ensure_env()
    if args.command == 'init':
        compose(['up', '-d', '--wait', 'db'])
        # Installing fleetflow_operations pulls in fleetflow as a dependency.
        compose(['run', '--rm', 'web', '-i', 'fleetflow_operations', '--without-demo=all', '--stop-after-init', '--no-http'])
        compose(['run', '--rm', 'web', 'bootstrap'])
        compose(['up', '-d', '--wait', 'web'])
        print('Open http://localhost:8069. Login: admin. Password: FLEETFLOW_ADMIN_PASSWORD in fleetflow/.env.')
    elif args.command == 'start':
        compose(['up', '-d', '--wait'])
    elif args.command == 'stop':
        compose(['stop'])
    elif args.command == 'logs':
        compose(['logs', '--tail', '150', 'web'])
    elif args.command == 'demo':
        print('Adding clearly marked fictional demo records. Do not run this against a real operations database.')
        compose(['run', '--rm', 'web', 'demo'])
    elif args.command == 'test':
        # Separate project/volumes; never reset the normal development database.
        # The model suite runs with --no-http and EXCLUDES the ff_http tag (those
        # need a live HTTP server; see the test-http command).
        project = 'fleetflow-test'
        try:
            compose(['up', '-d', '--wait', 'db'], project)
            compose(['run', '--rm', 'web', '-i', 'fleetflow_operations', '--without-demo=all', '--test-enable',
                     '--test-tags', '/fleetflow,/fleetflow_operations,-ff_http', '--stop-after-init', '--no-http'], project)
        finally:
            compose(['down', '-v'], project)
    elif args.command == 'test-http':
        # Authenticated HTTP/JSON-RPC acceptance (ff_http): the HTTP server MUST be
        # on, so this run omits --no-http. Isolated project/volumes as usual.
        project = 'fleetflow-http-test'
        try:
            compose(['up', '-d', '--wait', 'db'], project)
            compose(['run', '--rm', 'web', '-i', 'fleetflow_operations', '--without-demo=all', '--test-enable',
                     '--test-tags', 'ff_http', '--stop-after-init'], project)
        finally:
            compose(['down', '-v'], project)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print('Command failed. Check Docker and the logs above; no success is assumed.', file=sys.stderr)
        raise SystemExit(error.returncode)
