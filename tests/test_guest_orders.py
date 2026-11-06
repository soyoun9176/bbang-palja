"""Accountless orders share the sales queue, stock lock and integer order IDs."""
import concurrent.futures
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import Application, APIError, now
from server.db import SCHEMA


class GuestOrderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='bbang-guest-')
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'app.db'
        env = dict(os.environ)
        env.pop('DATABASE_URL', None)
        env.update(DB_PATH=str(self.path), APP_ENV='development', DEMO_SEED='0', STAFF_PASSWORD='guest-test-password')
        settings = patch.dict(os.environ, env, clear=True)
        settings.start()
        self.addCleanup(settings.stop)
        self.app = Application()
        self.staff = self.call('/api/staff/login', {'name':'담당자', 'password':'guest-test-password'})['token']
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=5 WHERE id IN (101,102)')

    def call(self, path, body=None, token=None, method='POST'):
        return self.app.handle(method, path, {}, body or {}, 'Bearer '+token if token else None)

    def payload(self, name='빵만 구매자', quantity=1):
        return {'name':name, 'items':[{'product_id':101,'quantity':quantity}], 'request_id':uuid.uuid4().hex}

    def counts(self):
        with self.app.db.transaction() as tx:
            return {table:tx.one(f'SELECT COUNT(*) AS n FROM {table}')['n']
                    for table in ('users','sessions','orders','guest_order_access','dice_wallet')}

    def stock(self):
        with self.app.db.transaction() as tx:
            return tx.one('SELECT stock FROM products WHERE id=101')['stock']

    def transition(self, order, action):
        return self.call(f"/api/staff/orders/{order['id']}/{action}", token=self.staff)['order']

    def test_guest_holds_stock_joins_queue_and_approval_never_creates_an_account_or_dice(self):
        before = self.counts()
        body = self.payload(quantity=2)
        order = self.call('/api/guest/orders', body)['order']
        self.assertEqual((order['user_id'],order['customer_name'],order['status'],order['dice_quantity']),
                         (None,body['name'],'pending',0))
        self.assertEqual(self.stock(),3)
        dashboard = self.call('/api/staff/dashboard',token=self.staff,method='GET')
        self.assertEqual(dashboard['orders'][0]['id'],order['id'])
        self.assertEqual(dashboard['stats']['pending_orders'],1)
        self.assertEqual(dashboard['users'],[])
        self.transition(order,'approve')
        self.transition(order,'approve')
        receipt = self.call(f"/api/guest/orders/{order['id']}",token=body['request_id'],method='GET')['order']
        self.assertEqual(receipt['status'],'approved')
        self.assertEqual(self.stock(),3)
        after = self.counts()
        self.assertEqual((after['users'],after['sessions'],after['dice_wallet']),
                         (before['users'],before['sessions'],0))
        dashboard = self.call('/api/staff/dashboard',token=self.staff,method='GET')
        self.assertEqual((dashboard['stats']['revenue'],dashboard['stats']['bread_sold']),(5600,2))

    def test_cancel_restores_stock_once_and_receipt_follows_current_status(self):
        body = self.payload()
        order = self.call('/api/guest/orders',body)['order']
        self.transition(order,'cancel')
        self.transition(order,'cancel')
        self.assertEqual(self.stock(),5)
        self.assertEqual(self.call('/api/guest/orders',body)['order']['status'],'cancelled')
        with self.assertRaises(APIError) as error:self.transition(order,'approve')
        self.assertEqual(error.exception.status,409)

    def test_receipt_is_required_and_another_order_or_login_token_cannot_read_it(self):
        first, second = self.payload(), self.payload()
        order = self.call('/api/guest/orders',first)['order']
        other = self.call('/api/guest/orders',second)['order']
        self.assertEqual(other['id'],order['id']+1)
        for identity in (None,self.staff,second['request_id'],'wrong'):
            with self.subTest(identity=identity):
                with self.assertRaises(APIError) as error:
                    self.call(f"/api/guest/orders/{order['id']}",token=identity,method='GET')
                self.assertEqual(error.exception.status,404)
        for path in ('/api/orders','/api/staff/dashboard','/api/auth/me'):
            with self.assertRaises(APIError) as error:self.call(path,token=first['request_id'],method='GET')
            self.assertEqual(error.exception.status,401)
        with self.app.db.transaction() as tx:
            row = tx.one('SELECT * FROM guest_order_access WHERE order_id=?',(order['id'],))
            self.assertEqual(row['token_hash'],hashlib.sha256(first['request_id'].encode()).hexdigest())
            self.assertNotIn(first['request_id'],str(row))

    def test_retry_stock_failure_and_request_payload_conflict_are_atomic(self):
        body = self.payload(quantity=5)
        order = self.call('/api/guest/orders',body)['order']
        self.assertEqual(self.call('/api/guest/orders',body)['order']['id'],order['id'])
        with self.assertRaises(APIError) as error:self.call('/api/guest/orders',{**body,'name':'다른 사람'})
        self.assertEqual(error.exception.status,409)
        with self.assertRaises(APIError) as error:self.call('/api/guest/orders',self.payload())
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.counts()['orders'],1)
        self.assertEqual(self.counts()['guest_order_access'],1)
        self.assertEqual(self.stock(),0)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM inventory_logs')['n'],1)

    def test_guest_and_account_order_compete_for_the_same_last_unit(self):
        buyer = self.call('/api/auth/register',{'name':'회원','phone':'01011112222','pin':'1234'})
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=1 WHERE id=101')
        def submit(guest):
            try:
                body = self.payload()
                if guest:self.call('/api/guest/orders',body)
                else:self.call('/api/orders',body,buyer['token'])
                return 200
            except APIError as error:return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit,(True,False))),[200,409])
        self.assertEqual(self.stock(),0)
        self.assertEqual(self.counts()['orders'],1)

    def test_manual_guest_sale_is_immediately_approved_and_shares_order_numbering(self):
        first = self.call('/api/guest/orders',self.payload())['order']
        body = {**self.payload(),'guest':True}
        result = self.call('/api/staff/manual-sale',body,self.staff)
        self.assertEqual(self.call('/api/staff/manual-sale',body,self.staff),result)
        self.assertEqual((result['order']['id'],result['order']['status'],result['order']['user_id'],result['user']),
                         (first['id']+1,'approved',None,None))
        self.assertEqual(result['order']['dice_quantity'],0)
        self.assertEqual(self.counts()['users'],1)  # Only the staff account.
        self.assertEqual(self.stock(),3)
        for extra in ({'user_id':1},{'phone':'01011112222'},{'pin':'1234'}):
            with self.assertRaises(APIError):self.call('/api/staff/manual-sale',{**body,**extra,'request_id':uuid.uuid4().hex},self.staff)

    def test_manual_preorder_can_be_fulfilled_without_account_and_cannot_be_fulfilled_twice(self):
        self.call('/api/staff/preorders/import',{'reservations':[{'name':'예약자','phone':'01012345678',
                  'items':[{'product_id':101,'quantity':2}]}]},self.staff)
        reservation = self.call('/api/staff/preorders/lookup',{'name':'예약자','phone':'01012345678'},self.staff)['reservation']
        path = f"/api/staff/preorders/{reservation['id']}/complete"
        body = {'name':'예약자','phone':'01012345678','guest':True,'request_id':uuid.uuid4().hex}
        first = self.call(path,body,self.staff)
        repeated = self.call(path,{**body,'request_id':uuid.uuid4().hex},self.staff)
        self.assertIsNone(first['order']['user_id'])
        self.assertIsNone(first['user'])
        self.assertEqual(first['order']['dice_quantity'],0)
        self.assertTrue(repeated['already_completed'])
        self.assertEqual(repeated['order']['id'],first['order']['id'])
        self.assertEqual(self.counts()['users'],1)
        self.assertEqual(self.stock(),3)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT preorder_stock FROM products WHERE id=101')['preorder_stock'],0)

    def test_invalid_name_items_and_weak_request_id_do_not_create_records(self):
        for extra in ({'name':''},{'name':'x'*31},{'items':[]},{'items':[{'product_id':101,'quantity':0}]},{'request_id':'1'}):
            with self.subTest(extra=extra):
                with self.assertRaises(APIError):self.call('/api/guest/orders',{**self.payload(),**extra})
        self.assertEqual(self.counts()['orders'],0)
        self.assertEqual(self.stock(),5)

    def test_old_order_schema_upgrade_preserves_orders_items_sessions_and_id_sequence(self):
        old = self.path.parent/'older.db'
        schema = SCHEMA.replace(' user_id INTEGER REFERENCES users(id),\n customer_name',
                                ' user_id INTEGER NOT NULL REFERENCES users(id),\n customer_name')
        with sqlite3.connect(old) as conn:
            conn.executescript(schema)
            conn.execute("INSERT INTO users(id,name,phone,role,password_hash,score,created_at) VALUES(1,'기존 계정','010-2222-3333','buyer','hash',17,?)",(now(),))
            conn.execute("INSERT INTO products VALUES(101,'플레인 휘낭시에','바람',2800,3,0,0,'bread','financier')")
            conn.execute("INSERT INTO sessions VALUES('existing-token',1,'2999-01-01T00:00:00Z')")
            for identity in (7,11):
                conn.execute("INSERT INTO orders(id,user_id,customer_name,type,status,total,quantity,created_at) VALUES(?,1,'기존 계정','walkin','pending',2800,1,?)",(identity,now()))
            conn.execute('DELETE FROM orders WHERE id=11')
            conn.execute("INSERT INTO order_items(order_id,product_id,name,quantity,price) VALUES(7,101,'이전 메뉴명',1,2800)")
            conn.execute("INSERT INTO idempotency VALUES(1,'order','kept','fingerprint','{}',?)",(now(),))
        with patch.dict(os.environ,{'DB_PATH':str(old)}):
            app = Application()
            for _ in range(2):app.db.initialize()
            with app.db.transaction() as tx:
                self.assertEqual(tx.one('SELECT customer_name,total FROM orders WHERE id=7'),{'customer_name':'기존 계정','total':2800})
                self.assertEqual(tx.one('SELECT name FROM order_items WHERE order_id=7')['name'],'이전 메뉴명')
                self.assertEqual(tx.one('SELECT score FROM users WHERE id=1')['score'],17)
                self.assertIsNotNone(tx.one("SELECT * FROM sessions WHERE token_hash='existing-token'"))
                self.assertIsNotNone(tx.one("SELECT * FROM idempotency WHERE request_id='kept'"))
                self.assertEqual(tx.all('PRAGMA foreign_key_check'),[])
                self.assertIsNotNone(tx.one("SELECT name FROM sqlite_master WHERE name='idx_orders_user'"))
            order = app.handle('POST','/api/guest/orders',{},self.payload(),None)['order']
            self.assertEqual(order['id'],12)
            self.assertIsNone(order['user_id'])


if __name__ == '__main__':
    unittest.main()
