"""Milk sales share event stock but never grant purchase dice."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application
from server.catalog import MILK_PRODUCT_ID


class MilkTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-milk-')
        self.addCleanup(folder.cleanup)
        environment=dict(os.environ)
        environment.pop('DATABASE_URL',None)
        environment.update(DB_PATH=str(Path(folder.name)/'app.db'),APP_ENV='production',DEMO_SEED='0',
                           STAFF_PASSWORD='milk-test-password',ALLOWED_ORIGINS='')
        settings=patch.dict(os.environ,environment,clear=True)
        settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.request('POST','/api/staff/login',{'name':'우유담당','password':'milk-test-password'})['token']

    def request(self,method,path,body=None,token=None):
        return self.app.handle(method,path,{},body or {},'Bearer '+token if token else None)

    def buyer(self):
        return self.request('POST','/api/auth/register',{'name':'우유'+uuid.uuid4().hex[:8],'pin':'1234'})

    def stock(self,quantity,product_id=MILK_PRODUCT_ID):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=? WHERE id=?',(quantity,product_id))

    def product(self,product_id=MILK_PRODUCT_ID):
        return next(p for p in self.request('GET','/api/products')['products'] if p['id']==product_id)

    def me(self,buyer):
        return self.request('GET','/api/auth/me',token=buyer['token'])['user']

    def order(self,buyer,items):
        return self.request('POST','/api/orders',{'items':[{'product_id':pid,'quantity':q} for pid,q in items],
                                                'request_id':uuid.uuid4().hex},buyer['token'])['order']

    def transition(self,order,action):
        return self.request('POST',f"/api/staff/orders/{order['id']}/{action}",{},self.staff)['order']

    def certify(self,buyer,milk=0,dice=1,identity=None):
        return self.request('POST','/api/staff/instagram',{'user_id':buyer['user']['id'],
                            'milk_quantity':milk,'dice':dice,'request_id':identity or uuid.uuid4().hex},self.staff)

    def test_milk_menu_price_reservation_cancel_and_zero_purchase_dice(self):
        self.stock(4)
        buyer=self.buyer()
        milk=self.product()
        self.assertEqual((milk['name'],milk['price'],milk['dice_per_unit'],milk['reward_eligible']),('우유',2000,0,False))
        order=self.order(buyer,[(MILK_PRODUCT_ID,2)])
        self.assertEqual((order['quantity'],order['total'],order['dice_quantity']),(2,4000,0))
        self.assertEqual(self.product()['stock'],2)
        self.transition(order,'approve');self.transition(order,'approve')
        self.assertEqual(self.me(buyer)['dice_balance'],0)
        another=self.order(buyer,[(MILK_PRODUCT_ID,1)])
        self.transition(another,'cancel');self.transition(another,'cancel')
        self.assertEqual(self.product()['stock'],2)
        self.assertEqual(self.me(buyer)['dice_balance'],0)

    def test_mixed_order_and_manual_sale_grant_dice_for_bread_only(self):
        self.stock(8);self.stock(5,101)
        buyer=self.buyer()
        order=self.order(buyer,[(101,2),(MILK_PRODUCT_ID,3)])
        self.assertEqual((order['quantity'],order['total'],order['dice_quantity']),(5,11600,2))
        self.transition(order,'approve')
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        body={'user_id':buyer['user']['id'],'items':[{'product_id':MILK_PRODUCT_ID,'quantity':2}],
              'request_id':uuid.uuid4().hex}
        first=self.request('POST','/api/staff/manual-sale',body,self.staff)
        self.assertEqual(self.request('POST','/api/staff/manual-sale',body,self.staff),first)
        self.assertEqual(first['order']['dice_quantity'],0)
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        body={'user_id':buyer['user']['id'],'items':[{'product_id':101,'quantity':1},
              {'product_id':MILK_PRODUCT_ID,'quantity':1}],'request_id':uuid.uuid4().hex}
        self.request('POST','/api/staff/manual-sale',body,self.staff)
        dashboard=self.request('GET','/api/staff/dashboard',token=self.staff)
        self.assertEqual(self.me(buyer)['dice_balance'],3)
        self.assertEqual(dashboard['stats']['bread_sold'],3)
        self.assertEqual(dashboard['stats']['milk_stock'],2)
        self.assertEqual(self.product()['stock'],2)

    def test_preorders_reserve_and_restore_milk_but_only_bread_grants_dice(self):
        self.stock(3);self.stock(2,101)
        buyer=self.buyer()
        self.request('POST','/api/staff/preorders/import',{'reservations':[{
            'name':buyer['user']['name'],'phone':'01012345678',
            'items':[{'product_id':MILK_PRODUCT_ID,'quantity':2},{'product_id':101,'quantity':1}]}]},self.staff)
        self.assertEqual((self.product()['stock'],self.product()['preorder_stock']),(1,2))
        from urllib.parse import parse_qs,urlencode
        query=parse_qs(urlencode({'name':buyer['user']['name'],'phone':'01012345678'}))
        reservation=self.app.handle('GET','/api/preorders/lookup',query,{},'Bearer '+buyer['token'])['reservation']
        def claim():
            return self.request('POST',f"/api/preorders/{reservation['id']}/claim",
                                {'request_id':uuid.uuid4().hex},buyer['token'])['order']
        order=claim()
        self.assertEqual(order['dice_quantity'],1)
        self.assertEqual(self.product()['preorder_stock'],0)
        self.transition(order,'cancel')
        self.assertEqual(self.product()['preorder_stock'],2)
        self.transition(claim(),'approve')
        self.assertEqual(self.me(buyer)['dice_balance'],1)
        self.assertEqual((self.product()['stock'],self.product()['preorder_stock']),(1,0))

    def test_instagram_grants_only_one_typed_die_without_touching_milk(self):
        for stock in [0,2]:
            self.stock(stock);buyer=self.buyer();identity=uuid.uuid4().hex
            first=self.certify(buyer,identity=identity)
            self.assertEqual(self.certify(buyer,identity=identity),first)
            self.assertEqual((first['event']['milk_quantity'],first['event']['dice']),(0,1))
            self.assertEqual(self.me(buyer)['dice'][0]['kind'],'instagram')
            self.assertEqual(self.product()['stock'],stock)
            with self.assertRaises(APIError) as error:self.certify(buyer)
            self.assertEqual(error.exception.status,409)
        for milk,dice in [(1,1),(0,0),(0,2)]:
            with self.assertRaises(APIError) as error:self.certify(self.buyer(),milk,dice)
            self.assertEqual(error.exception.status,400)

    def test_milk_face_failure_is_atomic_and_retry_allocates_only_once(self):
        buyer=self.buyer();self.certify(buyer);self.stock(0);identity=uuid.uuid4().hex
        body={'kind':'instagram','request_id':identity}
        with patch('server.app.secrets.randbelow',return_value=5):
            with self.assertRaises(APIError) as error:self.request('POST','/api/dice/roll',body,buyer['token'])
            self.assertEqual(error.exception.status,409)
            self.assertEqual(self.me(buyer)['dice_balance'],1)
            self.stock(1)
            first=self.request('POST','/api/dice/roll',body,buyer['token'])
            self.assertEqual(self.request('POST','/api/dice/roll',body,buyer['token']),first)
        self.assertEqual((first['result'],first['value'],first['score']),('milk',0,0))
        self.assertEqual((self.product()['stock'],self.me(buyer)['dice_balance']),(0,0))
        records=self.request('GET','/api/rewards',token=buyer['token'])['rewards']
        self.assertEqual((len(records),records[0]['kind']),(1,'dice_milk'))

    def test_last_milk_cannot_be_sold_and_won_by_dice_simultaneously(self):
        self.stock(1);shopper,participant=self.buyer(),self.buyer();self.certify(participant)
        barrier=threading.Barrier(2)
        def compete(kind):
            barrier.wait(timeout=5)
            try:
                if kind=='sale':result=self.order(shopper,[(MILK_PRODUCT_ID,1)])
                else:result=self.request('POST','/api/dice/roll',{'kind':'instagram','request_id':uuid.uuid4().hex},participant['token'])
                return 200,result
            except APIError as error:return error.status,None
        with patch('server.app.secrets.randbelow',return_value=5):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(compete,['sale','dice']))
        self.assertEqual(sorted(status for status,_ in results),[200,409])
        self.assertEqual(self.product()['stock'],0)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM inventory_logs WHERE product_id=? AND delta=-1',(MILK_PRODUCT_ID,))['n'],1)

    def test_milk_is_never_a_random_bread_reward(self):
        self.stock(20)
        buyer=self.buyer()
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE users SET score=20 WHERE id=?',(buyer['user']['id'],))
            for threshold,kind in [(5,'oatmeal'),(10,'milk'),(15,'sunglasses')]:
                tx.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(?,?,?,?,?)",(buyer['user']['id'],threshold,kind,'선행 보상 테스트','2026-11-07'))
        body={'request_id':uuid.uuid4().hex}
        with self.assertRaises(APIError) as error:self.request('POST','/api/rewards/claim',body,buyer['token'])
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.me(buyer)['rewards_claimed'],0)
        self.stock(1,101)
        with patch('server.app.secrets.randbelow',return_value=0) as random:
            result=self.request('POST','/api/rewards/claim',body,buyer['token'])
        random.assert_called_once_with(1)
        self.assertEqual(result['reward']['product_id'],101)
        self.assertEqual(self.product()['stock'],20)

    def test_legacy_milk_migrates_once_and_compatibility_writes_use_same_stock(self):
        self.stock(2)
        with self.app.db.transaction(write=True) as tx:
            tx.execute("UPDATE settings SET value='7' WHERE key='milk_stock'")
        self.app.seed()
        self.assertEqual(self.product()['stock'],9)
        self.app.seed()
        self.assertEqual(self.product()['stock'],9)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one("SELECT value FROM settings WHERE key='milk_stock'")['value'],'0')
            logs=tx.all("SELECT * FROM inventory_logs WHERE reason='별도 우유 재고를 일반 품목 재고로 통합'")
            self.assertEqual([(x['bucket'],x['delta']) for x in logs],[('milk',-7),('stock',7)])
        body={'bucket':'milk','delta':-3,'reason':'이전 화면 호환','request_id':uuid.uuid4().hex}
        first=self.request('POST','/api/staff/inventory',body,self.staff)
        self.assertEqual(self.request('POST','/api/staff/inventory',body,self.staff),first)
        self.app.seed()
        self.assertEqual(self.product()['stock'],6)
        buyer=self.buyer();self.certify(buyer)
        self.assertEqual(self.product()['stock'],6)
        self.assertEqual(self.me(buyer)['dice_balance'],1)
