"""Physical event rewards reserve stock until staff approval or cancellation."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from account_support import account_payload, phone_for

from server.app import APIError, Application, grant_dice


class RewardRequestTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-reward-queue-')
        self.addCleanup(folder.cleanup)
        env=dict(os.environ)
        env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(Path(folder.name)/'app.db'),APP_ENV='production',DEMO_SEED='0',
                   STAFF_PASSWORD='request-test-password',ALLOWED_ORIGINS='')
        settings=patch.dict(os.environ,env,clear=True)
        settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.call('POST','/api/staff/login',{'name':'지급 담당','password':'request-test-password'})['token']
        self.buyer=self.register('구매자')

    def call(self,method,path,body=None,token=None):
        return self.app.handle(method,path,{},account_payload(path,body) or {},'Bearer '+token if token else None)

    def register(self,name):
        return self.call('POST','/api/auth/register',{'name':name,'pin':'1234'})

    def stock(self,pid,count):
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=? WHERE id=?',(count,pid))

    def available(self,pid):
        return next(p for p in self.call('GET','/api/products')['products'] if p['id']==pid)['stock']

    def claim_at(self,threshold):
        uid=self.buyer['user']['id']
        with self.app.db.transaction(write=True) as tx:
            for point,kind in [(5,'oatmeal'),(10,'milk'),(15,'sunglasses'),(20,'bread')]:
                if point>=threshold:break
                tx.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,threshold) DO NOTHING",(uid,point,kind,'선행 보상','2026-11-07'))
            tx.execute('UPDATE users SET score=? WHERE id=?',(threshold,uid))
        return self.call('POST','/api/rewards/claim',{'request_id':uuid.uuid4().hex},self.buyer['token'])

    def milk_roll(self,buyer=None,identity=None):
        buyer=buyer or self.buyer
        with self.app.db.transaction(write=True) as tx:grant_dice(tx,buyer['user']['id'],'instagram',1)
        with patch('server.app.secrets.randbelow',return_value=5):
            return self.call('POST','/api/dice/roll',{'kind':'instagram','request_id':identity or uuid.uuid4().hex},buyer['token'])

    def choose(self,row,pid,buyer=None,identity=None):
        return self.call('POST',f"/api/reward-requests/{row['id']}/choose",{'product_id':pid,'request_id':identity or uuid.uuid4().hex},(buyer or self.buyer)['token'])['request']

    def transition(self,row,action):
        return self.call('POST',f"/api/staff/reward-requests/{row['id']}/{action}",{},self.staff)['request']

    def test_bread_hold_approval_and_cancel_are_exactly_once(self):
        self.stock(101,2)
        first=self.claim_at(20)['reward']['fulfillment']
        self.assertEqual((first['status'],first['product_id'],self.available(101)),('pending',101,1))
        self.transition(first,'approve');self.transition(first,'approve')
        self.assertEqual(self.available(101),1)
        with self.assertRaises(APIError) as error:self.transition(first,'cancel')
        self.assertEqual(error.exception.status,409)
        second=self.claim_at(30)['reward']['fulfillment']
        self.assertEqual(self.available(101),0)
        self.transition(second,'cancel');self.transition(second,'cancel')
        self.assertEqual(self.available(101),1)
        with self.assertRaises(APIError):self.transition(second,'approve')
        with self.assertRaises(APIError):self.call('POST','/api/rewards/claim',{'request_id':uuid.uuid4().hex},self.buyer['token'])

    def test_milk_outcome_is_fixed_before_choice_and_soymilk_reserves_separately(self):
        self.stock(112,2);self.stock(113,1)
        outcome=self.milk_roll();row=outcome['fulfillment']
        self.assertEqual((outcome['result'],outcome['value'],outcome['dice_balance']),('milk',0,0))
        self.assertEqual((row['status'],self.available(112),self.available(113)),('awaiting_choice',2,1))
        identity=uuid.uuid4().hex
        chosen=self.choose(row,113,identity=identity)
        self.assertEqual(self.choose(row,113,identity=identity),chosen)
        self.assertEqual((chosen['status'],chosen['product_name'],self.available(112),self.available(113)),('pending','두유',2,0))
        with self.assertRaises(APIError):self.choose(row,112)
        self.transition(chosen,'cancel');self.transition(chosen,'cancel')
        self.assertEqual((self.available(112),self.available(113)),(2,1))
        record=self.call('GET','/api/rewards',token=self.buyer['token'])['rewards'][0]
        self.assertEqual((record['product_name'],record['fulfillment']['status']),('두유','cancelled'))

    def test_sold_out_options_are_rejected_and_buyer_can_decline_without_reroll(self):
        self.stock(112,0);self.stock(113,0)
        identity=uuid.uuid4().hex
        outcome=self.milk_roll(identity=identity);row=outcome['fulfillment']
        for pid in [112,113]:
            with self.assertRaises(APIError) as error:self.choose(row,pid)
            self.assertEqual(error.exception.status,409)
        body={'request_id':uuid.uuid4().hex}
        path=f"/api/reward-requests/{row['id']}/decline"
        result=self.call('POST',path,body,self.buyer['token'])
        self.assertEqual(self.call('POST',path,body,self.buyer['token']),result)
        self.assertEqual(result['request']['status'],'cancelled')
        replay=self.call('POST','/api/dice/roll',{'kind':'instagram','request_id':identity},self.buyer['token'])
        self.assertEqual(replay['id'],outcome['id'])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM typed_dice_rolls')['n'],1)
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM inventory_logs')['n'],0)

    def test_declining_unselected_drinks_moves_both_reward_sources_out_of_staff_choice_queue(self):
        self.stock(112,0);self.stock(113,2)
        rows=[self.milk_roll()['fulfillment'],self.claim_at(10)['reward']['fulfillment']]
        before=self.call('GET','/api/staff/dashboard',token=self.staff)['reward_requests']
        self.assertEqual(sum(r['status']=='awaiting_choice' for r in before),2)
        for row in rows:
            result=self.call('POST',f"/api/reward-requests/{row['id']}/decline",{'request_id':uuid.uuid4().hex},self.buyer['token'])
            self.assertEqual(result['request']['status'],'cancelled')
        dashboard=self.call('GET','/api/staff/dashboard',token=self.staff)['reward_requests']
        self.assertFalse(any(r['status']=='awaiting_choice' for r in dashboard))
        self.assertEqual({r['id'] for r in dashboard if r['status']=='cancelled'},{r['id'] for r in rows})
        buyer=self.call('GET','/api/rewards',token=self.buyer['token'])
        fulfilled=[r['fulfillment'] for r in buyer['rewards'] if r['fulfillment']]
        self.assertEqual({r['id'] for r in fulfilled},{r['id'] for r in rows})
        self.assertTrue(all(r['status']=='cancelled' for r in fulfilled))
        self.assertEqual((self.available(112),self.available(113)),(0,2))
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM inventory_logs')['n'],0)
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM typed_dice_rolls')['n'],1)

    def test_ownership_staff_authorization_and_selection_before_approval(self):
        self.stock(112,1);row=self.milk_roll()['fulfillment'];other=self.register('다른 구매자')
        with self.assertRaises(APIError) as error:self.choose(row,112,other)
        self.assertEqual(error.exception.status,403)
        with self.assertRaises(APIError) as error:self.call('POST',f"/api/staff/reward-requests/{row['id']}/approve",{},self.buyer['token'])
        self.assertEqual(error.exception.status,403)
        with self.assertRaises(APIError) as error:self.transition(row,'approve')
        self.assertEqual(error.exception.status,409)
        with self.assertRaises(APIError) as error:self.choose(row,101)
        self.assertEqual(error.exception.status,400)
        self.assertEqual(self.call('GET','/api/rewards',token=other['token'])['requests'],[])
        self.assertEqual(self.available(112),1)

    def test_last_drink_cannot_be_sold_and_held_as_reward(self):
        self.stock(113,1);row=self.milk_roll()['fulfillment'];shopper=self.register('음료 구매자')
        barrier=threading.Barrier(2)
        def compete(kind):
            barrier.wait(timeout=5)
            try:
                if kind=='reward':value=self.choose(row,113)
                else:value=self.call('POST','/api/orders',{'items':[{'product_id':113,'quantity':1}],'request_id':uuid.uuid4().hex},shopper['token'])
                return 200,value
            except APIError as error:return error.status,None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(compete,['reward','sale']))
        self.assertEqual(sorted(status for status,_ in results),[200,409])
        self.assertEqual(self.available(113),0)
        with self.app.db.transaction() as tx:self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM inventory_logs WHERE product_id=113 AND delta=-1")['n'],1)

    def test_competing_staff_transitions_are_final_and_stock_is_consistent(self):
        self.stock(112,1);row=self.choose(self.milk_roll()['fulfillment'],112)
        barrier=threading.Barrier(2)
        def compete(action):
            barrier.wait(timeout=5)
            try:return 200,self.transition(row,action)
            except APIError as error:return error.status,None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(compete,['approve','cancel']))
        self.assertEqual(sorted(status for status,_ in results),[200,409])
        final=next(r for status,r in results if status==200)
        self.assertEqual(self.available(112),int(final['status']=='cancelled'))

    def test_oatmeal_can_be_returned_but_digital_reward_skips_fulfillment(self):
        with self.app.db.transaction(write=True) as tx:tx.execute("UPDATE event_supplies SET stock=1 WHERE key='oatmeal'")
        row=self.claim_at(5)['reward']['fulfillment']
        self.assertEqual(row['status'],'pending')
        self.transition(row,'cancel');self.transition(row,'cancel')
        with self.app.db.transaction() as tx:self.assertEqual(tx.one("SELECT stock FROM event_supplies WHERE key='oatmeal'")['stock'],1)
        digital=self.claim_at(15)
        self.assertIsNone(digital['reward']['fulfillment'])
        self.assertTrue(digital['user']['sunglasses_unlocked'])
        rows=self.call('GET','/api/staff/dashboard',token=self.staff)['reward_requests']
        self.assertEqual(len(rows),1)

    def test_drink_sales_grant_no_dice_and_do_not_unlock_bread_pins(self):
        self.stock(112,2);self.stock(113,3)
        result=self.call('POST','/api/staff/manual-sale',{'user_id':self.buyer['user']['id'],'items':[{'product_id':112,'quantity':1},{'product_id':113,'quantity':2}],'request_id':uuid.uuid4().hex},self.staff)
        self.assertEqual((result['order']['total'],result['order']['dice_quantity']),(3000,0))
        self.assertEqual(result['user']['unlocked_hairpins'],['none'])
        menu=self.call('GET','/api/products')['products']
        for p in menu:
            if p['id'] in [112,113]:
                self.assertEqual((p['dice_per_unit'],p['reward_eligible'],p['beverage_reward_eligible']),(0,False,True))
        dashboard=self.call('GET','/api/staff/dashboard',token=self.staff)
        self.assertEqual(dashboard['stats']['bread_sold'],0)

    def test_restart_preserves_historical_grants_without_creating_duplicate_requests(self):
        self.stock(112,7)
        with self.app.db.transaction(write=True) as tx:
            uid=self.buyer['user']['id']
            tx.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_id,product_name,created_at) VALUES(?,10,'milk',112,'우유','2026-11-06')",(uid,))
            tx.execute("INSERT INTO typed_dice_rolls(user_id,kind,result,value,created_at) VALUES(?,'instagram','milk',0,'2026-11-06')",(uid,))
        self.app=Application()
        data=self.call('GET','/api/rewards',token=self.buyer['token'])
        self.assertEqual(len(data['rewards']),2)
        self.assertEqual(data['requests'],[])
        self.assertTrue(all(r['fulfillment'] is None for r in data['rewards']))
        self.assertEqual(self.available(112),7)

    def test_selected_achieved_milestones_can_be_claimed_independently_once(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE users SET score=20 WHERE id=?',(self.buyer['user']['id'],))
        self.stock(101,1)
        def claim(point,identity=None):
            return self.call('POST','/api/rewards/claim',{'threshold':point,'request_id':identity or uuid.uuid4().hex},self.buyer['token'])
        digital=claim(15)
        self.assertEqual(digital['reward']['kind'],'sunglasses')
        self.assertEqual(digital['user']['claimed_milestones'],[15])
        identity=uuid.uuid4().hex
        bread=claim(20,identity)
        self.assertEqual(claim(20,identity),bread)
        self.assertEqual(bread['reward']['threshold'],20)
        self.assertEqual(self.available(101),0)
        for point,status in [(15,409),(30,409),(25,400),('10',400),(True,400)]:
            with self.assertRaises(APIError) as error:claim(point)
            self.assertEqual(error.exception.status,status)
        claims=self.call('GET','/api/auth/me',token=self.buyer['token'])['user']['claimed_milestones']
        self.assertEqual(claims,[15,20])
