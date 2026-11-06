"""Typed dice issuance, server-side outcomes, migration and double-spend checks."""
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application, grant_dice
from server.game import preorder_kind


class TypedDiceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='bbang-dice-')
        self.addCleanup(folder.cleanup)
        environment = dict(os.environ)
        environment.pop('DATABASE_URL', None)
        environment.update(DB_PATH=str(Path(folder.name)/'app.db'), APP_ENV='production',
                           DEMO_SEED='0', STAFF_PASSWORD='dice-test-password', ALLOWED_ORIGINS='')
        settings = patch.dict(os.environ, environment, clear=True)
        settings.start(); self.addCleanup(settings.stop)
        self.app = Application()
        self.staff = self.call('POST', '/api/staff/login', {'name':'검증 담당', 'password':'dice-test-password'})['token']
        self.buyer = self.call('POST', '/api/auth/register', {'name':'검증 구매자', 'pin':'1234'})

    def call(self, method, path, body=None, token=None):
        return self.app.handle(method, path, {}, body or {}, 'Bearer '+token if token else None)

    def me(self):
        return self.call('GET', '/api/auth/me', token=self.buyer['token'])['user']

    def grant(self, kind, quantity):
        with self.app.db.transaction(write=True) as tx:
            grant_dice(tx, self.buyer['user']['id'], kind, quantity)

    def roll(self, kind, identity=None, **extra):
        return self.call('POST', '/api/dice/roll', {'kind':kind,'request_id':identity or uuid.uuid4().hex,**extra}, self.buyer['token'])

    def test_preorder_amount_boundaries(self):
        for amount, expected in [(1,'plain'),(5000,'plain'),(5001,'rainbow'),(10000,'rainbow'),
                                 (10001,'silver'),(20000,'silver'),(20001,'gold')]:
            self.assertEqual(preorder_kind(amount), 'preorder_'+expected)

    def test_actual_preorder_is_one_die_while_manual_walkin_is_per_bread(self):
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=30 WHERE id IN (101,112)')
        self.call('POST','/api/staff/preorders/import',{'reservations':[{'name':'예약인','phone':'01012345678',
                  'items':[{'product_id':101,'quantity':8}]}]},self.staff)
        reservation=self.call('GET','/api/staff/dashboard',token=self.staff)['reservations'][0]
        body={'name':reservation['name'],'phone':reservation['phone'],'user_id':self.buyer['user']['id'],'request_id':uuid.uuid4().hex}
        result=self.call('POST',f"/api/staff/preorders/{reservation['id']}/complete",body,self.staff)
        self.assertEqual((result['order']['dice_quantity'],result['order']['dice']['kind']),(1,'preorder_gold'))
        self.call('POST',f"/api/staff/preorders/{reservation['id']}/complete",body,self.staff)
        self.call('POST','/api/staff/manual-sale',{'user_id':self.buyer['user']['id'],
                  'items':[{'product_id':101,'quantity':3},{'product_id':112,'quantity':2}],
                  'request_id':uuid.uuid4().hex},self.staff)
        self.assertEqual({d['kind']:d['quantity'] for d in self.me()['dice']},{'walkin':3,'preorder_gold':1})
        self.assertEqual(self.me()['dice_balance'],4)

    def test_all_six_faces_are_server_selected_including_high_scores_and_milk(self):
        expected={
            'walkin':(1,2,3,3,4,5), 'preorder_plain':(1,2,3,4,5,6),
            'preorder_rainbow':(2,2,3,5,6,12), 'preorder_silver':(3,5,7,9,11,18),
            'preorder_gold':('milk',6,9,11,15,22), 'instagram':(1,1,2,2,3,'milk'),
        }
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=3 WHERE id=112')
        total=0
        for kind, faces in expected.items():
            self.grant(kind,6)
            for index, face in enumerate(faces):
                with patch('server.app.secrets.randbelow',return_value=index) as draw:
                    result=self.roll(kind)
                draw.assert_called_once_with(6)
                total+=0 if face=='milk' else face
                self.assertEqual((result['result'],result['value']),('milk',0) if face=='milk' else ('score',face))
                self.assertEqual(result['score'],total)
        self.assertEqual(self.me()['dice_balance'],0)
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM typed_dice_rolls')['n'],36)
            self.assertEqual(tx.one('SELECT stock FROM products WHERE id=112')['stock'],1)
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM dice_rolls')['n'],0)

    def test_forged_kind_and_client_result_cannot_spend_other_dice(self):
        self.grant('walkin',1)
        for kind, extra, status in [('preorder_gold',{},409),('madeup',{},400),('walkin',{'value':22},400)]:
            with self.assertRaises(APIError) as error:self.roll(kind,**extra)
            self.assertEqual(error.exception.status,status)
        self.assertEqual((self.me()['dice_balance'],self.me()['score']),(1,0))

    def test_retry_and_concurrent_rolls_consume_one_die_once(self):
        self.grant('preorder_silver',1)
        gate=threading.Barrier(2)
        def compete(_):
            gate.wait(timeout=5)
            try:return 200,self.roll('preorder_silver')
            except APIError as error:return error.status,None
        with patch('server.app.secrets.randbelow',return_value=5):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(compete,range(2)))
        self.assertEqual(sorted(s for s,_ in results),[200,409])
        self.assertEqual((self.me()['score'],self.me()['dice_balance']),(18,0))
        self.grant('walkin',1);identity=uuid.uuid4().hex
        first=self.roll('walkin',identity)
        self.assertEqual(self.roll('walkin',identity),first)
        self.assertEqual(self.me()['dice_balance'],0)

    def test_public_metadata_never_contains_face_tables_or_price_bands(self):
        self.grant('preorder_gold',1)
        data=json.dumps([self.call('GET','/api/config'),self.me()],ensure_ascii=False)
        for secret in ['faces','5000','10000','20000','22']:
            self.assertNotIn(secret,data)
        self.assertIn('준비된 마법사의 주사위',data)
        self.assertIn('인싸 마법사의 주사위',data)

    def test_legacy_balance_and_history_migrate_once_without_reset(self):
        user_id=self.buyer['user']['id']
        with self.app.db.transaction(write=True) as tx:
            tx.execute("DELETE FROM settings WHERE key='typed_dice_v1'")
            tx.execute('UPDATE users SET score=17,dice_balance=4,rewards_claimed=1 WHERE id=?',(user_id,))
            tx.execute("INSERT INTO dice_rolls(user_id,value,created_at) VALUES(?,6,'2026-11-06')",(user_id,))
            tx.execute("INSERT INTO rewards(user_id,product_id,product_name,threshold,created_at) VALUES(?,101,'기존 빵',10,'2026-11-06')",(user_id,))
        self.app=Application();self.app=Application()
        self.assertEqual((self.me()['score'],self.me()['dice_balance']),(17,4))
        self.assertEqual([(d['kind'],d['quantity']) for d in self.me()['dice']],[('walkin',4)])
        records=self.call('GET','/api/rewards',token=self.buyer['token'])['rewards']
        self.assertEqual(records[0]['kind'],'legacy_bread')
        with self.app.db.transaction() as tx:self.assertEqual(tx.one('SELECT value FROM dice_rolls')['value'],6)
