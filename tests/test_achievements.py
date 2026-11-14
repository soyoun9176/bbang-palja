"""Approval-based achievements, unique first arrivals, and owned profile titles."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application
from server.db import SCHEMA


class AchievementTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='cambo-achievement-test-');self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'app.db'
        env=dict(os.environ);env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(self.path),APP_ENV='development',DEMO_SEED='0',STAFF_PASSWORD='title-test')
        settings=patch.dict(os.environ,env,clear=True);settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.call('/api/staff/login',{'name':'도전과제 담당','password':'title-test'})
        self.buyer=self.register('구매자','01011112222')
        self.other=self.register('다른 구매자','01033334444')
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=100')
            tx.execute("UPDATE sessions SET expires_at='2999-01-01T00:00:00Z'")
            tx.execute("UPDATE event_supplies SET stock=10 WHERE key='oatmeal'")

    def call(self,path,body=None,account=None,method='POST',query=None):
        return self.app.handle(method,path,query or {},body or {},'Bearer '+account['token'] if account else None)

    def register(self,name,phone):
        return self.call('/api/auth/register',{'name':name,'phone':phone,'pin':'1234'})

    def me(self,account=None):
        return self.call('/api/auth/me',account=account or self.buyer,method='GET')['user']

    def order(self,items,account=None,stamp=None):
        with patch('server.app.now',return_value=stamp) if stamp else patch('server.app.now',wraps=__import__('server.app',fromlist=['now']).now):
            return self.call('/api/orders',{'items':[{'product_id':pid,'quantity':n} for pid,n in items],
                             'request_id':uuid.uuid4().hex},account or self.buyer)['order']

    def process(self,order,action='approve'):
        return self.call(f"/api/staff/orders/{order['id']}/{action}",{},self.staff)['order']

    def owned(self,kind,account=None):
        return {r['id'] for r in self.me(account)[kind] if r['owned']}

    def count(self,table):
        with self.app.db.transaction() as tx:return tx.one(f'SELECT COUNT(*) AS n FROM {table}')['n']

    def equip(self,title_id,account=None,extra=None):
        account=account or self.buyer
        return self.call('/api/profile',{'avatar':self.me(account)['avatar'],'title_id':title_id,**(extra or {})},account)['user']

    def claim(self,threshold,identity=None):
        return self.call('/api/rewards/claim',{'threshold':threshold,'request_id':identity or uuid.uuid4().hex},self.buyer)

    def test_pending_cancelled_and_free_items_do_not_earn_purchase_rewards(self):
        order=self.order([(101,5)])
        self.assertNotIn('focus_101',self.owned('titles'))
        self.process(order,'cancel')
        self.call('/api/staff/manual-event-grants',{'user_id':self.buyer['user']['id'],'kind':'bread','product_id':101,
                  'quantity':5,'reason':'보상','request_id':uuid.uuid4().hex},self.staff)
        self.assertEqual(self.owned('titles'),set())
        self.assertTrue(all(a['current']==0 for a in self.me()['achievements']))

    def test_approved_cumulative_counts_unlock_each_focus_title_but_one_focus_badge(self):
        self.process(self.order([(101,2)]))
        self.process(self.order([(101,3)]))
        self.assertIn('focus_101',self.owned('titles'))
        self.assertIn('ach_focus',self.owned('badges'))
        self.process(self.order([(102,5)]))
        self.assertTrue({'focus_101','focus_102'}<=self.owned('titles'))
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM user_badges WHERE badge_id='ach_focus'")['n'],1)
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM user_achievements WHERE achievement_key='focus'")['n'],2)
        self.app=Application()
        self.assertTrue({'focus_101','focus_102'}<=self.owned('titles'))

    def test_financier_four_kinds_and_all_breads_ignore_drinks_and_award_gold_vvip(self):
        self.process(self.order([(pid,1) for pid in range(101,105)]+[(112,5),(113,5)]))
        self.assertIn('elements',self.owned('titles'))
        self.assertNotIn('vvip',self.owned('titles'))
        progress={a['id']:a for a in self.me()['achievements']}
        self.assertEqual(progress['all_breads']['current'],4)
        self.process(self.order([(pid,1) for pid in range(105,112)]))
        user=self.me()
        self.assertTrue({'ach_elements','ach_vvip'}<=self.owned('badges'))
        self.assertEqual(user['equipped_title'],{'id':'vvip','name':'캄딜 VVIP','style':'gold'})
        self.assertTrue(all(a['completed'] for a in user['achievements'][:2]))
        self.process(self.order([(109,4)]))
        self.assertEqual(self.me()['equipped_title']['id'],'vvip')

    def test_preorder_counts_combine_with_walkin_but_application_rank_is_not_pickup_rank(self):
        reservations=[{'name':f'예약{i}','phone':f'0105555{i:04d}','items':[{'product_id':101,'quantity':3}]} for i in range(11)]
        self.call('/api/staff/preorders/import',{'reservations':reservations,'request_id':uuid.uuid4().hex},self.staff)
        with self.app.db.transaction() as tx:rows=tx.all('SELECT * FROM reservations ORDER BY id')
        for index,account in ((10,self.buyer),(0,self.other)):
            row=rows[index]
            self.call(f"/api/staff/preorders/{row['id']}/complete",{'name':row['name'],'phone':row['phone'],
                      'user_id':account['user']['id'],'request_id':uuid.uuid4().hex},self.staff)
        self.assertNotIn('fast',self.owned('titles'))
        self.assertIn('fast',self.owned('titles',self.other))
        self.process(self.order([(101,2)]))
        self.assertIn('focus_101',self.owned('titles'))
        self.assertEqual(next(a for a in self.me()['achievements'] if a['id']=='focus')['current'],5)

    def test_vvip_replaces_an_older_gold_title_but_restart_keeps_a_later_user_choice(self):
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE users SET score=30 WHERE id=?',(self.buyer['user']['id'],))
        self.claim(30)
        self.assertEqual(self.me()['equipped_title']['id'],'score_30')
        self.process(self.order([(pid,1) for pid in range(101,112)]))
        self.assertEqual(self.me()['equipped_title']['id'],'vvip')
        self.equip('elements');self.app=Application()
        self.assertEqual(self.me()['equipped_title']['id'],'elements')

    def test_duplicate_reservation_phone_occupies_one_of_ten_people(self):
        with self.app.db.transaction(write=True) as tx:
            for i in range(11):
                tx.execute('INSERT INTO reservations(name,phone,created_at) VALUES(?,?,?)',
                           (f'동명이인{i}','010-5555-0000' if i<2 else f'010-5555-{i:04d}',f'2026-11-01T00:00:{i:02d}Z'))
            target=tx.one('SELECT * FROM reservations ORDER BY id DESC LIMIT 1')
            tx.execute('INSERT INTO reservation_items(reservation_id,product_id,quantity,price) VALUES(?,101,1,2800)',(target['id'],))
            tx.execute('UPDATE products SET preorder_stock=1 WHERE id=101')
        self.call(f"/api/staff/preorders/{target['id']}/complete",{'name':target['name'],'phone':target['phone'],
                  'user_id':self.buyer['user']['id'],'request_id':uuid.uuid4().hex},self.staff)
        self.assertIn('fast',self.owned('titles'))
        fast=[a for a in self.me()['achievements'] if a['id']=='fast']
        self.assertEqual(len(fast),1)
        self.assertEqual((fast[0]['name'],fast[0]['completed'],fast[0]['current']),('우사인볼트 연금술사',True,1))

    def test_first_order_waits_for_earlier_pending_and_cancel_releases_daily_award(self):
        first=self.order([(101,1)],stamp='2026-11-20T15:00:00Z')
        second=self.order([(102,1)],self.other,stamp='2026-11-20T15:01:00Z')
        self.process(second)
        self.assertNotIn('fast',self.owned('titles',self.other))
        self.process(first,'cancel')
        self.assertIn('fast',self.owned('titles',self.other))
        with self.app.db.transaction() as tx:
            row=tx.one("SELECT * FROM user_achievements WHERE achievement_key='walkin_fast'")
            self.assertEqual((row['user_id'],row['scope'],row['order_id']),
                             (self.other['user']['id'],'2026-11-21',second['id']))

    def test_concurrent_approvals_award_only_first_order_once(self):
        first=self.order([(101,1)],stamp='2026-11-20T01:00:00Z')
        second=self.order([(102,1)],self.other,stamp='2026-11-20T01:00:01Z')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.process,[second,first]))
        self.process(first)
        self.assertIn('fast',self.owned('titles'))
        self.assertNotIn('fast',self.owned('titles',self.other))
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM user_achievements WHERE achievement_key='walkin_fast'")['n'],1)

    def test_korean_midnight_splits_days_and_repeat_win_preserves_history_without_duplicate_rewards(self):
        self.process(self.order([(101,1)],stamp='2026-11-20T14:59:59Z'))
        self.process(self.order([(101,1)],stamp='2026-11-20T15:00:00Z'))
        fast=[a for a in self.me()['achievements'] if a['id']=='fast']
        self.assertEqual(len(fast),1)
        self.assertTrue(fast[0]['completed'])
        self.assertEqual(fast[0]['dates'],['2026-11-20','2026-11-21'])
        with self.app.db.transaction() as tx:
            self.assertEqual([r['scope'] for r in tx.all("SELECT scope FROM user_achievements WHERE achievement_key='walkin_fast' ORDER BY scope")],['2026-11-20','2026-11-21'])
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM user_titles WHERE title_id='fast'")['n'],1)
            self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM user_badges WHERE badge_id='ach_fast'")['n'],1)

    def test_guest_first_purchase_occupies_slot_and_drink_only_orders_do_not(self):
        self.call('/api/staff/manual-sale',{'guest':True,'name':'비회원','items':[{'product_id':101,'quantity':5}],
                  'request_id':uuid.uuid4().hex},self.staff)
        self.process(self.order([(102,1)]))
        self.assertNotIn('fast',self.owned('titles'))
        self.assertEqual(self.count('users'),3)
        self.assertEqual(self.count('user_achievements'),0)
        drink=self.order([(112,5)],stamp='2026-12-01T00:00:00Z')
        bread=self.order([(101,1)],self.other,stamp='2026-12-01T00:00:01Z')
        self.process(bread)
        self.assertIn('fast',self.owned('titles',self.other))
        self.process(drink)
        self.assertNotIn('focus_112',self.owned('titles'))

    def test_score_claim_titles_are_atomic_and_idempotent_and_unequip_is_durable(self):
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE users SET score=30 WHERE id=?',(self.buyer['user']['id'],))
        identity=uuid.uuid4().hex
        self.assertEqual(self.claim(15,identity),self.claim(15,identity))
        self.assertEqual(self.me()['equipped_title']['id'],'score_15')
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=0 WHERE id BETWEEN 101 AND 111')
        with self.assertRaises(APIError):self.claim(30)
        self.assertNotIn('score_30',self.owned('titles'))
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=5 WHERE id=101')
        self.claim(30)
        self.assertEqual(self.me()['equipped_title']['id'],'score_30')
        self.equip('score_15')
        self.call('/api/profile',{'avatar':self.me()['avatar']},self.buyer)
        self.assertEqual(self.me()['equipped_title']['id'],'score_15')
        self.equip(None);self.app=Application()
        self.assertIsNone(self.me()['equipped_title'])
        self.assertTrue({'score_15','score_30'}<=self.owned('titles'))

    def test_title_equip_requires_ownership_and_public_entries_do_not_disclose_achievements(self):
        self.process(self.order([(101,5)]))
        self.equip('focus_101')
        for account,title_id,extra in ((self.other,'focus_101',{}),(self.buyer,'vvip',{}),
                                       (self.buyer,'focus_101',{'user_id':self.other['user']['id']})):
            with self.assertRaises(APIError):self.equip(title_id,account,extra)
        board=self.call('/api/leaderboard',account=self.other,method='GET')
        row=next(r for r in board['leaders'] if r['id']==self.buyer['user']['id'])
        self.assertEqual(row['equipped_title']['name'],'플레인 휘낭시에 몰입가')
        for key in ('titles','earned_titles','achievements','phone','badge_catalog'):self.assertNotIn(key,row)
        with self.app.db.transaction(write=True) as tx:tx.execute("UPDATE user_profiles SET title_id='vvip' WHERE user_id=?",(self.buyer['user']['id'],))
        self.assertIsNone(self.me()['equipped_title'])

    def test_staff_custom_titles_have_audit_and_reject_guest_buyer_duplicates_and_unknown_styles(self):
        body={'name':'커스텀 대현자','description':'30점 보상 후 담당자에게 요청','style':'gold','request_id':uuid.uuid4().hex}
        title=self.call('/api/staff/titles',body,self.staff)['title']
        self.assertEqual(self.call('/api/staff/titles',body,self.staff)['title'],title)
        grant={'user_id':self.buyer['user']['id'],'title_id':title['id'],'reason':'30점 이름 정하기','request_id':uuid.uuid4().hex}
        first=self.call('/api/staff/title-grants',grant,self.staff)
        self.assertEqual(self.call('/api/staff/title-grants',grant,self.staff),first)
        self.assertEqual(self.me()['equipped_title']['name'],title['name'])
        self.assertEqual(first['grant']['source'],'manual')
        for path,data,account in (('/api/staff/titles',body,self.buyer),('/api/staff/title-grants',grant,self.buyer),
                                  ('/api/staff/title-grants',{**grant,'guest':True},self.staff),
                                  ('/api/staff/titles',{**body,'style':'url(x)','request_id':uuid.uuid4().hex},self.staff),
                                  ('/api/staff/title-grants',{**grant,'request_id':uuid.uuid4().hex},self.staff)):
            with self.assertRaises(APIError):self.call(path,data,account)
        dashboard=self.call('/api/staff/dashboard',account=self.staff,method='GET')
        self.assertEqual(dashboard['title_grants'][0]['reason'],'30점 이름 정하기')
        self.assertEqual(self.me()['score'],0)
        self.assertEqual(self.count('orders'),0)

    def test_previous_badge_schema_migrates_ownership_and_sequence_without_reset(self):
        old=self.path.parent/'old-badges.db'
        old_badges="""CREATE TABLE IF NOT EXISTS badges (
 id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
 icon TEXT NOT NULL CHECK (icon IN ('spark','flask','star','heart','bread','trophy')),
 rule TEXT NOT NULL CHECK (rule IN ('milestone','manual')),threshold INTEGER,
 created_at TEXT NOT NULL,created_by INTEGER REFERENCES users(id),
 CHECK ((rule='milestone' AND threshold IS NOT NULL AND threshold>0) OR (rule='manual' AND threshold IS NULL))
);"""
        old_ownership="""CREATE TABLE IF NOT EXISTS user_badges (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),badge_id TEXT NOT NULL REFERENCES badges(id),
 source TEXT NOT NULL CHECK (source IN ('milestone','manual')),milestone_id INTEGER REFERENCES milestone_claims(id),
 granted_by INTEGER REFERENCES users(id),reason TEXT NOT NULL,earned_at TEXT NOT NULL,UNIQUE(user_id,badge_id),
 CHECK ((source='milestone' AND milestone_id IS NOT NULL AND granted_by IS NULL) OR (source='manual' AND milestone_id IS NULL AND granted_by IS NOT NULL))
);"""
        schema=SCHEMA
        for table in ('titles','user_titles','user_achievements'):
            schema=re.sub(r'CREATE TABLE IF NOT EXISTS '+table+r' \([\s\S]*?\n\);\n','',schema)
        schema=schema.replace(' title_id TEXT REFERENCES titles(id),\n','')
        for table,ddl in (('badges',old_badges),('user_badges',old_ownership)):
            schema=re.sub(r'CREATE TABLE IF NOT EXISTS '+table+r' \([\s\S]*?\n\);',ddl,schema)
        stamp='2026-11-01T00:00:00Z';avatar=self.me()['avatar']
        with sqlite3.connect(old) as c:
            c.executescript(schema)
            c.execute("INSERT INTO users(id,name,phone,role,password_hash,created_at) VALUES(1,'기존','010-5555-6666','buyer','hash',?)",(stamp,))
            c.execute("INSERT INTO users(id,name,role,password_hash,created_at) VALUES(2,'담당','staff','',?)",(stamp,))
            c.execute("INSERT INTO badges VALUES('old','기존 배지','이전 행사','star','manual',NULL,?,2)",(stamp,))
            c.execute("INSERT INTO user_badges VALUES(7,1,'old','manual',NULL,2,'직접 확인',?)",(stamp,))
            c.execute("UPDATE sqlite_sequence SET seq=42 WHERE name='user_badges'")
            c.execute("INSERT INTO user_profiles VALUES(1,?,'old',?)",(json.dumps(avatar),stamp))
            c.execute('INSERT INTO sessions VALUES(?,1,?)',(hashlib.sha256(b'a'*40).hexdigest(),'2999-01-01T00:00:00Z'))
            c.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(1,15,'sunglasses','선글라스',?)",(stamp,))
        with patch.dict(os.environ,{'DB_PATH':str(old)}):
            for _ in range(2):self.app=Application()
            user=self.me({'token':'a'*40})
            self.assertEqual(user['avatar'],avatar)
            self.assertEqual(user['equipped_badge']['id'],'old')
            self.assertEqual(user['equipped_title']['id'],'score_15')
            with self.app.db.transaction() as tx:
                self.assertEqual(tx.one("SELECT * FROM user_badges WHERE id=7")['reason'],'직접 확인')
                self.assertEqual(tx.one("SELECT earned_at FROM user_titles")['earned_at'],stamp)
                self.assertEqual(tx.one("SELECT seq FROM sqlite_sequence WHERE name='user_badges'")['seq'],42)
                self.assertEqual(tx.all('PRAGMA foreign_key_check'),[])


if __name__=='__main__':unittest.main()
