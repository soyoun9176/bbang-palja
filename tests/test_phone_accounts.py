"""Phone identifiers, strict normalization, privacy and explicit DB recreation."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reset_database',ROOT/'ops/reset-db.py')
reset=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


class PhoneAccountTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-phone-')
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'app.db'
        env=dict(os.environ)
        env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(self.path),APP_ENV='development',DEMO_SEED='0',STAFF_PASSWORD='test-phone-password')
        settings=patch.dict(os.environ,env,clear=True);settings.start();self.addCleanup(settings.stop)
        self.app=Application()

    def call(self,path,body=None,token=None,method='POST',query=None):
        return self.app.handle(method,path,query or {},body or {},'Bearer '+token if token else None)

    def register(self,phone='01012345678',name='같은 닉네임'):
        return self.call('/api/auth/register',{'name':name,'phone':phone,'pin':'1234'})

    def test_phone_is_the_unique_identifier_and_nicknames_may_repeat(self):
        first=self.register();second=self.register('01098765432')
        self.assertEqual(first['user']['name'],second['user']['name'])
        self.assertNotEqual(first['user']['id'],second['user']['id'])
        for phone in ['01012345678','010-1234-5678']:
            logged=self.call('/api/auth/login',{'phone':phone,'pin':'1234'})
            self.assertEqual(logged['user']['id'],first['user']['id'])
        with self.assertRaises(APIError) as error:self.register('010-1234-5678','다른 닉네임')
        self.assertEqual(error.exception.status,409)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT phone FROM users WHERE id=?',(first['user']['id'],))['phone'],'010-1234-5678')

    def test_invalid_formats_and_non_ascii_characters_are_rejected(self):
        invalid=[None,12345678,True,'','0101234567','010123456789','01112345678','+821012345678',
                 '010 1234 5678',' 01012345678','01012345678 ','01012345678\n','010-12345678','0101234-5678',
                 '010--1234-5678','010-123-45678','010-1234-567a','010(1234)5678','０１０１２３４５６７８','010−1234−5678']
        for phone in invalid:
            with self.subTest(phone=phone):
                with self.assertRaises(APIError) as error:self.register(phone)
                self.assertEqual(error.exception.status,400)
        with self.app.db.transaction() as tx:self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM users')['n'],0)

    def test_missing_phone_and_bad_login_do_not_fall_back_to_nickname(self):
        self.register()
        for body,status in [({'name':'같은 닉네임','pin':'1234'},400),({'phone':'01012345678','pin':'4321'},401),({'phone':'01011112222','pin':'1234'},401)]:
            with self.assertRaises(APIError) as error:self.call('/api/auth/login',body)
            self.assertEqual(error.exception.status,status)

    def test_phone_is_hidden_from_buyer_responses_and_cannot_be_changed_in_profile(self):
        account=self.register();token=account['token']
        self.assertNotIn('phone',account['user'])
        self.assertNotIn('phone',self.call('/api/auth/me',token=token,method='GET')['user'])
        board=self.call('/api/leaderboard',token=token,method='GET')
        self.assertTrue(all('phone' not in person for person in board['leaders']))
        avatar=account['user']['avatar']
        with self.assertRaises(APIError) as error:self.call('/api/profile',{'avatar':avatar,'phone':'010-9999-9999'},token)
        self.assertEqual(error.exception.status,400)
        staff=self.call('/api/staff/login',{'name':'같은 닉네임','password':'test-phone-password'})
        users=self.call('/api/staff/dashboard',token=staff['token'],method='GET')['users']
        self.assertEqual(users[0]['phone'],'010-1234-5678')

    def test_reservation_ownership_uses_account_phone_not_nickname(self):
        account=self.register();other=self.register('01011112222')
        staff=self.call('/api/staff/login',{'name':'담당','password':'test-phone-password'})['token']
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=2 WHERE id=101')
        self.call('/api/staff/preorders/import',{'reservations':[{'name':'예약한 실명','phone':'01012345678','items':[{'product_id':101,'quantity':1}]}]},staff)
        found=self.call('/api/preorders/lookup',token=account['token'],method='GET',query={'name':['예약한 실명']})['reservation']
        self.assertNotIn('phone',found)
        with self.assertRaises(APIError) as error:self.call('/api/preorders/lookup',token=other['token'],method='GET',query={'name':['예약한 실명']})
        self.assertEqual(error.exception.status,404)
        with self.assertRaises(APIError) as error:self.call(f"/api/preorders/{found['id']}/claim",{'request_id':uuid.uuid4().hex},other['token'])
        self.assertEqual(error.exception.status,404)
        result=self.call(f"/api/preorders/{found['id']}/claim",{'request_id':uuid.uuid4().hex},account['token'])
        self.assertEqual(result['order']['user_id'],account['user']['id'])


class DatabaseResetTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='bbang-reset-');self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'legacy.sqlite3'
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT)')
            c.execute("INSERT INTO users VALUES(7,'기존 기록')")
        env=dict(os.environ);env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(self.path),APP_ENV='development',DEMO_SEED='0',STAFF_PASSWORD='test-phone-password')
        settings=patch.dict(os.environ,env,clear=True);settings.start();self.addCleanup(settings.stop)

    def test_old_schema_refuses_automatic_mutation_then_explicit_reset_backs_up_and_rebuilds(self):
        with self.assertRaisesRegex(RuntimeError,'재생성'):Application()
        with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT * FROM users').fetchall(),[(7,'기존 기록')])
        result=reset.rebuild()
        with sqlite3.connect(result['backup']) as c:self.assertEqual(c.execute('SELECT * FROM users').fetchall(),[(7,'기존 기록')])
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM products').fetchone()[0],13)
            self.assertEqual(c.execute('SELECT SUM(stock) FROM products').fetchone()[0],0)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(Path(result['backup']).stat().st_mode&0o777,0o600)
        Application()

    def test_cli_requires_explicit_yes_and_failed_preparation_keeps_original(self):
        run=subprocess.run([sys.executable,str(ROOT/'ops/reset-db.py')],env=os.environ.copy(),capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
        with patch.object(reset,'Application',side_effect=RuntimeError('준비 실패')):
            with self.assertRaises(RuntimeError):reset.rebuild()
        with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT * FROM users').fetchall(),[(7,'기존 기록')])

    def test_cli_uses_env_file_without_printing_credentials(self):
        env_file=self.path.parent/'api.env'
        env_file.write_text(f'DB_PATH={self.path}\nAPP_ENV=development\nSTAFF_PASSWORD=not-for-output\n')
        run=subprocess.run([sys.executable,str(ROOT/'ops/reset-db.py'),'--yes','--env-file',str(env_file)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertNotIn('not-for-output',run.stdout+run.stderr)
        self.assertEqual(json.loads(run.stdout)['mode'],'empty')
