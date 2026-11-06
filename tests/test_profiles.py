"""Account-scoped character choices persist without changing event progress."""
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from account_support import account_payload, phone_for

from server.app import Application, APIError, AVATAR_OPTIONS, default_avatar


class ProfileTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-profiles-')
        self.addCleanup(folder.cleanup)
        env=dict(os.environ)
        env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(Path(folder.name)/'app.db'),APP_ENV='production',DEMO_SEED='0',
                   STAFF_PASSWORD='profile-test-password',ALLOWED_ORIGINS='')
        settings=patch.dict(os.environ,env,clear=True)
        settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.buyer=self.call('POST','/api/auth/register',{'name':'꾸미는사람','pin':'1234'})
        self.other=self.call('POST','/api/auth/register',{'name':'다른사람','pin':'5678'})
        self.staff=self.call('POST','/api/staff/login',{'name':'담당자','password':'profile-test-password'})
        self.chosen={'face_shape':'financier','skin':'warm','expression':'wink','glasses':'round','hairpin':'none'}

    def call(self,method,path,body=None,token=None):
        return self.app.handle(method,path,{},account_payload(path,body) or {},'Bearer '+token if token else None)

    def me(self,account):
        return self.call('GET','/api/auth/me',token=account['token'])['user']

    def save(self,avatar=None,account=None):
        return self.call('POST','/api/profile',{'avatar':avatar or self.chosen},(account or self.buyer)['token'])['user']

    def order(self,items,account=None):
        return self.call('POST','/api/orders',{'items':items,'request_id':uuid.uuid4().hex},(account or self.buyer)['token'])['order']

    def transition(self,order,action):
        return self.call('POST',f"/api/staff/orders/{order['id']}/{action}",{},self.staff['token'])

    def test_hairpins_unlock_only_after_purchase_approval_and_cannot_be_forged(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=10 WHERE id IN (101,102,112)')
        self.assertEqual(self.me(self.buyer)['unlocked_hairpins'],['none'])
        pending=self.order([{'product_id':101,'quantity':1},{'product_id':112,'quantity':1}])
        selected={**self.chosen,'hairpin':'bread_101'}
        with self.assertRaises(APIError) as error:self.save(selected)
        self.assertEqual(error.exception.status,403)
        self.assertIn('구매가 승인',error.exception.message)
        self.transition(pending,'approve')
        self.assertEqual(self.me(self.buyer)['unlocked_hairpins'],['none','bread_101'])
        self.assertEqual(self.save(selected)['avatar'],selected)
        cancelled=self.order([{'product_id':102,'quantity':1}]);self.transition(cancelled,'cancel')
        with self.assertRaises(APIError) as error:self.save({**selected,'hairpin':'bread_102'})
        self.assertEqual(error.exception.status,403)
        self.assertEqual(self.me(self.buyer)['avatar'],selected)
        with self.assertRaises(APIError) as error:self.save({**selected,'hairpin':'bread_112'})
        self.assertEqual(error.exception.status,400)
        self.assertEqual(self.me(self.other)['unlocked_hairpins'],['none'])
        board=self.call('GET','/api/leaderboard',token=self.other['token'])
        entry=next(p for p in board['leaders'] if p['id']==self.buyer['user']['id'])
        self.assertEqual(entry['avatar']['hairpin'],'bread_101')
        self.assertNotIn('unlocked_hairpins',entry)

    def test_preorder_and_manual_sales_unlock_the_credited_accounts_bread(self):
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=10 WHERE id IN (102,109)')
        self.call('POST','/api/staff/preorders/import',{'reservations':[{'name':'꾸미는사람','phone':'01012345678',
            'items':[{'product_id':109,'quantity':1}]}]},self.staff['token'])
        reservation=self.app.handle('GET','/api/preorders/lookup',{'name':['꾸미는사람'],'phone':['01012345678']},{},'Bearer '+self.buyer['token'])['reservation']
        order=self.call('POST',f"/api/preorders/{reservation['id']}/claim",{'request_id':uuid.uuid4().hex},self.buyer['token'])['order']
        self.assertEqual(self.me(self.buyer)['unlocked_hairpins'],['none'])
        self.transition(order,'approve')
        for _ in range(2):
            self.call('POST','/api/staff/manual-sale',{'user_id':self.other['user']['id'],
                'items':[{'product_id':102,'quantity':1}],'request_id':uuid.uuid4().hex},self.staff['token'])
        self.assertEqual(self.me(self.buyer)['unlocked_hairpins'],['none','bread_109'])
        self.assertEqual(self.me(self.other)['unlocked_hairpins'],['none','bread_102'])
        self.assertEqual(self.save({**self.chosen,'hairpin':'bread_109'})['avatar']['hairpin'],'bread_109')
        with self.assertRaises(APIError):self.save({**self.chosen,'hairpin':'bread_109'},self.other)

    def test_sunglasses_require_the_fifteen_point_reward(self):
        selected={**self.chosen,'glasses':'sunglasses','expression':'happy'}
        with self.assertRaises(APIError) as error:self.save(selected)
        self.assertEqual(error.exception.status,403)
        with self.app.db.transaction(write=True) as tx:
            tx.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(?,15,'sunglasses','멋진 선글라스','2026-11-07')",(self.buyer['user']['id'],))
        self.assertEqual(self.save(selected)['avatar'],selected)
        user=self.me(self.buyer)
        self.assertTrue(user['sunglasses_unlocked'])
        self.assertEqual((user['score'],user['dice_balance']),(0,0))

    def test_bread_reward_does_not_count_as_a_purchase_for_hairpins(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=0')
            tx.execute('UPDATE products SET stock=2 WHERE id=101')
            tx.execute('UPDATE users SET score=20 WHERE id=?',(self.buyer['user']['id'],))
            for threshold,kind in [(5,'oatmeal'),(10,'milk'),(15,'sunglasses')]:
                tx.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(?,?,?,?,?)",(self.buyer['user']['id'],threshold,kind,'선행 보상 테스트','2026-11-07'))
        self.call('POST','/api/rewards/claim',{'request_id':uuid.uuid4().hex},self.buyer['token'])
        self.assertEqual(self.me(self.buyer)['unlocked_hairpins'],['none'])

    def test_legacy_profiles_get_a_default_expression_and_no_unearned_pin(self):
        legacy={'face_shape':'oval','skin':'warm','hair_style':'waves','hair_color':'plum','glasses':'round','hairpin':'star'}
        expected={'face_shape':'financier','skin':'warm','expression':'smile','glasses':'round','hairpin':'none'}
        with self.app.db.transaction(write=True) as tx:
            tx.execute("INSERT INTO user_profiles(user_id,appearance,updated_at) VALUES(?,?,'2026-11-06')",
                       (self.buyer['user']['id'],json.dumps(legacy)))
        self.assertEqual(self.me(self.buyer)['avatar'],expected)
        self.assertEqual(self.save(legacy)['avatar'],expected)
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE user_profiles SET appearance=? WHERE user_id=?',
                       (json.dumps({**expected,'hairpin':'bread_101'}),self.buyer['user']['id']))
        self.assertEqual(self.me(self.buyer)['avatar']['hairpin'],'none')

    def test_defaults_exist_for_every_account_without_creating_profile_records(self):
        for account in [self.buyer,self.other,self.staff]:
            user=self.me(account)
            self.assertEqual(user['avatar'],default_avatar(user['id']))
            self.assertFalse(user['profile_customized'])
            self.assertEqual(set(user['avatar']),set(AVATAR_OPTIONS))
        self.assertNotEqual(self.me(self.buyer)['avatar'],self.me(self.other)['avatar'])
        self.app=Application()
        self.assertEqual(self.me(self.buyer)['avatar'],self.buyer['user']['avatar'])
        with self.app.db.transaction() as tx:self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM user_profiles')['n'],0)

    def test_saved_choices_survive_login_restart_and_are_visible_in_ranking_and_staff(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE users SET score=23,dice_balance=4,rewards_claimed=2 WHERE id=?',(self.buyer['user']['id'],))
            tx.execute('UPDATE products SET stock=8 WHERE id=101')
        user=self.save()
        self.assertEqual(user['avatar'],self.chosen)
        self.assertTrue(user['profile_customized'])
        self.assertEqual((user['score'],user['dice_balance'],user['rewards_claimed'],user['level']),(23,4,2,2))
        login=self.call('POST','/api/auth/login',{'name':'꾸미는사람','pin':'1234'})
        self.assertEqual(login['user']['avatar'],self.chosen)
        self.app=Application()
        self.assertEqual(self.me(self.buyer)['avatar'],self.chosen)
        board=self.call('GET','/api/leaderboard',token=self.other['token'])
        for rows in [board['leaders'],board['neighbors']]:
            entry=next(row for row in rows if row['id']==user['id'])
            self.assertEqual(entry['avatar'],self.chosen)
            self.assertNotIn('password_hash',entry)
            self.assertNotIn('appearance',entry)
        dashboard=self.call('GET','/api/staff/dashboard',token=self.staff['token'])
        self.assertEqual(next(u for u in dashboard['users'] if u['id']==user['id'])['avatar'],self.chosen)
        self.assertEqual(next(p for p in dashboard['products'] if p['id']==101)['stock'],8)
        self.assertFalse(self.me(self.other)['profile_customized'])

    def test_legacy_face_choices_map_to_bread_without_losing_other_customizations(self):
        for old,new in [('round','madeleine'),('oval','financier'),('square','pound'),('soboro','madeleine'),('salt','financier'),('toast','pound')]:
            with self.subTest(old=old):
                saved={**self.chosen,'face_shape':old}
                with self.app.db.transaction(write=True) as tx:
                    tx.execute("INSERT INTO user_profiles(user_id,appearance,updated_at) VALUES(?,?,'2026-11-06') "
                               "ON CONFLICT(user_id) DO UPDATE SET appearance=excluded.appearance",
                               (self.buyer['user']['id'],json.dumps(saved)))
                expected={**saved,'face_shape':new}
                self.assertEqual(self.me(self.buyer)['avatar'],expected)
                self.assertTrue(self.me(self.buyer)['profile_customized'])
                self.assertEqual(self.save(saved)['avatar'],expected)

    def test_profile_write_is_own_account_only_and_retries_replace_one_record(self):
        for _ in range(2):self.save()
        second={**self.chosen,'glasses':'square','expression':'happy'}
        self.save(second,self.other)
        self.assertEqual(self.me(self.buyer)['avatar'],self.chosen)
        self.assertEqual(self.me(self.other)['avatar'],second)
        self.save(second,self.staff)
        self.assertEqual(self.me(self.staff)['avatar'],second)
        with self.assertRaises(APIError) as error:self.call('POST','/api/profile',{'avatar':self.chosen})
        self.assertEqual(error.exception.status,401)
        with self.assertRaises(APIError) as error:
            self.call('POST','/api/profile',{'avatar':second,'user_id':self.other['user']['id']},self.buyer['token'])
        self.assertEqual(error.exception.status,400)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM user_profiles')['n'],3)

    def test_invalid_and_injected_choices_are_rejected_without_partial_changes(self):
        self.save()
        cases=[None,[],{}, {**self.chosen,'face_shape':None},{**self.chosen,'glasses':['round']},
               {**self.chosen,'hairpin':'<script>alert(1)</script>'},{**self.chosen,'hair_color':'https://example.com/photo.png'},
               {**self.chosen,'score':99999}, {k:v for k,v in self.chosen.items() if k!='skin'}]
        for avatar in cases:
            with self.subTest(avatar=avatar):
                with self.assertRaises(APIError) as error:
                    self.call('POST','/api/profile',{'avatar':avatar},self.buyer['token'])
                self.assertEqual(error.exception.status,400)
                self.assertEqual(self.me(self.buyer)['avatar'],self.chosen)
        self.assertEqual(self.me(self.buyer)['score'],0)

    def test_existing_database_adds_only_the_new_profile_table_and_keeps_sessions_and_orders(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=3 WHERE id=101')
        order=self.call('POST','/api/orders',{'items':[{'product_id':101,'quantity':1}],
                        'request_id':uuid.uuid4().hex},self.buyer['token'])['order']
        with self.app.db.transaction(write=True) as tx:
            tx.execute('DROP TABLE user_profiles')
        self.app=Application()
        self.assertFalse(self.me(self.buyer)['profile_customized'])
        self.assertEqual(self.call('GET','/api/orders',token=self.buyer['token'])['orders'][0]['id'],order['id'])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT stock FROM products WHERE id=101')['stock'],2)
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM user_profiles')['n'],0)
        self.assertEqual(self.save()['avatar'],self.chosen)

    def test_competing_updates_store_one_whole_profile(self):
        other={**self.chosen,'face_shape':'pound','expression':'happy','glasses':'round'}
        gate=threading.Barrier(2)
        def update(avatar):
            gate.wait(timeout=5)
            return self.save(avatar)['avatar']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            saved=list(pool.map(update,[self.chosen,other]))
        self.assertIn(self.me(self.buyer)['avatar'],saved)
        with self.app.db.transaction() as tx:
            rows=tx.all('SELECT appearance FROM user_profiles WHERE user_id=?',(self.buyer['user']['id'],))
            self.assertEqual(len(rows),1)
            self.assertIn(json.loads(rows[0]['appearance']),[self.chosen,other])
