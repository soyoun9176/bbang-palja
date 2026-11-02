"""Staff preorder fulfillment shares the customer order and reserved stock."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs,urlencode

from server.app import Application,APIError,now


class ManualPreorderTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-manual-preorder-')
        self.addCleanup(folder.cleanup)
        environment=dict(os.environ)
        environment.pop('DATABASE_URL',None)
        environment.update(DB_PATH=str(Path(folder.name)/'app.db'),APP_ENV='production',DEMO_SEED='0',
                           STAFF_PASSWORD='preorder-test-password',ALLOWED_ORIGINS='')
        settings=patch.dict(os.environ,environment,clear=True)
        settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.request('POST','/api/staff/login',{'name':'수령담당','password':'preorder-test-password'})['token']
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=10 WHERE id=101')
            tx.execute('UPDATE products SET stock=5 WHERE id=112')

    def request(self,method,path,body=None,token=None):
        return self.app.handle(method,path,{},body or {},'Bearer '+token if token else None)

    def buyer(self,name=None):
        return self.request('POST','/api/auth/register',{'name':name or '예약'+uuid.uuid4().hex[:8],'pin':'1234'})

    def reserve(self,name,items=None):
        self.request('POST','/api/staff/preorders/import',{'reservations':[{'name':name,'phone':'01012345678',
            'items':items or [{'product_id':101,'quantity':2},{'product_id':112,'quantity':1}]}]},self.staff)
        return self.lookup(name)

    def lookup(self,name,phone='01012345678'):
        return self.request('POST','/api/staff/preorders/lookup',{'name':name,'phone':phone},self.staff)['reservation']

    def complete(self,reservation,extra=None,identity=None,staff=None):
        return self.request('POST',f"/api/staff/preorders/{reservation['id']}/complete",
            {'name':reservation['name'],'phone':reservation['phone'],'request_id':identity or uuid.uuid4().hex,
             **(extra or {})},staff or self.staff)

    def product(self,pid):
        with self.app.db.transaction() as tx:return tx.one('SELECT * FROM products WHERE id=?',(pid,))

    def me(self,buyer):
        return self.request('GET','/api/auth/me',token=buyer['token'])['user']

    def claim(self,reservation,buyer):
        query=parse_qs(urlencode({'name':reservation['name'],'phone':reservation['phone']}))
        self.app.handle('GET','/api/preorders/lookup',query,{},'Bearer '+buyer['token'])
        return self.request('POST',f"/api/preorders/{reservation['id']}/claim",{'request_id':uuid.uuid4().hex},buyer['token'])['order']

    def test_reserved_pickup_uses_original_prices_and_only_reserved_stock_once(self):
        buyer=self.buyer();r=self.reserve(buyer['user']['name'])
        self.assertEqual((r['status'],r['dice_quantity'],r['total'],r['order']),('reserved',2,7600,None))
        before=[self.product(p)['stock'] for p in [101,112]]
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET price=9999 WHERE id=101')
        identity=uuid.uuid4().hex
        result=self.complete(r,{'user_id':buyer['user']['id']},identity)
        self.assertEqual(self.complete(r,{'user_id':buyer['user']['id']},identity),result)
        self.assertEqual((result['order']['type'],result['order']['status'],result['order']['total']),('preorder','approved',7600))
        self.assertEqual(result['order']['dice_quantity'],2)
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        self.assertEqual([self.product(p)['stock'] for p in [101,112]],before)
        self.assertEqual([self.product(p)['preorder_stock'] for p in [101,112]],[0,0])
        repeat=self.complete(r,{'user_id':buyer['user']['id']})
        self.assertTrue(repeat['already_completed'])
        self.assertEqual(repeat['order']['id'],result['order']['id'])
        self.assertEqual(self.claim(r,buyer)['id'],result['order']['id'])
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        with self.app.db.transaction() as tx:self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM orders')['n'],1)

    def test_existing_customer_pickup_request_is_approved_without_another_deduction(self):
        buyer=self.buyer();r=self.reserve(buyer['user']['name'])
        order=self.claim(r,buyer)
        self.assertEqual(self.product(101)['preorder_stock'],0)
        self.assertEqual(self.lookup(r['name'])['order']['id'],order['id'])
        result=self.complete(r,{'user_id':buyer['user']['id']})
        self.assertEqual(result['order']['id'],order['id'])
        self.assertEqual(result['order']['status'],'approved')
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        self.assertEqual(self.product(101)['preorder_stock'],0)
        self.request('POST',f"/api/staff/orders/{order['id']}/approve",{},self.staff)
        self.assertEqual(self.me(buyer)['dice_balance'],2)

    def test_new_buyer_can_collect_milk_without_purchase_dice(self):
        r=self.reserve('첫방문예약자',[{'product_id':112,'quantity':2}])
        result=self.complete(r,{'pin':'2345'})
        self.assertEqual(result['user']['name'],'첫방문예약자')
        self.assertEqual(result['user']['dice_balance'],0)
        self.assertEqual((result['order']['quantity'],result['order']['total']),(2,4000))
        login=self.request('POST','/api/auth/login',{'name':'첫방문예약자','pin':'2345'})
        self.assertEqual(login['user']['id'],result['user']['id'])
        self.complete(r,{'pin':'9999'})  # Completed receipt does not reset the account PIN.
        self.request('POST','/api/auth/login',{'name':'첫방문예약자','pin':'2345'})
        self.assertEqual((self.product(112)['stock'],self.product(112)['preorder_stock']),(3,0))

    def test_failed_stock_rolls_back_new_account_and_all_partial_writes(self):
        r=self.reserve('재고검증예약자');identity=uuid.uuid4().hex
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET preorder_stock=0 WHERE id=112')
        with self.assertRaises(APIError) as error:self.complete(r,{'pin':'2345'},identity)
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.product(101)['preorder_stock'],2)
        with self.app.db.transaction() as tx:
            self.assertIsNone(tx.one("SELECT id FROM users WHERE name=? AND role='buyer'",(r['name'],)))
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM orders')['n'],0)
            self.assertEqual(tx.one('SELECT status FROM reservations WHERE id=?',(r['id'],))['status'],'reserved')
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET preorder_stock=1 WHERE id=112')
        self.assertEqual(self.complete(r,{'pin':'2345'},identity)['user']['dice_balance'],2)

    def test_invalid_phone_wrong_account_and_buyer_access_do_not_fulfill(self):
        buyer=self.buyer();other=self.buyer();r=self.reserve(buyer['user']['name'])
        cases=[({'phone':'01099999999','user_id':buyer['user']['id']},404),
               ({'user_id':other['user']['id']},409),({'pin':'9999'},409),({'pin':'123'},400)]
        for body,status in cases:
            with self.subTest(body=body),self.assertRaises(APIError) as error:self.complete(r,body)
            self.assertEqual(error.exception.status,status)
        for path,body in [('/api/staff/preorders/lookup',{'name':r['name'],'phone':r['phone']}),
                          (f"/api/staff/preorders/{r['id']}/complete",{'name':r['name'],'phone':r['phone'],'request_id':uuid.uuid4().hex})]:
            with self.assertRaises(APIError) as error:self.request('POST',path,body,buyer['token'])
            self.assertEqual(error.exception.status,403)
            with self.assertRaises(APIError) as error:self.request('POST',path,body)
            self.assertEqual(error.exception.status,401)
        self.assertEqual(self.me(buyer)['dice_balance'],0)
        self.assertEqual(self.product(101)['preorder_stock'],2)
        # A staff lookup must not grant the buyer a phone-verification record.
        with self.assertRaises(APIError) as error:self.request('POST',f"/api/preorders/{r['id']}/claim",{'request_id':uuid.uuid4().hex},buyer['token'])
        self.assertEqual(error.exception.status,403)

    def test_cancelled_request_can_be_collected_with_a_new_order(self):
        buyer=self.buyer();r=self.reserve(buyer['user']['name'])
        order=self.claim(r,buyer)
        self.request('POST',f"/api/staff/orders/{order['id']}/cancel",{},self.staff)
        self.assertEqual(self.product(101)['preorder_stock'],2)
        result=self.complete(r,{'user_id':buyer['user']['id']})
        self.assertNotEqual(result['order']['id'],order['id'])
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        self.assertEqual(self.product(101)['preorder_stock'],0)

    def test_two_staff_cannot_complete_the_same_reservation_twice(self):
        buyer=self.buyer();r=self.reserve(buyer['user']['name'])
        second=self.request('POST','/api/staff/login',{'name':'다음담당','password':'preorder-test-password'})['token']
        barrier=threading.Barrier(2)
        def complete(token):
            barrier.wait(timeout=5)
            return self.complete(r,{'user_id':buyer['user']['id']},staff=token)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(complete,[self.staff,second]))
        self.assertEqual(results[0]['order']['id'],results[1]['order']['id'])
        self.assertEqual(sorted(x['already_completed'] for x in results),[False,True])
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM orders')['n'],1)
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM inventory_logs WHERE bucket='preorder_stock' AND delta<0")['n'],2)

    def test_customer_claim_and_manual_pickup_race_share_one_order(self):
        buyer=self.buyer();r=self.reserve(buyer['user']['name'])
        query=parse_qs(urlencode({'name':r['name'],'phone':r['phone']}))
        self.app.handle('GET','/api/preorders/lookup',query,{},'Bearer '+buyer['token'])
        barrier=threading.Barrier(2)
        def compete(kind):
            barrier.wait(timeout=5)
            if kind=='staff':return self.complete(r,{'user_id':buyer['user']['id']})['order']
            return self.request('POST',f"/api/preorders/{r['id']}/claim",{'request_id':uuid.uuid4().hex},buyer['token'])['order']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:orders=list(pool.map(compete,['staff','buyer']))
        self.assertEqual(orders[0]['id'],orders[1]['id'])
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        self.assertEqual(self.product(101)['preorder_stock'],0)

    def test_historical_menu_reservation_uses_its_reserved_price(self):
        buyer=self.buyer()
        with self.app.db.transaction(write=True) as tx:
            tx.execute("INSERT INTO products VALUES(1,'이전 예약 빵','',9000,9,2,0,'이전','salt-bread')")
            rid=tx.insert('INSERT INTO reservations(name,phone,created_at) VALUES(?,?,?)',(buyer['user']['name'],'01012345678',now()))
            tx.execute('INSERT INTO reservation_items(reservation_id,product_id,quantity,price) VALUES(?,1,2,2500)',(rid,))
        r=self.lookup(buyer['user']['name'])
        result=self.complete(r,{'user_id':buyer['user']['id']})
        self.assertEqual(result['order']['total'],5000)
        self.assertEqual(self.me(buyer)['dice_balance'],2)
        self.assertEqual((self.product(1)['stock'],self.product(1)['preorder_stock']),(9,0))
