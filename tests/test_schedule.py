"""Private schedule import is date-scoped and preserves existing deployments."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server.app import APIError,Application
from server.db import Database
from server.schedule import replace_dates


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='cambo-schedule-test-');self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.path=self.root/'app.db'
        settings=patch.dict(os.environ,{'DB_PATH':str(self.path),'DATABASE_URL':'','APP_ENV':'development',
                                      'DEMO_SEED':'0','STAFF_PASSWORD':'schedule-test-password'})
        settings.start();self.addCleanup(settings.stop)
        self.db=Database(self.root)

    def rows(self):
        with self.db.transaction() as tx:return tx.all('SELECT name,time,role,event_date FROM schedule ORDER BY id')

    def test_previous_schedule_table_adds_date_without_losing_legacy_rows(self):
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE schedule(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,time TEXT NOT NULL,role TEXT NOT NULL)')
            c.execute("INSERT INTO schedule VALUES(7,'담당 A','09:00-10:00','포장')")
        for _ in range(2):self.db.initialize()
        self.assertEqual(self.rows(),[{'name':'담당 A','time':'09:00-10:00','role':'포장','event_date':None}])
        with self.db.transaction() as tx:self.assertEqual(tx.all('PRAGMA foreign_key_check'),[])

    def test_import_replaces_only_selected_dates_and_is_repeatable(self):
        self.db.initialize()
        with self.db.transaction(write=True) as tx:
            tx.insert('INSERT INTO schedule(name,time,role) VALUES(?,?,?)',('공통 담당','오픈','준비'))
            tx.insert('INSERT INTO schedule(name,time,role,event_date) VALUES(?,?,?,?)',('다른 날짜 담당','오픈','','2099-01-03'))
        incoming=[{'event_date':'2099-01-01','time':'오픈','name':'담당 A, 담당 B'},
                  {'event_date':'2099-01-01','time':'09:00–10:00','name':'담당 C','role':'판매'}]
        for _ in range(2):
            with self.db.transaction(write=True) as tx:self.assertEqual(replace_dates(tx,incoming),{'imported':2,'dates':['2099-01-01']})
        rows=self.rows();self.assertEqual(len(rows),4)
        self.assertEqual(rows[-1],{'name':'담당 C','time':'09:00-10:00','role':'판매','event_date':'2099-01-01'})
        self.db.initialize();self.assertEqual(self.rows(),rows)

    def test_invalid_payload_never_removes_existing_assignments(self):
        self.db.initialize()
        row={'event_date':'2099-01-01','time':'오픈','name':'담당 A'}
        with self.db.transaction(write=True) as tx:replace_dates(tx,[row])
        before=self.rows()
        invalid=[[],{},[{**row,'event_date':'2099-02-30'}],[{**row,'event_date':'2099-1-1'}],
                 [{**row,'time':'25:00-26:00'}],[{**row,'time':'12:00-10:00'}],[{**row,'time':'10:00-24:01'}],
                 [{**row,'time':None}],[{**row,'name':''}],[{**row,'role':'x'*81}],[{**row,'extra':True}],
                 [row,dict(row)],[row,{**row,'name':None}]]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    with self.db.transaction(write=True) as tx:replace_dates(tx,payload)
                self.assertEqual(self.rows(),before)

    def test_schedule_is_staff_only_and_restart_does_not_seed_or_overwrite_it(self):
        app=Application()
        def call(path,body=None,token=None,method='POST'):
            return app.handle(method,path,{},body or {},'Bearer '+token if token else None)
        staff=call('/api/staff/login',{'name':'담당 A','password':'schedule-test-password'})
        buyer=call('/api/auth/register',{'name':'참가자 A','phone':'01012345678','pin':'1234'})
        self.assertEqual(call('/api/staff/dashboard',token=staff['token'],method='GET')['schedule'],[])
        with app.db.transaction(write=True) as tx:
            replace_dates(tx,[{'event_date':'2099-01-01','time':'오픈','name':'담당 A, 담당 B'}])
        app=Application()
        result=call('/api/staff/dashboard',token=staff['token'],method='GET')['schedule']
        self.assertEqual((result[0]['event_date'],result[0]['name']),('2099-01-01','담당 A, 담당 B'))
        with self.assertRaises(APIError) as error:call('/api/staff/dashboard',token=buyer['token'],method='GET')
        self.assertEqual(error.exception.status,403)
        self.assertNotIn('schedule',call('/api/config',method='GET'))


if __name__=='__main__':unittest.main()
