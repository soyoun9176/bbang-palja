"""Staff recovery grants preserve stock, score, identity and a durable audit trail."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application


class ManualEventGrantTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-manual-grant-')
        self.addCleanup(folder.cleanup)
        env=dict(os.environ)
        env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(Path(folder.name)/'app.db'),APP_ENV='development',DEMO_SEED='0',STAFF_PASSWORD='grant-test-password')
        settings=patch.dict(os.environ,env,clear=True)
        settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.call('/api/staff/login',{'name':'지급담당','password':'grant-test-password'})
        self.buyer=self.call('/api/auth/register',{'name':'대상자','phone':'01011112222','pin':'1234'})
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=5 WHERE id IN (101,112,113)')
            tx.execute("UPDATE event_supplies SET stock=5 WHERE key='oatmeal'")
            tx.execute("INSERT INTO settings(key,value) VALUES('event_beverage_limit_112','100'),('event_beverage_limit_113','100')")

    def call(self,path,body=None,token=None,method='POST'):
        return self.app.handle(method,path,{},body or {},'Bearer '+token if token else None)

    def give(self,extra=None,identity=None):
        body={'user_id':self.buyer['user']['id'],'kind':'bread','product_id':101,'quantity':1,
              'reason':'이벤트 오류 복구','request_id':identity or uuid.uuid4().hex,**(extra or {})}
        if body.get('guest'):body.pop('user_id')
        return self.call('/api/staff/manual-event-grants',body,self.staff['token'])

    def me(self):
        return self.call('/api/auth/me',token=self.buyer['token'],method='GET')['user']

    def stock(self,product_id=101):
        with self.app.db.transaction() as tx:return tx.one('SELECT stock FROM products WHERE id=?',(product_id,))['stock']

    def count(self,table):
        with self.app.db.transaction() as tx:return tx.one(f'SELECT COUNT(*) AS n FROM {table}')['n']

    def test_only_staff_can_grant_and_view_audit_records(self):
        for token,status in ((None,401),(self.buyer['token'],403)):
            with self.assertRaises(APIError) as error:self.call('/api/staff/manual-event-grants',{},token)
            self.assertEqual(error.exception.status,status)
        self.assertEqual(self.count('manual_event_grants'),0)
        self.assertEqual(self.stock(),5)

    def test_account_bread_grant_decrements_shared_stock_and_records_actor_without_sales_or_dice(self):
        result=self.give({'quantity':2})
        grant=result['grant']
        self.assertEqual((grant['user_id'],grant['customer_name'],grant['quantity']),
                         (self.buyer['user']['id'],'대상자',2))
        self.assertEqual((grant['staff_id'],grant['staff_name'],grant['reason']),
                         (self.staff['user']['id'],'지급담당','이벤트 오류 복구'))
        self.assertEqual(self.stock(),3)
        for table in ('orders','dice_wallet','milestone_claims'):self.assertEqual(self.count(table),0)
        self.assertEqual(self.me()['unlocked_hairpins'],['none'])
        dashboard=self.call('/api/staff/dashboard',token=self.staff['token'],method='GET')
        self.assertEqual(dashboard['manual_grants'],[grant])
        self.assertEqual((dashboard['stats']['revenue'],dashboard['stats']['bread_sold']),(0,0))
        with self.app.db.transaction() as tx:
            log=tx.one('SELECT * FROM inventory_logs ORDER BY id DESC LIMIT 1')
            self.assertEqual((log['delta'],log['actor']),(-2,'지급담당'))
            self.assertIn(f"임의 지급 #{grant['id']}",log['reason'])

    def test_guest_goods_have_integer_grant_ids_without_creating_accounts(self):
        before=(self.count('users'),self.count('sessions'))
        bread=self.give({'guest':True,'name':'비회원','quantity':2})
        gift=self.give({'guest':True,'name':'비회원','kind':'gift','gift':'milk','quantity':1})
        self.assertEqual(gift['grant']['id'],bread['grant']['id']+1)
        for value in (bread,gift):
            self.assertIsNone(value['user'])
            self.assertIsNone(value['grant']['user_id'])
            self.assertEqual(value['grant']['customer_name'],'비회원')
        self.assertEqual((self.count('users'),self.count('sessions')),before)
        self.assertEqual((self.stock(),self.stock(112)),(3,4))

    def test_gifts_use_their_own_stock_and_custom_prizes_only_leave_a_record(self):
        for gift in ('milk','soymilk','oatmeal'):
            result=self.give({'kind':'gift','gift':gift,'quantity':2})
            self.assertEqual(result['grant']['gift_key'],gift)
        self.assertEqual((self.stock(112),self.stock(113)),(3,3))
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one("SELECT stock FROM event_supplies WHERE key='oatmeal'")['stock'],3)
        custom=self.give({'guest':True,'name':'상품 수령자','kind':'gift','gift':'custom','gift_name':'푸딩 무드등','quantity':3})
        self.assertEqual((custom['grant']['item_name'],custom['grant']['quantity']),('푸딩 무드등',3))
        self.assertIsNone(custom['grant']['product_id'])
        self.assertIsNone(custom['grant']['supply_key'])
        self.assertEqual(self.count('inventory_logs'),3)

    def test_score_grants_update_ranking_and_allow_normal_milestones_without_auto_claims(self):
        result=self.give({'kind':'score','points':16})
        self.assertEqual((result['grant']['points'],result['user']['score']),(16,16))
        self.assertEqual(self.me()['score'],16)
        self.assertEqual((self.count('milestone_claims'),self.count('reward_requests'),self.count('dice_wallet')),(0,0,0))
        board=self.call('/api/leaderboard',token=self.buyer['token'],method='GET')
        self.assertEqual(board['leaders'][0]['score'],16)
        reward=self.call('/api/rewards/claim',{'threshold':5,'request_id':uuid.uuid4().hex},self.buyer['token'])
        self.assertEqual(reward['reward']['threshold'],5)
        self.assertEqual(self.stock(),5)

    def test_sunglasses_can_be_recovered_without_faking_score_or_milestone_claims(self):
        avatar={**self.me()['avatar'],'glasses':'sunglasses'}
        with self.assertRaises(APIError) as error:self.call('/api/profile',{'avatar':avatar},self.buyer['token'])
        self.assertEqual(error.exception.status,403)
        identity=uuid.uuid4().hex
        first=self.give({'kind':'gift','gift':'sunglasses'},identity)
        self.assertEqual(self.give({'kind':'gift','gift':'sunglasses'},identity),first)
        self.assertTrue(first['user']['sunglasses_unlocked'])
        saved=self.call('/api/profile',{'avatar':avatar},self.buyer['token'])['user']
        self.assertEqual(saved['avatar']['glasses'],'sunglasses')
        self.assertEqual((saved['score'],saved['level'],saved['claimed_milestones']),(0,0,[]))
        board=self.call('/api/leaderboard',token=self.buyer['token'],method='GET')
        self.assertEqual(board['leaders'][0]['avatar']['glasses'],'sunglasses')
        with self.assertRaises(APIError) as error:self.give({'kind':'gift','gift':'sunglasses'})
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.count('manual_event_grants'),1)

    def test_guest_cannot_receive_points_or_profile_access_even_via_direct_api(self):
        for extra in ({'kind':'score','points':5},{'kind':'gift','gift':'sunglasses'}):
            with self.assertRaises(APIError) as error:self.give({'guest':True,'name':'비회원',**extra})
            self.assertEqual(error.exception.status,400)
        self.assertEqual(self.count('manual_event_grants'),0)
        self.assertFalse(self.me()['sunglasses_unlocked'])
        self.assertEqual(self.me()['score'],0)

    def test_identical_retry_grants_once_and_conflicting_retry_is_rejected(self):
        identity=uuid.uuid4().hex
        first=self.give({'kind':'score','points':7},identity)
        self.assertEqual(self.give({'kind':'score','points':7},identity),first)
        with self.assertRaises(APIError) as error:self.give({'kind':'score','points':8},identity)
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.me()['score'],7)
        self.assertEqual(self.count('manual_event_grants'),1)

    def test_invalid_grants_and_insufficient_stock_leave_no_partial_audit_or_inventory_changes(self):
        cases=[{'quantity':0},{'quantity':-1},{'quantity':True},{'quantity':101},{'reason':''},
               {'kind':'unknown'},{'product_id':112},{'product_id':99999},
               {'kind':'score','points':0},{'kind':'score','points':-2},{'kind':'score','points':1.5},
               {'kind':'score','points':10001},{'kind':'gift','gift':'missing'},
               {'kind':'gift','gift':'custom','gift_name':''},{'kind':'gift','gift':'sunglasses','quantity':2},
               {'user_id':self.staff['user']['id']},{'guest':True,'name':''},
               {'guest':True,'name':'비회원','phone':'01011112222'}, {'quantity':6}]
        for extra in cases:
            with self.subTest(extra=extra):
                with self.assertRaises(APIError):self.give(extra)
        self.assertEqual((self.count('manual_event_grants'),self.count('inventory_logs'),self.count('idempotency')),(0,0,0))
        self.assertEqual((self.stock(),self.me()['score']),(5,0))

    def test_manual_grant_and_sale_cannot_take_the_same_last_unit(self):
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=1 WHERE id=101')
        def submit(grant):
            try:
                if grant:self.give({'guest':True,'name':'비회원'})
                else:self.call('/api/orders',{'items':[{'product_id':101,'quantity':1}],
                                             'request_id':uuid.uuid4().hex},self.buyer['token'])
                return 200
            except APIError as error:return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit,(True,False))),[200,409])
        self.assertEqual(self.stock(),0)
        self.assertEqual(self.count('orders')+self.count('manual_event_grants'),1)

    def test_existing_database_adds_grant_table_without_changing_previous_records(self):
        self.call('/api/orders',{'items':[{'product_id':101,'quantity':1}],
                                'request_id':uuid.uuid4().hex},self.buyer['token'])
        with self.app.db.transaction(write=True) as tx:
            before={table:tx.all('SELECT * FROM '+table) for table in ('users','sessions','orders','order_items','products','idempotency')}
            tx.execute('DROP TABLE manual_event_grants')
        self.app=Application()
        with self.app.db.transaction() as tx:
            for table,rows in before.items():self.assertEqual(tx.all('SELECT * FROM '+table),rows,table)
            self.assertEqual(tx.all('SELECT * FROM manual_event_grants'),[])
            self.assertEqual(tx.all('PRAGMA foreign_key_check'),[])


if __name__=='__main__':
    unittest.main()
