#!/usr/bin/env python3
"""Install only this project's services; keep credentials and DB outside Git."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request


def command(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prototype', action='store_true', help='Initialize the sample DB and start services.')
    mode.add_argument('--sync-code-only', action='store_true', help='Copy code only; preserve DB, secrets and running services.')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run with sudo on the Oracle server.')
    source = args.source.resolve()
    if not (source / 'server/app.py').is_file() or not (source / 'frontend/index.html').is_file():
        parser.error('The source directory must contain this project.')
    existing_environment = Path('/etc/bbang-palja/api.env')
    if args.prototype and existing_environment.exists():
        existing_values = dict(line.split('=', 1) for line in existing_environment.read_text().splitlines()
                               if line and not line.startswith('#'))
        if existing_values.get('DB_PATH') != '/var/lib/bbang-palja/prototype.sqlite3':
            parser.error('An event DB is configured. Prototype initialization is refused.')
    destination = Path('/opt/bbang-palja/app')
    if destination.exists() and not (destination / '.bbang-palja-managed').exists():
        parser.error('Refusing to replace an unmanaged application directory.')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / '.bbang-palja-managed').touch(mode=0o600)
    for name in ('server', 'frontend'):
        shutil.copytree(source / name, destination / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if args.sync_code_only:
        print('Code synchronized. DB and secrets preserved; services were not restarted.')
        return

    config = Path('/etc/bbang-palja')
    config.mkdir(mode=0o700, exist_ok=True)
    environment_file = config / 'api.env'
    database = Path('/var/lib/bbang-palja/prototype.sqlite3')
    if environment_file.exists():
        values = dict(line.split('=', 1) for line in environment_file.read_text().splitlines()
                      if line and not line.startswith('#'))
        if values.get('DB_PATH') != str(database):
            parser.error('An event DB is configured. Prototype initialization is refused.')
    else:
        values = {
            'APP_ENV': 'production', 'HOST': '127.0.0.1', 'PORT': '8000',
            'STAFF_PASSWORD': secrets.token_urlsafe(18), 'DEMO_SEED': '0',
            'DB_PATH': str(database), 'ALLOWED_ORIGINS': json.loads((source/'ops/pages-project.json').read_text())['production_origin'],
        }
        with environment_file.open('x') as out:
            os.chmod(environment_file, 0o600)
            out.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    if not shutil.which('cloudflared'):
        parser.error('Install the official cloudflared binary first.')
    if not database.exists():
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Seed an explicitly separate prototype DB offline. The public API then
        # runs in production mode so it never publishes the staff password hint.
        seed_environment = os.environ.copy()
        seed_environment.pop('DATABASE_URL', None)
        seed_environment.update(values, APP_ENV='development', DEMO_SEED='1',
                                PYTHONDONTWRITEBYTECODE='1')
        subprocess.run([sys.executable, '-c', 'from server.app import Application; Application()'],
                       cwd=destination, env=seed_environment, check=True)
    units = ('bbang-palja-api.service', 'bbang-palja-quick-tunnel.service')
    templates = Path(__file__).resolve().parent / 'systemd'
    for name in units:
        command('install', '-m', '0644', str(templates / name), '/etc/systemd/system/' + name)
    command('systemd-analyze', 'verify', *('/etc/systemd/system/' + name for name in units))
    command('systemctl', 'daemon-reload')
    command('systemctl', 'enable', '--now', units[0])
    deadline = time.monotonic() + 20
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            if time.monotonic() >= deadline:
                raise SystemExit('API did not become ready. Inspect its journal before retrying.')
            time.sleep(0.25)
    command('systemctl', 'enable', '--now', units[1])
    print(json.dumps({'database': str(database), 'api': 'http://127.0.0.1:8000',
                      'services': list(units), 'staffPasswordFile': str(environment_file)}))


if __name__ == '__main__':
    main()
