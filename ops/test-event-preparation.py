#!/usr/bin/env python3
"""Generate dummy CSV and verify event setup on a new local DB and temporary HTTP port."""
import argparse
from contextlib import redirect_stdout
import csv
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.app import Application, Server
from server.catalog import PRODUCTS, REWARD_PRODUCT_IDS

HEADERS = ['이름', '연락처', '휘낭시에(플레인)', '휘낭시에(카라멜)', '휘낭시에(초코)',
           '휘낭시에(무화과)', '다쿠아즈(레몬)', '다쿠아즈(얼그레이)', '보늬밤 마들렌',
           '로투스 브라우니 치즈케이크', '글레이즈드 도넛', '에그타르트', '치즈타르트']
DUMMY_ROWS = [
    ['김나나', '', 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ['이테스트', '010-0000-0002', 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ['박테스트', '010-0000-0003', 0, 0, 0, 0, 2, 2, 0, 0, 0, 0, 0],
    ['김나나', '', 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0],
]


def run(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix='run-', dir=output_dir)).resolve()
    database, csv_file = directory / 'test.sqlite3', directory / 'preorders-dummy.csv'
    with csv_file.open('w', encoding='utf-8-sig', newline='') as handle:
        csv.writer(handle).writerows([HEADERS, *DUMMY_ROWS])
    password = 'local-event-preview'
    os.environ.update(DB_PATH=str(database), DATABASE_URL='', APP_ENV='development',
                      DEMO_SEED='0', STAFF_PASSWORD=password, ALLOWED_ORIGINS='')
    app = Application()
    with app.db.transaction(write=True) as tx:
        tx.execute("INSERT INTO schedule(name,time,role,event_date) VALUES('테스트 담당','10:00-11:00','판매','2026-11-16')")
        tx.execute('UPDATE products SET stock=9')
        tx.execute("INSERT INTO memos(content,author,created_at) VALUES('지워질 테스트 메모','테스트','2026-11-15')")
    app.handle('POST', '/api/auth/register', {}, {'name': '초기화 전 테스트', 'phone': '01000000099', 'pin': '1234'}, None)
    expected_prices = [(p[0], p[3]) for p in PRODUCTS]

    def command(script, *args, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / 'ops' / script), *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode != expected:
            raise RuntimeError(f'{script} failed ({result.returncode}): {result.stderr}')
        return json.loads(result.stdout) if result.stdout.strip() else None

    preview = command('reset-db.py', '--event', '--check')
    assert preview['delete']['users'] == 1
    reset = command('reset-db.py', '--event', '--yes')
    with sqlite3.connect(database) as cx:
        assert cx.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
        assert cx.execute('SELECT SUM(stock+preorder_stock+reward_stock) FROM products').fetchone()[0] == 0
        assert cx.execute('SELECT name,time,role,event_date FROM schedule').fetchall() == [('테스트 담당', '10:00-11:00', '판매', '2026-11-16')]
        assert cx.execute('SELECT id,price FROM products ORDER BY id').fetchall() == expected_prices
    shortage = command('import-preorders.py', csv_file, expected=2)
    assert not shortage['ready'] and not shortage['applied']

    server = Server(('127.0.0.1', 0), Application())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'

    def api(path, body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(base + path, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    try:
        staff = api('/api/staff/login', {'name': '테스트 담당', 'password': password})['token']
        # Use exactly the inventory API called by the online admin dashboard.
        for product_id in REWARD_PRODUCT_IDS:
            api('/api/staff/inventory', {'product_id': product_id, 'bucket': 'stock', 'delta': 20,
                                       'reason': '로컬 초기 재고 입력 테스트', 'request_id': uuid.uuid4().hex}, staff)
        ready = command('import-preorders.py', csv_file)
        assert ready['ready'] and not ready['applied'] and ready['quantity'] == 13
        imported = command('import-preorders.py', csv_file, '--apply')
        assert imported['applied'] and imported['reservations'] == 4 and imported['total'] == 45600
        with sqlite3.connect(database) as cx:
            assert cx.execute('SELECT SUM(preorder_stock) FROM products').fetchone()[0] == 13
            assert cx.execute('SELECT SUM(stock) FROM products').fetchone()[0] == 207
            assert cx.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
            assert cx.execute('SELECT COUNT(*) FROM users WHERE role=\'buyer\'').fetchone()[0] == 0
        command('import-preorders.py', csv_file, '--apply', expected=1)
        with sqlite3.connect(database) as cx:
            assert cx.execute('SELECT SUM(preorder_stock) FROM products').fetchone()[0] == 13
        tiers = []
        for index, row in enumerate(DUMMY_ROWS, 1):
            buyer = api('/api/auth/register', {'name': row[0], 'phone': f'010-0000-{index:04}', 'pin': '1234'})
            token = buyer['token']
            query = urllib.parse.urlencode({'name': row[0], 'phone': row[1]})
            lookup = api('/api/preorders/lookup?' + query, token=token)
            if not row[1]:
                assert lookup['reservation'] is None and len(lookup['reservations']) == 2
            reservation = next(r for r in lookup['reservations'] if r['id'] == index)
            order = api(f"/api/preorders/{reservation['id']}/claim", {'request_id': uuid.uuid4().hex}, token)['order']
            assert order['status'] == 'pending'
            assert api('/api/auth/me', token=token)['user']['dice_balance'] == 0
            approved = api(f"/api/staff/orders/{order['id']}/approve", {}, staff)['order']
            assert api('/api/auth/me', token=token)['user']['dice_balance'] == 1
            tiers.append(approved['dice']['kind'])
        assert tiers == ['preorder_plain', 'preorder_rainbow', 'preorder_silver', 'preorder_gold']
        with sqlite3.connect(database) as cx:
            assert cx.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not cx.execute('PRAGMA foreign_key_check').fetchall()
            assert cx.execute('SELECT SUM(preorder_stock) FROM products').fetchone()[0] == 0
            assert cx.execute('SELECT SUM(stock) FROM products').fetchone()[0] == 207
        return {'status': 'ok', 'database': str(database), 'csv': str(csv_file), 'reset_backup': reset['backup'],
                'schedule_preserved': True, 'prices_preserved': True, 'duplicate_import': 'rejected',
                'phoneless_name_matches': 2, 'automatic_assignment': False, 'staff_approval_required': True,
                'reservations_imported': 4, 'reserved_units_before_pickup': 13, 'walkin_units': 207,
                'approved_preorder_dice': tiers}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/event-preparation-tests')
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        report = run(args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
