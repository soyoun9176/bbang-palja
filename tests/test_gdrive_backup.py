"""Drive transport boundaries, failed uploads, retention and restore without OAuth secrets."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ops import db_backup as backup


class GoogleDriveBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cambo-drive-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = backup.Settings(database=self.root / 'source.sqlite3', state=self.root / 'state',
                                       recent=1, hourly=0)
        self.config = self.root / 'rclone.conf'
        self.config.write_text('[cambo-backup]\ntype = drive\nscope = drive.file\ntoken = {"access_token":"test-only"}\n')
        self.config.chmod(0o600)
        self.environment = {'BACKUP_RCLONE_BIN': sys.executable, 'BACKUP_RCLONE_CONFIG': str(self.config),
                            'BACKUP_DRIVE_REMOTE': 'cambo-backup:cambo-delight-backups'}
        self.store = backup.GoogleDriveStore(self.environment, self.settings)
        self.objects = {}
        self.commands = []
        self.deleted = []
        transport = patch.object(backup.subprocess, 'run', side_effect=self.transport)
        transport.start()
        self.addCleanup(transport.stop)

    def transport(self, command, **kwargs):
        self.commands.append(command)
        operation = next(item for item in command if item in ('copyto', 'lsjson', 'delete'))
        arguments = command[command.index(operation) + 1:]
        if operation == 'copyto':
            source, target = arguments[:2]
            if source.startswith('cambo-backup:'):
                Path(target).write_bytes(self.objects[source])
            else:
                self.objects[target] = Path(source).read_bytes()
            body = b''
        elif operation == 'lsjson':
            path = arguments[0]
            entries = [{'Path': key[len(path) + 1:], 'IsDir': False, 'Size': len(self.objects[key]),
                        'Hashes': {'md5': hashlib.md5(self.objects[key], usedforsecurity=False).hexdigest()}}
                       for key in self.objects
                       if key.startswith(path + '/') and '/' not in key[len(path) + 1:]]
            body = json.dumps(entries).encode()
        else:
            path = arguments[0]
            names = Path(arguments[arguments.index('--files-from-raw') + 1]).read_text().splitlines()
            self.deleted.extend(names)
            for name in names:
                self.objects.pop(path + '/' + name, None)
            body = b''
        return subprocess.CompletedProcess(command, 0, body, b'')

    def source_database(self):
        database = sqlite3.connect(self.settings.database)
        try:
            database.execute('CREATE TABLE orders(id INTEGER PRIMARY KEY, quantity INTEGER)')
            database.execute('INSERT INTO orders VALUES(1,3)')
            database.commit()
        finally:
            database.close()

    def test_full_backup_retention_and_restore_use_only_the_dedicated_drive_folder(self):
        self.source_database()
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        first = backup.perform_backup(self.settings, self.store, now)
        second = backup.perform_backup(self.settings, self.store, now + timedelta(minutes=5))
        self.assertNotIn(self.store._path(first['key']), self.objects)
        self.assertIn(self.store._path(second['key']), self.objects)
        self.assertEqual(self.deleted, [first['key'].split('/')[-1]])
        target = self.root / 'restored.sqlite3'
        backup.restore_backup(self.settings, self.store, target, api_stopped=True)
        database = sqlite3.connect(target)
        try:
            self.assertEqual(database.execute('SELECT * FROM orders').fetchall(), [(1, 3)])
        finally:
            database.close()
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        delete = next(command for command in self.commands if 'delete' in command)
        self.assertIn('--drive-use-trash=false', delete)
        self.assertTrue(delete[delete.index('delete') + 1].endswith('/snapshots'))
        self.assertFalse(list(self.config.parent.glob('.delete-*')))

    def test_auth_scope_and_config_permissions_are_enforced(self):
        self.config.write_text(self.config.read_text().replace('drive.file', 'drive'))
        with self.assertRaises(backup.BackupError):
            backup.GoogleDriveStore(self.environment, self.settings)
        self.config.write_text(self.config.read_text().replace('scope = drive\n', 'scope = drive.file\n'))
        self.config.chmod(0o644)
        with self.assertRaises(backup.BackupError):
            backup.GoogleDriveStore(self.environment, self.settings)

    def test_remote_root_and_paths_cannot_target_unrelated_drive_files(self):
        for remote in ('cambo-backup:', 'cambo-backup:../personal', 'other:personal;delete'):
            with self.assertRaises(backup.BackupError):
                backup.GoogleDriveStore({**self.environment, 'BACKUP_DRIVE_REMOTE': remote}, self.settings)
        for key in ('../personal', 'another-project/latest.json', self.settings.snapshots + '../latest.json'):
            with self.assertRaises(backup.BackupError):
                self.store._path(key)
        with self.assertRaises(backup.BackupError):
            self.store.delete([self.settings.latest])
        with self.assertRaises(backup.BackupError):
            self.store.keys('personal/')
        self.assertFalse(self.commands)

    def test_empty_rclone_defaults_are_allowed_but_alternative_credentials_are_rejected(self):
        original = self.config.read_text()
        self.config.write_text(original + 'team_drive =\nservice_account_file =\nclient_credentials = false\n')
        backup.GoogleDriveStore(self.environment, self.settings)
        for line in ('team_drive = shared-drive-id', 'client_credentials = true',
                     'service_account_file = /tmp/service-account.json'):
            with self.subTest(option=line):
                self.config.write_text(original + line + '\n')
                with self.assertRaises(backup.BackupError):
                    backup.GoogleDriveStore(self.environment, self.settings)

    def test_malformed_drive_listings_fail_without_deleting_snapshots(self):
        for value in (None, {}, [1], [{'Path': None}]):
            with self.subTest(value=value), patch.object(self.store, '_run', return_value=json.dumps(value).encode()):
                with self.assertRaises(backup.BackupError):
                    self.store.keys(self.settings.snapshots)
                with self.assertRaises(backup.BackupError):
                    self.store._stat(self.settings.latest)
        self.assertFalse(self.deleted)

    def test_upload_checksum_mismatch_is_rejected(self):
        source = self.root / 'upload'
        source.write_bytes(b'payload')
        with patch.object(self.store, '_stat', return_value={'Size': 7, 'Hashes': {'md5': '0' * 32}}):
            with self.assertRaises(backup.BackupError):
                self.store.put(self.settings.latest, source)

    def test_dedicated_folder_id_allows_using_that_folder_as_remote_root(self):
        self.config.write_text(self.config.read_text() + 'root_folder_id = dedicated-backup-folder\n')
        store = backup.GoogleDriveStore({**self.environment, 'BACKUP_DRIVE_REMOTE': 'cambo-backup:'}, self.settings)
        self.assertEqual(store._path(self.settings.latest), 'cambo-backup:' + self.settings.latest)

    def test_oversized_download_is_rejected_before_copying(self):
        key = self.settings.latest
        self.objects[self.store._path(key)] = b'x' * 20
        target = self.root / 'download'
        with self.assertRaises(backup.BackupError):
            self.store.get(key, target, 10)
        self.assertFalse(target.exists())
        self.assertFalse(any('copyto' in command for command in self.commands))

    def test_duplicate_drive_names_stop_cleanup(self):
        duplicate = json.dumps([{'Path': 'same.tar.gz'}, {'Path': 'same.tar.gz'}]).encode()
        with patch.object(self.store, '_run', return_value=duplicate):
            with self.assertRaises(backup.BackupError):
                self.store.keys(self.settings.snapshots)
        self.assertFalse(self.deleted)

    def test_recent_upload_lookup_retries_only_missing_objects_with_a_fixed_limit(self):
        metadata = {'Path': 'latest.json', 'Size': 1, 'IsDir': False, 'Hashes': {'md5': 'a' * 32}}
        with patch.object(self.store, '_run', side_effect=[b'[]', json.dumps([metadata]).encode()]) as run, \
                patch.object(backup.time, 'sleep') as sleep:
            self.assertEqual(self.store._stat(self.settings.latest), metadata)
            self.assertEqual(run.call_count, 2)
            sleep.assert_called_once_with(1)
        with patch.object(self.store, '_run', return_value=b'[]') as run, \
                patch.object(backup.time, 'sleep'):
            with self.assertRaises(backup.BackupError):
                self.store._stat(self.settings.latest)
            self.assertEqual(run.call_count, 3)

    def test_rclone_errors_do_not_expose_oauth_token_or_retry_indefinitely(self):
        with patch.object(backup.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 1, b'', b'secret-refresh-token-must-not-be-logged')):
            with self.assertRaises(backup.BackupError) as error:
                self.store.keys(self.settings.snapshots)
        self.assertNotIn('secret-refresh-token', str(error.exception))
        with patch.object(backup.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 40)):
            with self.assertRaises(backup.BackupError):
                self.store.keys(self.settings.snapshots)

    def test_failed_drive_upload_keeps_latest_pointer_and_existing_snapshot(self):
        self.source_database()
        backup.perform_backup(self.settings, self.store)
        original = dict(self.objects)
        with patch.object(self.store, '_run', side_effect=backup.BackupError('upload failed')):
            with self.assertRaises(backup.BackupError):
                backup.perform_backup(self.settings, self.store)
        self.assertEqual(self.objects, original)
        self.assertFalse(self.deleted)


if __name__ == '__main__':
    unittest.main()
