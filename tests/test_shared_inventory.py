"""Shared sale/reward stock, squared draw weights and race guarantees."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import call, patch

from server.app import Application, APIError, merge_legacy_reward_stock
from server.db import Database

ROOT = Path(__file__).resolve().parents[1]


class SharedInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kambo-shared-stock-')
        self.addCleanup(temporary.cleanup)
        environment = dict(os.environ)
        environment.pop('DATABASE_URL', None)
        environment.update(DB_PATH=str(Path(temporary.name)/'shared.db'), APP_ENV='production',
                           DEMO_SEED='0', STAFF_PASSWORD='test-staff-password', ALLOWED_ORIGINS='')
        env_patch = patch.dict(os.environ, environment, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.app = Application()

    def request(self, method, path, body=None, token=None):
        return self.app.handle(method, path, {}, body or {}, 'Bearer '+token if token else None)

    def buyer(self, bread_stage=True):
        login = self.request('POST', '/api/auth/register',
                             {'name':'추첨'+uuid.uuid4().hex[:10], 'pin':'1234'})
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE users SET score=? WHERE id=?', (20 if bread_stage else 0,login['user']['id']))
            if bread_stage:
                for threshold,kind in [(5,'oatmeal'),(10,'milk'),(15,'sunglasses')]:
                    tx.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(?,?,?,?,?)", (login['user']['id'],threshold,kind,'선행 보상 테스트','2026-11-07'))
                tx.execute('UPDATE users SET rewards_claimed=3 WHERE id=?',(login['user']['id'],))
        return login['token']

    def stock(self, counts):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=0')
            for product_id, quantity in counts.items():
                tx.execute('UPDATE products SET stock=? WHERE id=?', (quantity, product_id))

    def product(self, product_id):
        return next(p for p in self.request('GET', '/api/products')['products'] if p['id']==product_id)

    def draw(self, token, request_id=None):
        return self.request('POST', '/api/rewards/claim',
                            {'request_id': request_id or str(uuid.uuid4())}, token)

    def test_five_milestones_persist_once_and_stop_at_thirty(self):
        self.stock({101:2,112:1})
        with self.app.db.transaction(write=True) as tx:
            tx.execute("UPDATE event_supplies SET stock=1 WHERE key='oatmeal'")
        token=self.buyer(bread_stage=False)
        user=self.request('GET','/api/auth/me',token=token)['user']
        self.assertEqual([m['threshold'] for m in self.request('GET','/api/config')['milestones']],[5,10,15,20,30])
        for level,(threshold,kind) in enumerate([(5,'oatmeal'),(10,'milk'),(15,'sunglasses'),(20,'bread'),(30,'bread')],1):
            with self.app.db.transaction(write=True) as tx:
                tx.execute('UPDATE users SET score=? WHERE id=?',(threshold-1,user['id']))
            with self.assertRaises(APIError) as error:self.draw(token)
            self.assertEqual(error.exception.status,409)
            with self.app.db.transaction(write=True) as tx:
                tx.execute('UPDATE users SET score=? WHERE id=?',(threshold,user['id']))
            identity=uuid.uuid4().hex
            result=self.draw(token,identity)
            self.assertEqual(self.draw(token,identity),result)
            self.assertEqual((result['reward']['threshold'],result['reward']['kind']),(threshold,kind))
            if kind=='milk':
                self.request('POST',f"/api/reward-requests/{result['reward']['fulfillment']['id']}/choose",{'product_id':112,'request_id':uuid.uuid4().hex},token)
            user=self.request('GET','/api/auth/me',token=token)['user']
            self.assertEqual((user['level'],user['rewards_claimed']),(level,level))
        self.assertEqual(self.product(101)['stock'],0)
        self.assertEqual(self.product(112)['stock'],0)
        self.assertEqual(user['claimed_milestones'],[5,10,15,20,30])
        self.assertTrue(user['sunglasses_unlocked'])
        with self.assertRaises(APIError) as error:self.draw(token)
        self.assertEqual(error.exception.status,409)
        self.assertEqual(len(self.request('GET','/api/rewards',token=token)['rewards']),5)

    def test_parallel_level_up_requests_cannot_spend_one_milestone_twice(self):
        self.stock({101:2})
        token = self.buyer()
        barrier = threading.Barrier(2)
        def level_up(_):
            barrier.wait(timeout=5)
            try:
                return 200,self.draw(token)
            except APIError as error:
                return error.status,None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(level_up,range(2)))
        self.assertEqual(sorted(status for status,_ in results), [200,409])
        user = self.request('GET','/api/auth/me',token=token)['user']
        self.assertEqual((user['level'],user['rewards_claimed']), (4,4))
        self.assertEqual(self.product(101)['stock'], 1)

    def test_squared_weights_have_exact_ticket_boundaries(self):
        # 2^2 tickets for A and 4^2 for B: A gets [0,3], B gets [4,19].
        for ticket, expected in [(0,101),(3,101),(4,102),(19,102)]:
            with self.subTest(ticket=ticket):
                self.stock({101:2,102:4})
                token = self.buyer()
                with patch('server.app.secrets.randbelow', return_value=ticket) as random:
                    result = self.draw(token)
                random.assert_called_once_with(20)
                self.assertEqual(result['reward']['product_id'], expected)
                self.assertEqual(self.product(101)['stock'], 2-(expected==101))
                self.assertEqual(self.product(102)['stock'], 4-(expected==102))
                self.assertEqual(result['user']['rewards_claimed'], 4)

    def test_next_draw_uses_remaining_shared_stock(self):
        self.stock({101:2,102:4})
        first, second = self.buyer(), self.buyer()
        with patch('server.app.secrets.randbelow', side_effect=[0,1]) as random:
            self.assertEqual(self.draw(first)['reward']['product_id'], 101)
            self.assertEqual(self.draw(second)['reward']['product_id'], 102)
        self.assertEqual(random.call_args_list, [call(20),call(17)])
        self.assertEqual((self.product(101)['stock'], self.product(102)['stock']), (1,3))

    def test_pending_orders_and_preorders_are_not_drawn(self):
        self.stock({101:3})
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET preorder_stock=5 WHERE id=102')
        shopper, player = self.buyer(), self.buyer()
        order = self.request('POST', '/api/orders',
                             {'items':[{'product_id':101,'quantity':2}], 'request_id':str(uuid.uuid4())}, shopper)['order']
        self.assertEqual(self.product(101)['stock'], 1)
        with patch('server.app.secrets.randbelow', return_value=0) as random:
            self.assertEqual(self.draw(player)['reward']['product_id'], 101)
        random.assert_called_once_with(1)
        self.assertEqual(self.product(101)['stock'], 0)
        self.assertEqual(self.product(102)['preorder_stock'], 5)
        staff = self.request('POST', '/api/staff/login',
                             {'name':'담당검증','password':'test-staff-password'})['token']
        self.request('POST', f"/api/staff/orders/{order['id']}/cancel", {}, staff)
        self.assertEqual(self.product(101)['stock'], 2)
        another = self.buyer()
        with patch('server.app.secrets.randbelow', return_value=0) as random:
            self.draw(another)
        random.assert_called_once_with(4)

    def test_sold_out_keeps_entitlement_and_retry_deducts_only_once(self):
        self.stock({})
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET preorder_stock=5 WHERE id=101')
        token, identity = self.buyer(), str(uuid.uuid4())
        with self.assertRaises(APIError) as error:
            self.draw(token, identity)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.request('GET','/api/auth/me',token=token)['user']['rewards_claimed'], 3)
        self.assertEqual(self.request('GET','/api/auth/me',token=token)['user']['level'], 3)
        self.stock({101:1})
        result = self.draw(token, identity)
        self.assertEqual(self.draw(token, identity), result)
        self.assertEqual(self.product(101)['stock'], 0)
        self.assertEqual(self.product(101)['preorder_stock'], 5)
        with self.app.db.transaction() as tx:
            logs = tx.all("SELECT * FROM inventory_logs WHERE bucket='stock' AND delta=-1")
            self.assertEqual(len(logs), 1)
            self.assertIn('이벤트 지급 요청', logs[0]['reason'])
            self.assertEqual(tx.one("SELECT COUNT(*) AS count FROM milestone_claims WHERE kind='bread'")['count'], 1)

    def test_last_unit_cannot_be_both_ordered_and_drawn(self):
        self.stock({101:1})
        shopper, player = self.buyer(), self.buyer()
        barrier = threading.Barrier(2)
        def compete(kind):
            barrier.wait(timeout=5)
            try:
                if kind=='order':
                    result=self.request('POST','/api/orders',{'items':[{'product_id':101,'quantity':1}],
                                                             'request_id':str(uuid.uuid4())},shopper)
                else:
                    result=self.draw(player)
                return 200,result
            except APIError as error:
                return error.status,None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(compete,['order','reward']))
        self.assertEqual(sorted(status for status,_ in results), [200,409])
        self.assertEqual(self.product(101)['stock'], 0)
        with self.app.db.transaction() as tx:
            orders=tx.one('SELECT COUNT(*) AS count FROM orders')['count']
            rewards=tx.one("SELECT COUNT(*) AS count FROM milestone_claims WHERE kind='bread'")['count']
            self.assertEqual(orders+rewards, 1)

    def test_staff_cannot_create_a_separate_reward_pool(self):
        staff=self.request('POST','/api/staff/login',
                            {'name':'담당검증','password':'test-staff-password'})['token']
        with self.assertRaises(APIError) as error:
            self.request('POST','/api/staff/inventory',
                         {'product_id':101,'bucket':'reward_stock','delta':2,'reason':'이전 화면 요청'},staff)
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.product(101)['stock'], 0)
        self.assertEqual(self.product(101)['reward_stock'], 0)


class SharedInventoryMigrationTests(unittest.TestCase):
    def test_merge_preserves_total_and_reservations_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='kambo-stock-migration-') as directory:
            environment=dict(os.environ)
            environment.pop('DATABASE_URL',None)
            environment['DB_PATH']=str(Path(directory)/'legacy.db')
            with patch.dict(os.environ,environment,clear=True):
                db=Database(ROOT)
                db.initialize()
                with db.transaction(write=True) as tx:
                    tx.execute("INSERT INTO products VALUES (101,'플레인 휘낭시에','바람의 정수',2800,20,5,3,'휘낭시에','wind')")
                    merge_legacy_reward_stock(tx)
                    first=tx.one('SELECT stock,preorder_stock,reward_stock FROM products WHERE id=101')
                    self.assertEqual(first, {'stock':23,'preorder_stock':5,'reward_stock':0})
                    logs=tx.all('SELECT bucket,delta FROM inventory_logs ORDER BY id')
                    self.assertEqual(logs, [{'bucket':'reward_stock','delta':-3},{'bucket':'stock','delta':3}])
                    merge_legacy_reward_stock(tx)
                    self.assertEqual(tx.one('SELECT stock,preorder_stock,reward_stock FROM products WHERE id=101'), first)
                    self.assertEqual(tx.one('SELECT COUNT(*) AS count FROM inventory_logs')['count'], 2)
