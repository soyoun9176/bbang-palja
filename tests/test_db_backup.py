"""Offsite backup, retention, failure handling and offline restore using disposable DBs."""
from dataclasses import replace
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

from ops import db_backup as backup

ROOT = Path(__file__).resolve().parents[1]


class BackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cambo-backup-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = backup.Settings(database=self.root / 'live.sqlite3', state=self.root / 'state')
        self.store = backup.LocalStore(self.root / 'offsite')
        self.now = datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
        self.connection = sqlite3.connect(self.settings.database)
        self.addCleanup(self.connection.close)
        self.connection.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE products(id INTEGER PRIMARY KEY, stock INTEGER);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, product_id INTEGER REFERENCES products(id),
                                quantity INTEGER, status TEXT);
            INSERT INTO products VALUES(101,8);
            INSERT INTO orders VALUES(1,101,2,'approved');
        ''')
        self.connection.commit()

    def do_backup(self, now=None):
        return backup.perform_backup(self.settings, self.store, now or self.now)

    def latest(self):
        return json.loads(self.store.path(self.settings.latest).read_text())

    def restore(self, destination=None, **kwargs):
        return backup.restore_backup(self.settings, self.store, destination or self.root / 'restored.sqlite3',
                                     api_stopped=True, **kwargs)

    def test_live_wal_round_trip_and_manifest_preserve_committed_records_only(self):
        self.connection.execute("INSERT INTO orders VALUES(2,101,1,'pending')")
        self.connection.commit()
        # Keep WAL open, with another uncommitted write that must never reach the snapshot.
        self.connection.execute('UPDATE products SET stock=6')
        saved = self.do_backup()
        restored = self.restore()
        self.assertEqual(restored['key'], saved['key'])
        with closing(sqlite3.connect(restored['database'])) as db:
            self.assertEqual(db.execute('SELECT stock FROM products').fetchone()[0], 8)
            self.assertEqual(db.execute('SELECT id,status FROM orders ORDER BY id').fetchall(),
                             [(1, 'approved'), (2, 'pending')])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.connection.execute('SELECT stock FROM products').fetchone()[0], 6)
        self.assertEqual(self.store.path(saved['key']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(restored['database']).stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.settings.state.glob('.run-*')))
        pointer = self.latest()
        self.assertEqual(pointer['archive_sha256'], backup.digest(self.store.path(saved['key'])))
        self.assertEqual(pointer['snapshot_started_at'], backup.iso(self.now))

    def test_wal_writer_can_commit_while_incremental_backup_is_running(self):
        self.connection.executescript('CREATE TABLE payload(value BLOB);')
        self.connection.executemany('INSERT INTO payload VALUES(?)', [(b'x' * 4096,)] * 300)
        self.connection.commit()
        connect = sqlite3.connect
        test = self
        writes = []

        class ObservedSource(sqlite3.Connection):
            def backup(self, destination, **kwargs):
                original_progress = kwargs['progress']

                def progress(status, remaining, total):
                    if not writes:
                        def write():
                            with closing(connect(test.settings.database, timeout=1)) as writer:
                                with writer:
                                    writer.execute('UPDATE products SET stock=7')
                                    writer.execute("INSERT INTO orders VALUES(2,101,1,'approved')")
                            writes.append(True)
                        thread = threading.Thread(target=write)
                        thread.start()
                        thread.join(timeout=2)
                        test.assertFalse(thread.is_alive(), 'backup blocked the WAL writer')
                    original_progress(status, remaining, total)

                kwargs['progress'] = progress
                return super().backup(destination, **kwargs)

        def observed_connect(path, *args, **kwargs):
            if str(path) == self.settings.database.as_uri() + '?mode=ro':
                kwargs['factory'] = ObservedSource
            return connect(path, *args, **kwargs)

        with patch.object(backup.sqlite3, 'connect', side_effect=observed_connect):
            self.do_backup()
        self.assertEqual(writes, [True])
        restored = self.restore()
        with closing(connect(restored['database'])) as db:
            # The order and stock must represent the same committed transaction.
            stock = db.execute('SELECT stock FROM products').fetchone()[0]
            orders = db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
            self.assertIn((stock, orders), [(8, 1), (7, 2)])

    def test_retention_keeps_recent_and_one_per_hour_without_deleting_other_objects(self):
        prefix = self.settings.snapshots
        original_keys = []
        for index in range(12 * 72):
            date = self.now - timedelta(minutes=5 * index)
            key = prefix + date.strftime('%Y%m%dT%H%M%S%fZ') + '-12345678.tar.gz'
            path = self.store.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'old snapshot')
            original_keys.append(key)
        unrelated = [prefix + 'notes.json', 'other-project/snapshots/keep.tar.gz',
                     prefix + '20261399T000000000000Z-12345678.tar.gz']
        for key in unrelated:
            path = self.store.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'not managed')
        self.do_backup(self.now + timedelta(minutes=5))
        keys = {key for key in self.store.keys(prefix) if backup.snapshot_time(self.settings, key)}
        self.assertLessEqual(len(keys), self.settings.recent + self.settings.hourly)
        self.assertTrue(set(original_keys[:11]).issubset(keys))
        hour_keys = {}
        for key in keys:
            date = backup.snapshot_time(self.settings, key)
            hour_keys.setdefault(date.replace(minute=0, second=0, microsecond=0), []).append(key)
        self.assertEqual(len(hour_keys), 48)
        for key in unrelated:
            self.assertTrue(self.store.path(key).exists())
        self.assertEqual(self.latest()['key'], backup.read_state(self.settings)['latest_key'])

    def test_upload_failure_preserves_pointer_history_and_last_success(self):
        self.do_backup()
        latest = self.latest()
        keys = sorted(self.store.keys(self.settings.snapshots))
        old_status = backup.read_state(self.settings)
        with patch.object(self.store, 'put', side_effect=OSError('private-secret-must-not-be-logged')):
            with self.assertRaises(OSError):
                self.do_backup(self.now + timedelta(minutes=5))
        self.assertEqual(self.latest(), latest)
        self.assertEqual(sorted(self.store.keys(self.settings.snapshots)), keys)
        status = backup.read_state(self.settings)
        self.assertEqual(status['last_success_at'], old_status['last_success_at'])
        self.assertEqual(status['last_error'], 'OSError')
        self.assertNotIn('private-secret', (self.settings.state / 'status.json').read_text())
        self.assertFalse(list(self.settings.state.glob('.run-*')))
        self.assertFalse(backup.backup_status(self.settings, self.now)['ok'])

    def test_pointer_publish_failure_does_not_prune_or_replace_last_known_good(self):
        self.do_backup()
        pointer = self.latest()
        put = self.store.put

        def fail_pointer(key, source):
            if key == self.settings.latest:
                raise OSError('pointer upload interrupted')
            put(key, source)

        with patch.object(self.store, 'put', side_effect=fail_pointer), patch.object(self.store, 'delete') as delete:
            with self.assertRaises(OSError):
                self.do_backup(self.now + timedelta(minutes=5))
        delete.assert_not_called()
        self.assertEqual(self.latest(), pointer)
        self.assertTrue(self.store.path(pointer['key']).is_file())
        # A subsequent successful run recovers status and can clean up orphaned objects.
        self.do_backup(self.now + timedelta(minutes=10))
        self.assertIsNone(backup.read_state(self.settings)['last_error'])

    def test_pruning_failure_records_that_backup_was_uploaded_and_retains_all_copies(self):
        with patch.object(self.store, 'delete', side_effect=OSError('delete failed')):
            with self.assertRaises(OSError):
                self.do_backup()
        status = backup.read_state(self.settings)
        self.assertIsNotNone(status['last_success_at'])
        self.assertEqual(status['latest_key'], self.latest()['key'])
        self.assertEqual(status['last_error'], 'OSError')
        self.restore()

    def test_missing_corrupt_and_oversized_sources_never_publish_or_prune(self):
        self.do_backup()
        pointer = self.latest()
        missing = replace(self.settings, database=self.root / 'missing.sqlite3')
        corrupt = self.root / 'corrupt.sqlite3'
        corrupt.write_bytes(b'not a SQLite database')
        empty = self.root / 'empty.sqlite3'
        with closing(sqlite3.connect(empty)):
            pass
        for settings in [missing, replace(self.settings, database=corrupt),
                         replace(self.settings, database=empty),
                         replace(self.settings, max_bytes=4096)]:
            with self.subTest(database=settings.database, limit=settings.max_bytes):
                with self.assertRaises((backup.BackupError, sqlite3.DatabaseError)):
                    backup.perform_backup(settings, self.store)
                self.assertEqual(self.latest(), pointer)
        self.assertFalse(missing.database.exists())

    def test_busy_snapshot_times_out_without_removing_last_backup(self):
        self.do_backup()
        pointer = self.latest()
        # Rollback-journal exclusive lock blocks reads, unlike normal WAL sales.
        self.connection.execute('PRAGMA journal_mode=DELETE')
        self.connection.execute('BEGIN EXCLUSIVE')
        with self.assertRaises((sqlite3.OperationalError, backup.BackupError)):
            backup.perform_backup(replace(self.settings, snapshot_timeout=1), self.store)
        self.assertEqual(self.latest(), pointer)
        self.connection.rollback()

    def test_overlap_is_skipped_and_restore_refuses_same_operation_lock(self):
        with backup.operation_lock(self.settings):
            with self.assertRaises(backup.AlreadyRunning):
                self.do_backup()
            with self.assertRaises(backup.AlreadyRunning):
                self.restore()
            environment = {'DB_PATH': str(self.settings.database), 'BACKUP_STATE_DIR': str(self.settings.state),
                           'DATABASE_URL': ''}
            with patch.dict(os.environ, environment, clear=True), patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(backup.main(['--local-store', str(self.store.root), 'backup']), 0)
            self.assertIn('another_operation_is_running', output.getvalue())

    def test_stale_status_uses_snapshot_time_instead_of_upload_time(self):
        self.do_backup()
        self.assertTrue(backup.backup_status(self.settings, self.now + timedelta(minutes=14))['ok'])
        self.assertFalse(backup.backup_status(self.settings, self.now + timedelta(minutes=16))['ok'])
        empty = replace(self.settings, state=self.root / 'empty-state')
        self.assertFalse(backup.backup_status(empty, self.now)['ok'])

    def test_restore_requires_explicit_stop_and_overwrite_flags(self):
        self.do_backup()
        destination = self.root / 'restored.sqlite3'
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.settings, self.store, destination)
        self.assertFalse(destination.exists())
        self.restore(destination)
        before = destination.read_bytes()
        with self.assertRaises(backup.BackupError):
            self.restore(destination)
        self.assertEqual(destination.read_bytes(), before)

    def test_replace_preserves_current_db_and_its_wal_before_restoring_older_data(self):
        self.do_backup()
        self.connection.execute("INSERT INTO orders VALUES(2,101,1,'pending')")
        self.connection.commit()
        self.connection.close()
        result = self.restore(self.settings.database, replace=True)
        with closing(sqlite3.connect(self.settings.database)) as restored:
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1)
        with closing(sqlite3.connect(result['before_restore'])) as preserved:
            self.assertEqual(preserved.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 2)

    def test_corrupt_download_preserves_existing_destination_and_latest_pointer(self):
        self.do_backup()
        pointer = self.latest()
        archive = self.store.path(pointer['key'])
        archive.write_bytes(archive.read_bytes()[:-20] + b'corrupt')
        destination = self.root / 'existing.sqlite3'
        destination.write_bytes(b'existing DB must remain untouched')
        with self.assertRaises(backup.BackupError):
            self.restore(destination, replace=True)
        self.assertEqual(destination.read_bytes(), b'existing DB must remain untouched')
        self.assertEqual(self.latest(), pointer)

    def test_restore_rejects_wrong_checksum_links_and_traversal_in_archive(self):
        manifest = {'format': 1, 'database_bytes': 8, 'database_sha256': '0' * 64,
                    'snapshot_started_at': backup.iso(self.now)}
        key = self.settings.snapshots + self.now.strftime('%Y%m%dT%H%M%S%fZ') + '-abcdef12.tar.gz'
        path = self.store.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        for name, kind in [('database.sqlite3', tarfile.REGTYPE),
                           ('../../outside', tarfile.REGTYPE), ('database.sqlite3', tarfile.SYMTYPE)]:
            with self.subTest(name=name, kind=kind):
                with tarfile.open(path, 'w:gz') as bundle:
                    data = backup.json_bytes(manifest)
                    info = tarfile.TarInfo('manifest.json')
                    info.size = len(data)
                    bundle.addfile(info, io.BytesIO(data))
                    info = tarfile.TarInfo(name)
                    info.size, info.type, info.linkname = 8, kind, '/etc/passwd'
                    bundle.addfile(info, io.BytesIO(b'bad data') if kind == tarfile.REGTYPE else None)
                with self.assertRaises(backup.BackupError):
                    self.restore(key=key)
                self.assertFalse((self.root / 'restored.sqlite3').exists())
                self.assertFalse((self.root.parent / 'outside').exists())

    def test_restore_can_select_older_snapshot_when_latest_object_is_unavailable(self):
        old = self.do_backup()
        self.connection.execute("INSERT INTO orders VALUES(2,101,1,'pending')")
        self.connection.commit()
        self.do_backup(self.now + timedelta(minutes=5))
        self.store.path(self.settings.latest).unlink()
        result = self.restore(key=old['key'])
        with closing(sqlite3.connect(result['database'])) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1)

    def test_foreign_prefix_and_unsafe_settings_are_rejected(self):
        for prefix in ('', '../production', 'cambo/../other', 'cambo/prod?x=1'):
            with self.subTest(prefix=prefix), self.assertRaises(backup.BackupError):
                backup.Settings.from_environment({'BACKUP_PREFIX': prefix})
        with self.assertRaises(backup.BackupError):
            backup.Settings.from_environment({'DATABASE_URL': 'postgres://do-not-backup-stale-sqlite'})
        with self.assertRaises(backup.BackupError):
            self.restore(key='another-project/snapshots/anything.tar.gz')
        for key in ('../outside', '/absolute', 'project/../../outside'):
            with self.assertRaises(backup.BackupError):
                self.store.path(key)

    def test_terminated_run_work_files_are_cleaned_under_lock(self):
        backup.private_directory(self.settings.state)
        abandoned = self.settings.state / '.run-abandoned'
        abandoned.mkdir()
        (abandoned / 'private.sqlite3').write_bytes(b'old incomplete working file')
        self.do_backup()
        self.assertFalse(abandoned.exists())

    def test_standalone_installed_tool_records_current_api_release_not_its_own_directory(self):
        release = self.root / 'active-release'
        release.mkdir()
        (release / 'release.json').write_text(json.dumps({'commit': 'a' * 40}))
        settings = replace(self.settings, app_directory=release)
        backup.perform_backup(settings, self.store, self.now)
        self.assertEqual(self.latest()['code_commit'], 'a' * 40)
        self.assertEqual(self.restore()['code_commit'], 'a' * 40)

    def test_cli_local_store_round_trip_needs_no_cloud_credentials_or_api(self):
        environment = dict(os.environ, DB_PATH=str(self.settings.database), DATABASE_URL='',
                           BACKUP_STATE_DIR=str(self.settings.state))
        environment.pop('BACKUP_PREFIX', None)
        command = [sys.executable, str(ROOT / 'ops/db_backup.py'), '--local-store', str(self.store.root)]
        for arguments in [['backup'], ['list'], ['status'],
                          ['restore', '--destination', str(self.root / 'restored.sqlite3'), '--api-stopped']]:
            result = subprocess.run(command + arguments, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])


class ApplicationRestoreTests(unittest.TestCase):
    def test_full_event_database_restores_accounts_orders_stock_rewards_and_works_with_api(self):
        from server.app import Application
        with tempfile.TemporaryDirectory(prefix='cambo-full-restore-') as folder:
            root = Path(folder)
            source, restored = root / 'source.sqlite3', root / 'restored.sqlite3'
            environment = dict(os.environ, DB_PATH=str(source), DATABASE_URL='', DEMO_SEED='0',
                               APP_ENV='production', STAFF_PASSWORD='backup-test-staff', ALLOWED_ORIGINS='')
            with patch.dict(os.environ, environment, clear=True):
                app = Application()

                def call(path, body=None, token=None, method='POST'):
                    return app.handle(method, path, {}, body or {}, 'Bearer ' + token if token else None)

                staff = call('/api/staff/login', {'name': '복원담당', 'password': 'backup-test-staff'})
                buyer = call('/api/auth/register', {'name': '복원검증', 'phone': '010-5555-1212', 'pin': '1234'})
                with app.db.transaction(write=True) as tx:
                    tx.execute('UPDATE products SET stock=10 WHERE id=101')
                order = call('/api/orders', {'items': [{'product_id': 101, 'quantity': 2}],
                             'request_id': 'backup-order-1'}, buyer['token'])['order']
                call(f"/api/staff/orders/{order['id']}/approve", {}, staff['token'])
                call('/api/staff/manual-event-grants', {'user_id': buyer['user']['id'], 'kind': 'bread',
                     'product_id': 101, 'quantity': 1, 'reason': '복원검증', 'request_id': 'backup-grant-1'}, staff['token'])
                with closing(sqlite3.connect(source)) as database:
                    expected_dump = list(database.iterdump())
                settings = backup.Settings(database=source, state=root / 'state')
                store = backup.LocalStore(root / 'offsite')
                backup.perform_backup(settings, store)
                backup.restore_backup(settings, store, restored, api_stopped=True)
                with closing(sqlite3.connect(restored)) as database:
                    self.assertEqual(list(database.iterdump()), expected_dump)
                os.environ['DB_PATH'] = str(restored)
                app = Application()
                # Existing sessions, PIN authentication, approval state, dice and grants all survive.
                user = call('/api/auth/me', token=buyer['token'], method='GET')['user']
                self.assertEqual(user['name'], '복원검증')
                self.assertEqual(user['dice_balance'], 2)
                dashboard = call('/api/staff/dashboard', token=staff['token'], method='GET')
                self.assertEqual(dashboard['stats']['bread_sold'], 2)
                self.assertEqual(dashboard['stats']['bread_event_given'], 1)
                with app.db.transaction() as tx:
                    self.assertEqual(tx.one('SELECT stock FROM products WHERE id=101')['stock'], 7)


class BackupTimerTests(unittest.TestCase):
    def test_timer_and_service_bound_frequency_and_resources_without_api_restart(self):
        timer = (ROOT / 'ops/systemd/bbang-palja-backup.timer').read_text()
        service = (ROOT / 'ops/systemd/bbang-palja-backup.service').read_text()
        self.assertIn('OnUnitActiveSec=5min', timer)
        for setting in ['Nice=10', 'IOSchedulingClass=idle', 'CPUQuota=20%',
                        'MemoryMax=192M', 'TimeoutStartSec=120s', 'UMask=0077']:
            self.assertIn(setting, service)
        self.assertNotIn('ExecStartPre=', service)
        self.assertNotIn('Restart=', service)
        self.assertIn('/usr/local/lib/bbang-palja-backup/db_backup.py backup', service)
        self.assertNotIn('/opt/bbang-palja/app/ops/db_backup.py', service)


if __name__ == '__main__':
    unittest.main()
