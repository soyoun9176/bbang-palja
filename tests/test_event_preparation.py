"""Event-only reset and CSV import preserve config and separate stock entry from reservations."""
import concurrent.futures
import csv
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


reset = module('event_reset', 'ops/reset-db.py')
imports = module('preorder_csv', 'ops/import-preorders.py')


class EventPreparationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='cambo-event-setup-')
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)
        self.path = self.directory / 'app.sqlite3'
        self.csv = self.directory / 'preorders.csv'
        env = {**os.environ, 'DATABASE_URL': '', 'DB_PATH': str(self.path), 'APP_ENV': 'development',
               'DEMO_SEED': '0', 'STAFF_PASSWORD': 'event-preparation-test', 'ALLOWED_ORIGINS': ''}
        settings = patch.dict(os.environ, env, clear=True)
        settings.start()
        self.addCleanup(settings.stop)
        self.app = Application()
        self.staff = self.call('/api/staff/login', {'name': '테스트 담당', 'password': 'event-preparation-test'})['token']

    def call(self, path, body=None, token=None, method='POST'):
        return self.app.handle(method, path, {}, body or {}, 'Bearer ' + token if token else None)

    def write_csv(self, rows, headers=None):
        headers = headers or ['이름', '연락처', '휘낭시에(플레인)', '휘낭시에(카라멜)', '휘낭시에(초코)', '글레이즈드 도넛']
        with self.csv.open('w', encoding='utf-8-sig', newline='') as handle:
            csv.writer(handle).writerows([headers, *rows])

    def stock(self, product_id, quantity):
        self.call('/api/staff/inventory', {'product_id': product_id, 'bucket': 'stock', 'delta': quantity,
                                         'reason': '초기 재고 테스트', 'request_id': uuid.uuid4().hex}, self.staff)

    def dump(self):
        with sqlite3.connect(self.path) as cx:
            return '\n'.join(cx.iterdump())

    def test_reset_preview_and_apply_preserve_config_and_remove_linked_operating_records(self):
        self.stock(101, 12)
        buyer = self.call('/api/auth/register', {'name': '테스트 구매자', 'phone': '01000000001', 'pin': '1234'})
        uid = buyer['user']['id']
        self.call('/api/staff/manual-sale', {'user_id': uid, 'items': [{'product_id': 101, 'quantity': 5}],
                                          'request_id': uuid.uuid4().hex}, self.staff)
        self.call('/api/staff/instagram', {'user_id': uid, 'request_id': uuid.uuid4().hex}, self.staff)
        self.call('/api/staff/preorders/import', {'reservations': [{'name': '예약 테스트', 'phone': '01000000002',
                                                                 'items': [{'product_id': 101, 'quantity': 2}]}]}, self.staff)
        with self.app.db.transaction(write=True) as tx:
            staff_id = tx.one("SELECT id FROM users WHERE role='staff'")['id']
            tx.execute("INSERT INTO schedule(name,time,role,event_date) VALUES('운영 테스트','10:00-11:00','판매','2026-11-16')")
            tx.execute("INSERT INTO memos(content,author,created_at) VALUES('테스트 메모','담당','2026-11-15')")
            tx.execute("UPDATE users SET score=15 WHERE id=?", (uid,))
            tx.execute("UPDATE event_supplies SET stock=3 WHERE key='oatmeal'")
            tx.execute("INSERT INTO settings(key,value) VALUES('event_beverage_limit_112','40')")
            tx.execute("UPDATE settings SET value='3' WHERE key='milk_stock'")
            tx.execute("INSERT INTO titles(id,name,description,style,rule,created_at,created_by) VALUES('custom','운영 칭호','설정','magic','manual','2026-11-15',?)", (staff_id,))
            prices = tx.all('SELECT id,name,price FROM products ORDER BY id')
            schedule = tx.all('SELECT * FROM schedule')
        for threshold in (5, 10, 15):
            self.call('/api/rewards/claim', {'threshold': threshold, 'request_id': uuid.uuid4().hex}, buyer['token'])
        before = self.dump()
        preview = reset.reset_event(dry_run=True)
        self.assertGreater(preview['delete']['orders'], 0)
        self.assertEqual(self.dump(), before)
        self.assertFalse((self.directory / 'backups').exists())
        result = reset.reset_event()
        with self.app.db.transaction() as tx:
            for table in reset.EVENT_RECORD_TABLES:
                self.assertEqual(tx.one(f'SELECT COUNT(*) AS n FROM {table}')['n'], 0, table)
            self.assertEqual(tx.all('SELECT id,name,price FROM products ORDER BY id'), prices)
            self.assertEqual(tx.all('SELECT * FROM schedule'), schedule)
            self.assertEqual(tx.one("SELECT value FROM settings WHERE key='event_beverage_limit_112'")['value'], '40')
            self.assertEqual(tx.one("SELECT created_by FROM titles WHERE id='custom'")['created_by'], None)
            self.assertEqual(tx.one('SELECT SUM(stock+preorder_stock+reward_stock) AS n FROM products')['n'], 0)
            self.assertEqual(tx.one('SELECT SUM(stock) AS n FROM event_supplies')['n'], 0)
        with sqlite3.connect(result['backup']) as cx:
            self.assertEqual(cx.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
            self.assertEqual(cx.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(Path(result['backup']).stat().st_mode & 0o777, 0o600)
        Application()
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM users')['n'], 0)
            self.assertEqual(tx.one('SELECT SUM(stock+preorder_stock+reward_stock) AS n FROM products')['n'], 0)
            self.assertEqual(tx.all('SELECT * FROM schedule'), schedule)

    def test_reset_failure_rolls_back_even_after_dependent_rows_were_deleted(self):
        self.stock(101, 4)
        with self.app.db.transaction(write=True) as tx:
            tx.execute("CREATE TRIGGER refuse_user_reset BEFORE DELETE ON users BEGIN SELECT RAISE(ABORT,'test failure'); END")
        before = self.dump()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test failure'):
            reset.reset_event()
        self.assertEqual(self.dump(), before)

    def test_reset_refuses_unknown_tables_and_backup_failure_without_mutating(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('CREATE TABLE future_data(id INTEGER)')
        before = self.dump()
        with self.assertRaisesRegex(RuntimeError, '구조'):
            reset.reset_event()
        self.assertEqual(self.dump(), before)
        with self.app.db.transaction(write=True) as tx:
            tx.execute('DROP TABLE future_data')
        before = self.dump()
        with patch.object(reset, 'backup_database', side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):
                reset.reset_event()
        self.assertEqual(self.dump(), before)

    def test_reset_requires_confirmation_and_rejects_postgres(self):
        before = self.dump()
        result = subprocess.run([sys.executable, str(ROOT / 'ops/reset-db.py'), '--event'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.dump(), before)
        with patch.dict(os.environ, DATABASE_URL='postgresql://unused/database'):
            with self.assertRaisesRegex(RuntimeError, 'SQLite'):
                reset.reset_event()

    def test_flat_csv_preview_and_import_use_menu_headers_existing_prices_and_file_order(self):
        for pid in (101, 102, 103, 108):
            self.stock(pid, 10)
        self.write_csv([['같은 이름', '01000000001', 1, 2, 3, 1], ['같은 이름', '010-0000-0002', 0, 1, 0, 0]])
        before = self.dump()
        preview = imports.run_import(self.csv)
        self.assertTrue(preview['ready'])
        self.assertFalse(preview['applied'])
        self.assertEqual(preview['reservations'], 2)
        self.assertEqual(preview['quantity'], 8)
        self.assertEqual(preview['total'], 22800)
        self.assertEqual(self.dump(), before)
        self.assertTrue(imports.run_import(self.csv, apply=True)['applied'])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.all('SELECT phone FROM reservations ORDER BY id'), [{'phone': '010-0000-0001'}, {'phone': '010-0000-0002'}])
            quantities = {row['id']: (row['stock'], row['preorder_stock']) for row in tx.all('SELECT * FROM products')}
            self.assertEqual(quantities[101], (9, 1))
            self.assertEqual(quantities[102], (7, 3))
            self.assertEqual(quantities[103], (7, 3))
            self.assertEqual(quantities[108], (9, 1))
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM orders')['n'], 0)
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM users WHERE role='buyer'")['n'], 0)
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM dice_wallet')['n'], 0)
        before = self.dump()
        with self.assertRaises(APIError):
            imports.run_import(self.csv, apply=True)
        self.assertEqual(self.dump(), before)

    def test_reordered_headers_blank_quantities_and_optional_empty_trailing_cells(self):
        self.write_csv([['김나나', '010-0000-0001', '2', '', ''], [], ['다른 이름', '01000000002', '0', '1']],
                       ['이름', '연락처', '휘낭시에 (초코)', '휘낭시에(카라멜)', ''])
        rows = imports.read_preorders(self.csv)
        self.assertEqual(rows[0]['items'], [{'product_id': 102, 'quantity': 2}])
        self.assertEqual(rows[1]['items'], [{'product_id': 103, 'quantity': 1}])

    def test_tools_preserve_stored_prices_without_application_startup_side_effects(self):
        self.stock(101, 4)
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET price=4321 WHERE id=101')
        self.write_csv([['김나나', '01000000001', 2]], ['이름', '연락처', '휘낭시에(플레인)'])
        self.assertEqual(imports.run_import(self.csv)['total'], 8642)
        imports.run_import(self.csv, apply=True)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT price FROM reservation_items')['price'], 4321)
        reset.reset_event()
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT price FROM products WHERE id=101')['price'], 4321)

    def test_invalid_csv_never_partially_imports_or_changes_inventory(self):
        self.stock(101, 10)
        invalid = [
            ['다른 이름', '010-0000-0002-', 1],
            ['다른 이름', '010 0000 0002', 1],
            ['다른 이름', '01000000002', -1],
            ['다른 이름', '01000000002', '1.5'],
            ['다른 이름', '01000000002', '1e2'],
            ['다른 이름', '01000000002', 101],
            ['다른 이름', '01000000002', 0],
            ['첫 이름', '010-0000-0001', 1],
            ['다른 이름', '01000000002', 1, 'unexpected'],
        ]
        for row in invalid:
            with self.subTest(row=row):
                self.write_csv([['첫 이름', '01000000001', 1], row], ['이름', '연락처', '휘낭시에(플레인)'])
                before = self.dump()
                with self.assertRaisesRegex(ValueError, 'CSV 3행'):
                    imports.run_import(self.csv, apply=True)
                self.assertEqual(self.dump(), before)

    def test_phoneless_csv_keeps_identical_people_and_rejects_reimport_in_any_row_order(self):
        self.stock(101, 20)
        self.stock(102, 10)
        rows = [['동명이인', '', 1, 2], ['동명이인', '', 1, 2], ['다른예약', '', 3, 0]]
        self.write_csv(rows, ['이름', '연락처', '휘낭시에(플레인)', '휘낭시에(초코)'])
        before = self.dump()
        self.assertEqual(imports.run_import(self.csv)['reservations'], 3)
        self.assertEqual(self.dump(), before)
        imports.run_import(self.csv, apply=True)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.all('SELECT name,phone FROM reservations ORDER BY id'), [
                {'name': '동명이인', 'phone': None}, {'name': '동명이인', 'phone': None}, {'name': '다른예약', 'phone': None}])
        before = self.dump()
        for apply in (False, True):
            with self.assertRaisesRegex(APIError, '이미 등록한 CSV'):
                imports.run_import(self.csv, apply=apply)
            self.assertEqual(self.dump(), before)
        # Reordering the sheet's rows/columns cannot silently allocate the same stock twice.
        self.write_csv([[row[3], row[0], row[2], row[1]] for row in reversed(rows)],
                       ['휘낭시에(초코)', '이름', '휘낭시에(플레인)', '연락처'])
        with self.assertRaisesRegex(APIError, '이미 등록한 CSV'):
            imports.run_import(self.csv, apply=True)
        self.assertEqual(self.dump(), before)
        reset.reset_event()
        self.staff = self.call('/api/staff/login', {'name': '테스트 담당', 'password': 'event-preparation-test'})['token']
        self.stock(101, 20)
        self.stock(102, 10)
        self.assertTrue(imports.run_import(self.csv, apply=True)['applied'])

    def test_concurrent_phoneless_csv_import_reserves_only_once(self):
        self.stock(101, 10)
        self.write_csv([['동명이인', '', 2], ['동명이인', '', 2]], ['이름', '연락처', '휘낭시에(플레인)'])
        def attempt():
            try:
                return imports.run_import(self.csv, apply=True)['applied']
            except APIError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: attempt(), range(2))), [False, True])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT stock,preorder_stock FROM products WHERE id=101'), {'stock': 6, 'preorder_stock': 4})
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM reservations')['n'], 2)

    def test_unknown_or_duplicate_menu_and_empty_csv_are_rejected(self):
        for headers in (['이름', '연락처', '알 수 없는 빵'], ['이름', '연락처', '휘낭시에(초코)', '초코 휘낭시에'], ['이름', '연락처']):
            self.write_csv([], headers)
            with self.assertRaises(ValueError):
                imports.read_preorders(self.csv)
        self.csv.write_text('')
        with self.assertRaises(ValueError):
            imports.read_preorders(self.csv)

    def test_aggregate_stock_shortage_cannot_consume_the_first_reservation(self):
        self.stock(101, 3)
        self.write_csv([['첫 이름', '01000000001', 2], ['둘째 이름', '01000000002', 2]], ['이름', '연락처', '휘낭시에(플레인)'])
        before = self.dump()
        for apply in (False, True):
            result = imports.run_import(self.csv, apply=apply)
            self.assertFalse(result['ready'])
            self.assertFalse(result['applied'])
            self.assertEqual(result['products'][0]['remaining_after'], -1)
            self.assertEqual(self.dump(), before)

    def test_concurrent_import_of_same_file_cannot_double_reserve(self):
        self.stock(101, 3)
        self.write_csv([['김나나', '01000000001', 2]], ['이름', '연락처', '휘낭시에(플레인)'])
        def attempt():
            try:
                return imports.run_import(self.csv, apply=True)['applied']
            except APIError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: attempt(), range(2))), [False, True])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT stock,preorder_stock FROM products WHERE id=101'), {'stock': 1, 'preorder_stock': 2})
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM reservations')['n'], 1)

    def test_cli_defaults_to_preview_and_env_file_does_not_leak_secrets(self):
        self.stock(101, 2)
        self.write_csv([['김나나', '01000000001', 1]], ['이름', '연락처', '휘낭시에(플레인)'])
        env_file = self.directory / 'api.env'
        env_file.write_text(f'DB_PATH={self.path}\nSTAFF_PASSWORD=secret-not-for-output\n')
        before = self.dump()
        command = [sys.executable, str(ROOT / 'ops/import-preorders.py'), str(self.csv), '--env-file', str(env_file)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['applied'])
        self.assertNotIn('secret-not-for-output', result.stdout + result.stderr)
        self.assertEqual(self.dump(), before)
        result = subprocess.run([*command, '--apply'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['applied'])
