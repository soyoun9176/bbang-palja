#!/usr/bin/env python3
"""Back up the isolated prototype DB and add the event menu without refilling stock."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.catalog import PRODUCT_IDS, sync_catalog
from server.db import Database


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo on the Oracle server.')
    values = dict(line.split('=', 1) for line in Path('/etc/bbang-palja/api.env').read_text().splitlines()
                  if line and not line.startswith('#'))
    path = Path('/var/lib/bbang-palja/prototype.sqlite3')
    if values.get('DB_PATH') != str(path) or values.get('DATABASE_URL'):
        raise SystemExit('Refusing to modify an event DB or PostgreSQL database.')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'bbang-palja-api']).returncode == 0:
        raise SystemExit('Stop bbang-palja-api first; leave the Quick Tunnel running.')
    if not path.is_file():
        raise SystemExit('Prototype DB does not exist.')
    owner = path.stat()
    os.umask(0o077)
    folder = Path('/var/backups/bbang-palja')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = folder / ('prototype-before-menu-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
    source = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    os.environ.pop('DATABASE_URL', None)
    os.environ['DB_PATH'] = str(path)
    db = Database(ROOT)
    try:
        with db.transaction(write=True) as tx:
            added = sync_catalog(tx, demo=True)
    finally:
        for file in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')):
            if file.exists():
                os.chown(file, owner.st_uid, owner.st_gid)
    print(json.dumps({'backup': str(backup), 'new_menu_items': added,
                      'active_menu_items': len(PRODUCT_IDS), 'existing_stock_and_orders': 'preserved'}))


if __name__ == '__main__':
    main()
