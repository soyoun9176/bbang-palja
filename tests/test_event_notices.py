"""Shared two-notice board, one-time achievement broadcasts, and staff announcements."""
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application


class EventNoticeTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='cambo-notices-');self.addCleanup(folder.cleanup)
        env=dict(os.environ);env.pop('DATABASE_URL',None)
        env.update(DB_PATH=str(Path(folder.name)/'app.db'),APP_ENV='development',DEMO_SEED='0',STAFF_PASSWORD='notice-test')
        settings=patch.dict(os.environ,env,clear=True);settings.start();self.addCleanup(settings.stop)
        self.app=Application()
        self.staff=self.call('/api/staff/login',{'name':'알림 담당','password':'notice-test'})
        self.buyer=self.call('/api/auth/register',{'name':'별빵','phone':'01011112222','pin':'1234'})
        self.other=self.call('/api/auth/register',{'name':'달빵','phone':'01033334444','pin':'1234'})
        with self.app.db.transaction(write=True) as tx:tx.execute('UPDATE products SET stock=100')

    def call(self,path,body=None,account=None,method='POST'):
        return self.app.handle(method,path,{},body or {},'Bearer '+account['token'] if account else None)

    def notices(self,account=None):
        return self.call('/api/event-notices',account=account,method='GET')['notices']

    def announce(self,text='행사 안내',identity=None):
        return self.call('/api/staff/event-notices',{'content':text,'request_id':identity or uuid.uuid4().hex},self.staff)['notice']

    def delete(self,notice):
        return self.call(f"/api/staff/event-notices/{notice['id']}/delete",account=self.staff)

    def order(self,items,account=None):
        return self.call('/api/orders',{'items':[{'product_id':pid,'quantity':n} for pid,n in items],
                         'request_id':uuid.uuid4().hex},account or self.buyer)['order']

    def approve(self,order):
        return self.call(f"/api/staff/orders/{order['id']}/approve",account=self.staff)

    def test_empty_then_one_then_latest_two_are_shared_and_physically_bounded(self):
        self.assertEqual(self.notices(),[])
        first=self.announce('첫 공지');self.assertEqual(self.notices(),[first])
        second=self.announce('두 번째 공지');third=self.announce('세 번째 공지')
        self.assertEqual(self.notices(),[third,second])
        self.assertEqual(self.notices(self.buyer),self.notices(self.other))
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM event_notices')['n'],2)
        self.assertEqual(third['author']['name'],'관리자')
        self.assertEqual(third['author']['profile_kind'],'admin')
        self.assertIsNone(third['author']['avatar'])
        self.assertNotIn('알림 담당',json.dumps(self.notices(),ensure_ascii=False))
        dashboard=self.call('/api/staff/dashboard',account=self.staff,method='GET')
        self.assertEqual(dashboard['event_notices'],self.notices())

    def test_delete_does_not_resurface_evicted_notices_and_retry_never_recreates(self):
        identity=uuid.uuid4().hex
        old=self.announce('오래된 공지',identity);second=self.announce('남을 공지');third=self.announce('최신 공지')
        self.delete(third);self.assertEqual(self.notices(),[second])
        self.delete(second);self.delete(second);self.assertEqual(self.notices(),[])
        self.assertEqual(self.announce('오래된 공지',identity),old)
        self.app=Application();self.assertEqual(self.notices(),[])

    def test_approval_publishes_once_and_deleted_achievements_stay_deleted(self):
        order=self.order([(101,5)])
        self.assertEqual(self.notices(),[])
        self.approve(order)
        notices=self.notices();self.assertEqual(len(notices),2)
        self.assertTrue(any(n['content']=='번개 연금술사 도전과제를 달성했습니다!' for n in notices))
        self.assertTrue(any('플레인 휘낭시에 몰입가 도전과제를 달성했습니다!'==n['content'] for n in notices))
        self.assertTrue(all(n['kind']=='achievement' and n['author']['name']=='별빵' and n['author']['equipped_title'] for n in notices))
        self.approve(order);self.assertEqual(self.notices(),notices)
        for notice in notices:self.delete(notice)
        self.approve(self.order([(101,1)]))
        self.app=Application();self.assertEqual(self.notices(),[])
        self.approve(self.order([(102,5)]))
        self.assertEqual(len(self.notices()),1)
        self.assertIn('초코 휘낭시에 몰입가',self.notices()[0]['content'])

    def test_all_buyers_see_new_achievement_and_public_current_profile_only(self):
        self.approve(self.order([(pid,1) for pid in range(101,105)]))
        user=self.call('/api/auth/me',account=self.buyer,method='GET')['user']
        avatar={**user['avatar'],'expression':'wink','face_shape':'pound'}
        self.call('/api/profile',{'avatar':avatar,'title_id':'elements','badge_id':'ach_elements'},self.buyer)
        notice=self.notices(self.other)[0]
        self.assertEqual(self.notices(self.other),self.notices(self.buyer))
        author=next(n['author'] for n in self.notices() if '원소 수집가' in n['content'])
        self.assertEqual(author['avatar'],avatar)
        self.assertEqual(author['equipped_title']['name'],'원소 수집가')
        self.assertEqual(author['equipped_badge']['id'],'ach_elements')
        for key in ('phone','password_hash','pin','badges','titles','achievements','orders','earned_badges'):
            self.assertNotIn(key,author)
        self.assertNotIn('010-',json.dumps(notice,ensure_ascii=False))

    def test_startup_backfill_awards_without_broadcasting_historical_achievements(self):
        order=self.order([(101,5)])
        with self.app.db.transaction(write=True) as tx:
            tx.execute("UPDATE orders SET status='approved' WHERE id=?",(order['id'],))
        self.app=Application()
        with self.app.db.transaction() as tx:
            self.assertGreater(tx.one('SELECT COUNT(*) AS n FROM user_achievements')['n'],0)
        self.assertEqual(self.notices(),[])

    def test_concurrent_announcements_retain_exactly_two_latest_sequence_ids(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda n:self.announce(f'공지 {n}'),range(4)))
        self.assertEqual([n['id'] for n in self.notices()],sorted([n['id'] for n in results],reverse=True)[:2])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM event_notices')['n'],2)

    def test_staff_only_mutations_validate_short_text_and_reject_profile_spoofing(self):
        for account,status in ((None,401),(self.buyer,403)):
            for path,body in (('/api/staff/event-notices',{'content':'공지','request_id':uuid.uuid4().hex}),
                              ('/api/staff/event-notices/1/delete',{})):
                with self.assertRaises(APIError) as error:self.call(path,body,account)
                self.assertEqual(error.exception.status,status)
        for body in ({'content':' '},{'content':'가'*161},{'content':'공지','author':{'name':'다른 사람'}}, {'content':None}):
            with self.assertRaises(APIError):
                self.call('/api/staff/event-notices',{**body,'request_id':uuid.uuid4().hex},self.staff)
        self.assertEqual(self.announce('  공지  ')['content'],'공지')

    def test_notice_and_achievement_rollback_with_failed_approval(self):
        order=self.order([(101,5)])
        with patch('server.achievements.publish_notice',side_effect=RuntimeError('failed notice')):
            with self.assertRaises(RuntimeError):self.approve(order)
        self.assertEqual(self.notices(),[])
        with self.app.db.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM user_achievements')['n'],0)
            self.assertEqual(tx.one('SELECT status FROM orders WHERE id=?',(order['id'],))['status'],'pending')
        self.approve(order);self.assertEqual(len(self.notices()),2)
