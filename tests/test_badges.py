"""Earned badges are durable, account-scoped and separate from the selected badge."""
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


class BadgeTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='cambo-badges-')
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'app.db'
        env=dict(os.environ);env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(self.path),APP_ENV='development',DEMO_SEED='0',STAFF_PASSWORD='badge-test-password')
        settings=patch.dict(os.environ,env,clear=True);settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.call('/api/staff/login',{'name':'배지 담당','password':'badge-test-password'})
        self.buyer=self.call('/api/auth/register',{'name':'보유자','phone':'01011112222','pin':'1234'})
        self.other=self.call('/api/auth/register',{'name':'다른 보유자','phone':'01033334444','pin':'5678'})
        with self.app.db.transaction(write=True) as tx:
            tx.execute("UPDATE event_supplies SET stock=5 WHERE key='oatmeal'")
            tx.execute('UPDATE users SET score=10 WHERE id=?',(self.buyer['user']['id'],))

    def call(self,path,body=None,token=None,method='POST'):
        return self.app.handle(method,path,{},body or {},'Bearer '+token if token else None)

    def me(self,account=None):
        return self.call('/api/auth/me',token=(account or self.buyer)['token'],method='GET')['user']

    def claim(self,threshold,identity=None):
        return self.call('/api/rewards/claim',{'threshold':threshold,'request_id':identity or uuid.uuid4().hex},self.buyer['token'])

    def create(self,extra=None,identity=None):
        return self.call('/api/staff/badges',{'name':'특별 연금술사','description':'특별 이벤트를 완료하면 이 배지를 얻을 수 있어요.',
                         'icon':'star','request_id':identity or uuid.uuid4().hex,**(extra or {})},self.staff['token'])['badge']

    def grant(self,badge_id,account=None,identity=None,extra=None):
        return self.call('/api/staff/badge-grants',{'user_id':(account or self.buyer)['user']['id'],'badge_id':badge_id,
                         'reason':'이벤트 확인 완료','request_id':identity or uuid.uuid4().hex,**(extra or {})},self.staff['token'])

    def equip(self,badge_id,account=None,extra=None):
        account=account or self.buyer
        return self.call('/api/profile',{'avatar':self.me(account)['avatar'],'badge_id':badge_id,**(extra or {})},account['token'])['user']

    def count(self,table):
        with self.app.db.transaction() as tx:return tx.one(f'SELECT COUNT(*) AS n FROM {table}')['n']

    def test_new_accounts_show_locked_catalog_and_cannot_equip_unearned_badges(self):
        user=self.me()
        self.assertEqual([b['id'] for b in user['badges'] if b['rule']=='milestone'],['score_5','score_10'])
        self.assertEqual(sum(b['rule']=='achievement' for b in user['badges']),4)
        self.assertTrue(all(not b['owned'] and b['earned_at'] is None for b in user['badges']))
        self.assertIsNone(user['equipped_badge'])
        for badge_id in ('score_5','score_10','unknown'):
            with self.assertRaises(APIError) as error:self.equip(badge_id)
            self.assertEqual(error.exception.status,403)
        self.assertEqual(self.count('user_profiles'),0)
        self.assertEqual(self.count('user_badges'),0)  # Score alone is not a reward claim.

    def test_five_and_ten_point_claims_award_badges_once_with_source_and_original_time(self):
        identity=uuid.uuid4().hex
        first=self.claim(5,identity)
        self.assertEqual(self.claim(5,identity),first)
        self.claim(10)
        self.assertTrue(all(b['owned'] for b in self.me()['badges'] if b['rule']=='milestone'))
        self.assertIsNone(self.me()['equipped_badge'])
        with self.app.db.transaction() as tx:
            rows=tx.all('SELECT * FROM user_badges ORDER BY id')
            self.assertEqual(len(rows),2)
            for row in rows:
                claim=tx.one('SELECT * FROM milestone_claims WHERE id=?',(row['milestone_id'],))
                self.assertEqual(row['source'],'milestone')
                self.assertEqual(row['earned_at'],claim['created_at'])
                self.assertIsNone(row['granted_by'])
        self.app=Application()
        self.assertEqual(self.count('user_badges'),2)

    def test_failed_physical_reward_does_not_leave_a_badge_or_claim(self):
        with self.app.db.transaction(write=True) as tx:tx.execute("UPDATE event_supplies SET stock=0 WHERE key='oatmeal'")
        with self.assertRaises(APIError) as error:self.claim(5)
        self.assertEqual(error.exception.status,409)
        self.assertEqual((self.count('user_badges'),self.count('milestone_claims')),(0,0))

    def test_equipping_persists_one_badge_and_removing_it_keeps_ownership(self):
        self.claim(5);self.claim(10)
        avatar=self.me()['avatar']
        self.assertEqual(self.equip('score_5')['equipped_badge']['id'],'score_5')
        self.assertEqual(self.me()['equipped_badge']['id'],'score_5')
        self.app=Application()
        self.assertEqual(self.me()['equipped_badge']['id'],'score_5')
        self.equip('score_10')
        self.assertEqual(self.me()['equipped_badge']['id'],'score_10')
        # Old avatar-only clients preserve the selected badge.
        self.call('/api/profile',{'avatar':avatar},self.buyer['token'])
        self.assertEqual(self.me()['equipped_badge']['id'],'score_10')
        self.equip(None)
        self.assertIsNone(self.me()['equipped_badge'])
        self.assertEqual(self.count('user_badges'),2)
        self.assertEqual(self.me()['avatar'],avatar)

    def test_ownership_is_account_scoped_and_cannot_be_changed_in_a_profile_request(self):
        self.claim(5)
        with self.assertRaises(APIError) as error:self.equip('score_5',self.other)
        self.assertEqual(error.exception.status,403)
        with self.assertRaises(APIError) as error:self.equip('score_5',extra={'user_id':self.other['user']['id']})
        self.assertEqual(error.exception.status,400)
        self.assertTrue(all(not b['owned'] for b in self.me(self.other)['badges']))
        self.assertIsNone(self.me(self.other)['equipped_badge'])

    def test_rankings_show_only_equipped_badge_while_staff_can_track_owned_badges(self):
        self.claim(5);self.equip('score_5')
        board=self.call('/api/leaderboard',token=self.other['token'],method='GET')
        entry=next(row for row in board['leaders'] if row['id']==self.buyer['user']['id'])
        self.assertEqual(entry['equipped_badge'],{'id':'score_5','name':'마법의 씨앗','icon':'spark'})
        self.assertNotIn('badges',entry)
        self.assertNotIn('earned_badges',entry)
        staff=self.call('/api/staff/dashboard',token=self.staff['token'],method='GET')
        user=next(row for row in staff['users'] if row['id']==self.buyer['user']['id'])
        self.assertTrue(next(b for b in user['badges'] if b['id']=='score_5')['owned'])
        self.assertFalse(next(b for b in user['badges'] if b['id']=='score_10')['owned'])

    def test_staff_can_add_and_grant_a_badge_without_changing_progress_sales_or_inventory(self):
        before=self.me()
        identity=uuid.uuid4().hex
        badge=self.create(identity=identity)
        self.assertEqual(self.create(identity=identity),badge)
        self.assertEqual(badge['rule'],'manual')
        self.assertFalse(next(b for b in self.me()['badges'] if b['id']==badge['id'])['owned'])
        identity=uuid.uuid4().hex
        grant=self.grant(badge['id'],identity=identity)
        self.assertEqual(self.grant(badge['id'],identity=identity),grant)
        record=grant['grant']
        self.assertEqual((record['source'],record['granted_by'],record['reason']),('manual',self.staff['user']['id'],'이벤트 확인 완료'))
        self.assertIsNone(record['milestone_id'])
        self.assertEqual(self.equip(badge['id'])['equipped_badge']['id'],badge['id'])
        after=self.me()
        for key in ('score','dice_balance','rewards_claimed','claimed_milestones'):self.assertEqual(before[key],after[key])
        for table in ('orders','inventory_logs','reward_requests'):self.assertEqual(self.count(table),0)
        history=self.call('/api/staff/dashboard',token=self.staff['token'],method='GET')['badge_grants']
        self.assertEqual((history[0]['id'],history[0]['item_name'],history[0]['staff_name']),
                         (record['id'],badge['name'],'배지 담당'))

    def test_duplicate_manual_grants_cannot_create_multiple_ownership_records(self):
        badge=self.create()
        def give(_):
            try:self.grant(badge['id']);return 200
            except APIError as error:return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(give,range(2))),[200,409])
        self.assertEqual(self.count('user_badges'),1)
        self.grant(badge['id'],self.other)
        self.assertEqual(self.count('user_badges'),2)

    def test_staff_endpoints_reject_buyers_guests_and_invalid_definitions(self):
        for token,status in ((None,401),(self.buyer['token'],403)):
            for path in ('/api/staff/badges','/api/staff/badge-grants'):
                with self.assertRaises(APIError) as error:self.call(path,{},token)
                self.assertEqual(error.exception.status,status)
        for extra in ({'name':''},{'name':'x'*41},{'description':''},{'description':'x'*241},
                      {'icon':'https://bad.example/icon.svg'},{'rule':'milestone','threshold':1}):
            with self.assertRaises(APIError):self.create(extra)
        self.assertEqual(self.count('badges'),6)
        for extra in ({'guest':True,'name':'비회원'},{'reason':''},{'badge_id':'missing'},
                      {'user_id':self.staff['user']['id']}):
            with self.assertRaises(APIError):self.grant('score_5',extra=extra)
        self.assertEqual(self.count('user_badges'),0)

    def test_public_profiles_hide_a_forged_unearned_equipped_badge(self):
        self.equip(None)
        with self.app.db.transaction(write=True) as tx:tx.execute("UPDATE user_profiles SET badge_id='score_10' WHERE user_id=?",(self.buyer['user']['id'],))
        self.assertIsNone(self.me()['equipped_badge'])
        board=self.call('/api/leaderboard',token=self.other['token'],method='GET')
        self.assertTrue(all(row['equipped_badge'] is None for row in board['leaders']))

    def test_previous_schema_migrates_without_losing_profiles_sessions_or_claims_and_backfills_once(self):
        old=self.path.parent/'old.db'
        schema=re.sub(r'CREATE TABLE IF NOT EXISTS badges \([\s\S]*?\n\);\n','',SCHEMA)
        schema=re.sub(r'CREATE TABLE IF NOT EXISTS user_badges \([\s\S]*?\n\);\n','',schema)
        schema=schema.replace(' badge_id TEXT REFERENCES badges(id),\n','')
        avatar=self.me()['avatar'];stamp='2026-11-01T00:00:00Z'
        with sqlite3.connect(old) as conn:
            conn.executescript(schema)
            conn.execute("INSERT INTO users(id,name,phone,role,password_hash,score,created_at) VALUES(1,'기존','010-5555-6666','buyer','hash',9,?)",(stamp,))
            conn.execute('INSERT INTO user_profiles(user_id,appearance,updated_at) VALUES(1,?,?)',(json.dumps(avatar),stamp))
            conn.execute('INSERT INTO sessions VALUES(?,1,?)',(hashlib.sha256(b'a'*40).hexdigest(),'2999-01-01T00:00:00Z'))
            conn.execute("INSERT INTO milestone_claims(user_id,threshold,kind,product_name,created_at) VALUES(1,5,'oatmeal','오트밀',?)",(stamp,))
        with patch.dict(os.environ,{'DB_PATH':str(old)}):
            self.app=Application()
            for _ in range(2):self.app=Application()
            user=self.call('/api/auth/me',token='a'*40,method='GET')['user']
            self.assertEqual(user['avatar'],avatar)
            self.assertEqual((user['score'],user['claimed_milestones']),(9,[5]))
            self.assertTrue(next(b for b in user['badges'] if b['id']=='score_5')['owned'])
            self.assertIsNone(user['equipped_badge'])
            with self.app.db.transaction() as tx:
                self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM user_badges')['n'],1)
                self.assertEqual(tx.one('SELECT earned_at FROM user_badges')['earned_at'],stamp)
                self.assertEqual(tx.one('SELECT updated_at FROM user_profiles')['updated_at'],stamp)
                self.assertEqual(tx.all('PRAGMA foreign_key_check'),[])


if __name__=='__main__':
    unittest.main()
