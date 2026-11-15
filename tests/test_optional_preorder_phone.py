"""Phoneless bookings are explicit selections, never automatic account assignments."""
import concurrent.futures
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application
from server.db import SCHEMA


class OptionalPreorderPhoneTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='cambo-phoneless-')
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'app.sqlite3'
        settings = patch.dict(os.environ, DB_PATH=str(self.path), DATABASE_URL='', APP_ENV='production',
                              DEMO_SEED='0', STAFF_PASSWORD='optional-phone-test', ALLOWED_ORIGINS='')
        settings.start()
        self.addCleanup(settings.stop)
        self.app = Application()
        self.staff = self.call('/api/staff/login', {'name': '수령 담당', 'password': 'optional-phone-test'})['token']
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=200 WHERE id=101')
        self.serial = 0

    def call(self, path, body=None, token=None, *, method='POST', query=None):
        return self.app.handle(method, path, query or {}, body or {}, 'Bearer ' + token if token else None)

    def buyer(self, name='동명이인'):
        self.serial += 1
        phone = f'010-0000-{self.serial:04}'
        return {**self.call('/api/auth/register', {'name': name, 'phone': phone, 'pin': '1234'}), 'phone': phone}

    def reserve(self, name='동명이인', quantity=2, **extra):
        self.call('/api/staff/preorders/import', {'reservations': [
            {'name': name, 'items': [{'product_id': 101, 'quantity': quantity}], **extra}]}, self.staff)
        with self.app.db.transaction() as tx:
            return tx.one('SELECT * FROM reservations ORDER BY id DESC LIMIT 1')

    def lookup(self, buyer, name='동명이인', phone=''):
        return self.call('/api/preorders/lookup', token=buyer['token'], method='GET',
                         query={'name': [name], 'phone': [phone]})

    def claim(self, booking, buyer):
        return self.call(f"/api/preorders/{booking['id']}/claim", {'request_id': uuid.uuid4().hex}, buyer['token'])['order']

    def complete(self, booking, **extra):
        return self.call(f"/api/staff/preorders/{booking['id']}/complete", {
            'name': booking['name'], 'phone': booking['phone'], 'request_id': uuid.uuid4().hex, **extra}, self.staff)

    def me(self, buyer):
        return self.call('/api/auth/me', token=buyer['token'], method='GET')['user']

    def rows(self, table):
        with self.app.db.transaction() as tx:
            return tx.all(f'SELECT * FROM {table} ORDER BY 1')

    def test_optional_contact_import_and_signup_never_assign_any_booking(self):
        first = self.reserve()
        second = self.reserve(phone='', quantity=3)
        third = self.reserve(phone=None, quantity=4)
        buyer = self.buyer()
        self.assertEqual([row['phone'] for row in self.rows('reservations')], [None] * 3)
        self.assertTrue(all(row['user_id'] is None and row['order_id'] is None for row in self.rows('reservations')))
        result = self.lookup(buyer)
        self.assertIsNone(result['reservation'])
        self.assertEqual([r['id'] for r in result['reservations']], [first['id'], second['id'], third['id']])
        self.assertEqual([r['items'][0]['quantity'] for r in result['reservations']], [2, 3, 4])
        self.assertTrue(all('phone' not in r for r in result['reservations']))
        self.assertEqual(self.rows('orders'), [])
        self.assertEqual(self.me(buyer)['dice_balance'], 0)

    def test_name_lookup_lists_all_contact_variants_without_assigning_any_booking(self):
        buyer = self.buyer()
        blank = self.reserve()
        matching_phone = self.reserve(phone=buyer['phone'])
        other_phone = self.reserve(phone='010-9999-9999')
        self.reserve(name='다른 예약자')
        expected = [blank['id'], matching_phone['id'], other_phone['id']]
        result = self.call('/api/preorders/lookup', token=buyer['token'], method='GET')
        self.assertEqual([r['id'] for r in result['reservations']], expected)
        self.assertEqual([r['id'] for r in self.lookup(buyer)['reservations']], expected)
        self.assertEqual([r['id'] for r in self.lookup(buyer, phone='010-7777-7777')['reservations']], expected)
        self.assertTrue(all('phone' not in r for r in result['reservations']))
        self.assertTrue(all(r['user_id'] is None for r in self.rows('reservations')))
        self.assertEqual(self.rows('orders'), [])
        with self.assertRaises(APIError) as error:
            self.claim(other_phone, self.buyer())
        self.assertEqual(error.exception.status, 403)

    def test_buyer_selection_only_creates_pending_order_until_staff_explicitly_approves(self):
        booking, other = self.reserve(), self.reserve(quantity=3)
        buyer = self.buyer()
        self.lookup(buyer)
        order = self.claim(booking, buyer)
        self.assertEqual(order['status'], 'pending')
        self.assertEqual(self.me(buyer)['dice_balance'], 0)
        self.assertEqual(self.rows('user_achievements'), [])
        self.assertIsNone(self.rows('reservations')[1]['user_id'])
        with self.assertRaises(APIError) as error:
            self.call(f"/api/staff/orders/{order['id']}/approve", {}, buyer['token'])
        self.assertEqual(error.exception.status, 403)
        approved = self.call(f"/api/staff/orders/{order['id']}/approve", {}, self.staff)['order']
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(self.me(buyer)['dice_balance'], 1)
        self.complete(booking, user_id=buyer['user']['id'])
        self.assertEqual(self.me(buyer)['dice_balance'], 1)
        self.assertEqual(self.rows('reservations')[1]['id'], other['id'])
        self.assertEqual(self.rows('reservations')[1]['status'], 'reserved')

    def test_two_accounts_cannot_claim_same_booking_and_cancellation_allows_correct_account(self):
        booking = self.reserve()
        buyers = [self.buyer(), self.buyer()]
        for buyer in buyers:
            self.lookup(buyer)
        def attempt(buyer):
            try:
                return self.claim(booking, buyer)
            except APIError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, buyers))
        self.assertEqual(results.count(409), 1)
        winner = next(i for i, r in enumerate(results) if isinstance(r, dict))
        order = results[winner]
        self.assertEqual(len(self.rows('orders')), 1)
        self.assertEqual(next(p for p in self.rows('products') if p['id'] == 101)['preorder_stock'], 0)
        other = buyers[1 - winner]
        with self.assertRaises(APIError) as error:
            self.complete(booking, user_id=other['user']['id'])
        self.assertEqual(error.exception.status, 409)
        self.call(f"/api/staff/orders/{order['id']}/cancel", {}, self.staff)
        self.call(f"/api/staff/orders/{order['id']}/cancel", {}, self.staff)
        self.assertEqual(next(p for p in self.rows('products') if p['id'] == 101)['preorder_stock'], 2)
        corrected = self.claim(booking, other)
        self.assertEqual(corrected['status'], 'pending')
        self.complete(booking, user_id=other['user']['id'])
        self.assertEqual(self.me(other)['dice_balance'], 1)
        self.assertEqual(self.me(buyers[winner])['dice_balance'], 0)

    def test_staff_lists_all_matches_and_explicit_id_and_account_choose_the_right_ones(self):
        first, second = self.reserve(), self.reserve(quantity=3)
        buyers = [self.buyer(), self.buyer()]
        result = self.call('/api/staff/preorders/lookup', {'name': '동명이인'}, self.staff)
        self.assertIsNone(result['reservation'])
        self.assertEqual([r['id'] for r in result['reservations']], [first['id'], second['id']])
        chosen = self.call('/api/staff/preorders/lookup', {'name': '동명이인', 'reservation_id': second['id']}, self.staff)['reservation']
        self.assertEqual(chosen['items'][0]['quantity'], 3)
        with self.assertRaises(APIError):
            self.complete(second)
        completed = self.complete(second, user_id=buyers[1]['user']['id'])
        self.assertEqual(completed['order']['user_id'], buyers[1]['user']['id'])
        self.assertEqual(self.me(buyers[0])['dice_balance'], 0)
        self.assertIsNone(self.rows('reservations')[0]['user_id'])

    def test_new_account_needs_its_own_phone_and_does_not_change_the_booking_contact(self):
        booking = self.reserve(name='예약 실명')
        for phone in (None, '', '010-invalid'):
            with self.subTest(phone=phone), self.assertRaises(APIError):
                self.complete(booking, buyer_phone=phone, pin='1234')
        self.assertEqual(len(self.rows('users')), 1)  # Staff only.
        result = self.complete(booking, buyer_phone='01012345678', pin='2345')
        self.assertEqual(next(u for u in self.rows('users') if u['id'] == result['user']['id'])['phone'], '010-1234-5678')
        self.assertIsNone(result['reservation']['phone'])
        login = self.call('/api/auth/login', {'phone': '010-1234-5678', 'pin': '2345'})
        self.assertEqual(login['user']['id'], result['user']['id'])
        self.assertEqual(login['user']['dice_balance'], 1)

    def test_existing_phone_requires_matching_pin_and_never_overwrites_account_identity(self):
        buyer = self.buyer(name='계정 닉네임')
        booking = self.reserve(name='예약 실명')
        with self.assertRaises(APIError) as error:
            self.complete(booking, buyer_phone=buyer['phone'], pin='9999')
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.rows('orders'), [])
        result = self.complete(booking, buyer_phone=buyer['phone'], pin='1234')
        self.assertEqual(result['user']['id'], buyer['user']['id'])
        self.assertEqual(result['user']['name'], '계정 닉네임')
        self.assertEqual(result['reservation']['name'], '예약 실명')
        self.assertEqual(len(self.rows('users')), 2)

    def test_failed_completion_rolls_back_new_account_and_guest_pickup_creates_no_account(self):
        booking = self.reserve()
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET preorder_stock=0 WHERE id=101')
        with self.assertRaises(APIError):
            self.complete(booking, buyer_phone='01012345678', pin='1234')
        self.assertEqual(len(self.rows('users')), 1)
        self.assertEqual(self.rows('orders'), [])
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET preorder_stock=2 WHERE id=101')
        result = self.complete(booking, guest=True)
        self.assertIsNone(result['user'])
        self.assertIsNone(result['order']['user_id'])
        self.assertEqual(result['order']['dice_quantity'], 0)
        self.assertEqual(len(self.rows('users')), 1)

    def test_manual_import_retry_key_keeps_intentional_duplicates_but_prevents_resubmission(self):
        body = {'request_id': uuid.uuid4().hex, 'reservations': [
            {'name': '동명이인', 'items': [{'product_id': 101, 'quantity': 1}]}]}
        for _ in range(2):
            self.assertEqual(self.call('/api/staff/preorders/import', body, self.staff), {'imported': 1})
        self.assertEqual(len(self.rows('reservations')), 1)
        self.call('/api/staff/preorders/import', {**body, 'request_id': uuid.uuid4().hex}, self.staff)
        self.assertEqual(len(self.rows('reservations')), 2)

    def test_fast_award_counts_each_phoneless_booking_even_with_identical_names(self):
        bookings = [self.reserve(quantity=1) for _ in range(11)]
        for index in (0, 1, 10):
            buyer = self.buyer()
            self.assertFalse(any(row['user_id'] == buyer['user']['id'] for row in self.rows('user_achievements')))
            self.complete(bookings[index], user_id=buyer['user']['id'])
            earned = [row for row in self.rows('user_achievements') if row['user_id'] == buyer['user']['id']]
            self.assertEqual(any(row['achievement_key'] == 'preorder_fast' for row in earned), index < 10)

    def test_existing_db_migration_preserves_orders_ids_references_and_custom_schema(self):
        buyer = self.buyer()
        booking = self.reserve(phone='010-1234-5678')
        self.lookup(buyer, phone='010-1234-5678')
        self.complete(booking, user_id=buyer['user']['id'])
        tables = ('reservations', 'reservation_items', 'preorder_verifications', 'orders', 'order_items',
                  'users', 'user_achievements', 'user_badges', 'user_titles')
        before = {table: self.rows(table) for table in tables}
        # Recreate the schema shipped before optional contacts; leave dependent tables intact.
        with closing(sqlite3.connect(self.path)) as cx, cx:
            cx.execute('PRAGMA foreign_keys=OFF')
            cx.execute('DROP INDEX idx_reservations_import_batch')
            ddl = SCHEMA[SCHEMA.index('CREATE TABLE IF NOT EXISTS reservations ('):].split(';', 1)[0]
            ddl = ddl.replace('IF NOT EXISTS reservations', 'legacy_reservations').replace('phone TEXT,', 'phone TEXT NOT NULL,').replace(' import_batch TEXT,\n', '')
            cx.execute(ddl)
            columns = ','.join(key for key in before['reservations'][0] if key != 'import_batch')
            cx.execute(f'INSERT INTO legacy_reservations({columns}) SELECT {columns} FROM reservations')
            cx.execute('DROP TABLE reservations')
            cx.execute('ALTER TABLE legacy_reservations RENAME TO reservations')
            cx.execute("UPDATE sqlite_sequence SET seq=200 WHERE name='reservations'")
            cx.execute('CREATE INDEX custom_reservation_name ON reservations(name)')
            cx.execute('CREATE TRIGGER custom_reservation_trigger AFTER INSERT ON reservations BEGIN SELECT 1; END')
        Application()
        Application()  # Restart is idempotent.
        self.assertEqual({table: self.rows(table) for table in tables}, before)
        with closing(sqlite3.connect(self.path)) as cx:
            self.assertEqual(cx.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(cx.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('custom_reservation_name','custom_reservation_trigger')").fetchone()[0], 2)
        new = self.reserve(phone='')
        self.assertGreater(new['id'], 200)
        self.assertIsNone(new['phone'])


if __name__ == '__main__':
    unittest.main()
