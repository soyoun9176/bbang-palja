"""Deployment gates, deterministic frontend artifacts and rollback behavior."""
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from ops import deploy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_frontend', ROOT/'ops/build-frontend.py')
frontend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontend)


class DeploymentTests(unittest.TestCase):
    def test_only_the_latest_successful_main_push_is_eligible(self):
        valid = {'id':10,'head_sha':'a'*40,'event':'push','head_branch':'main',
                 'head_repository':{'full_name':deploy.REPOSITORY},'status':'completed','conclusion':'success'}
        self.assertTrue(deploy.verified_run([valid],'a'*40))
        for change in ({'event':'pull_request'},{'head_branch':'feature'},
                       {'head_repository':{'full_name':'someone/fork'}},{'status':'in_progress'},
                       {'conclusion':'failure'},{'head_sha':'b'*40}):
            with self.subTest(change=change):
                self.assertFalse(deploy.verified_run([{**valid,**change}],'a'*40))
        self.assertFalse(deploy.verified_run([valid,{**valid,'id':11,'conclusion':'failure'}],'a'*40))

    def archive(self, extra=None):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as tar:
            for name,content in [('repo/server/app.py',b'# app'),('repo/frontend/index.html',b'<html>')]:
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info,io.BytesIO(content))
            if extra:
                tar.addfile(extra)
        return buffer.getvalue()

    def test_unsuccessful_ci_keeps_running_release_and_does_not_backup_or_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)
            with patch.object(deploy,'STATE',state), \
                    patch.object(deploy,'get_json',side_effect=[{'sha':'a'*40},{'workflow_runs':[]}]), \
                    patch.object(deploy,'activate') as activate, \
                    patch.object(deploy,'backup_database') as backup:
                deploy.deploy()
            activate.assert_not_called()
            backup.assert_not_called()
            self.assertFalse((state/'state.json').exists())

    def test_active_release_is_not_deleted_when_recovering_after_state_write_interruption(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            sha='a'*40
            release=base/sha
            release.mkdir()
            current=base/'app'
            current.symlink_to(release)
            valid={'id':10,'head_sha':sha,'event':'push','head_branch':'main',
                   'head_repository':{'full_name':deploy.REPOSITORY},'status':'completed','conclusion':'success'}
            with patch.multiple(deploy,STATE=base,CURRENT=current,RELEASES=base), \
                    patch.object(deploy,'get_json',side_effect=[{'sha':sha},{'workflow_runs':[valid]}]), \
                    patch.object(deploy,'wait_healthy') as healthy, \
                    patch.object(deploy.shutil,'rmtree') as remove:
                deploy.deploy()
            healthy.assert_called_once_with(sha)
            remove.assert_not_called()
            self.assertTrue(release.is_dir())
            self.assertEqual(json.loads((base/'state.json').read_text())['deployed_sha'],sha)

    def test_release_archive_rejects_traversal_links_and_special_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            deploy.extract_release(self.archive(),base/'valid')
            self.assertTrue((base/'valid/server/app.py').is_file())
            for index,kind in enumerate(['traversal','symlink','fifo']):
                info = tarfile.TarInfo('repo/../../outside' if kind=='traversal' else 'repo/unsafe')
                if kind=='symlink':
                    info.type=tarfile.SYMTYPE
                    info.linkname='/etc/passwd'
                elif kind=='fifo':
                    info.type=tarfile.FIFOTYPE
                with self.assertRaises(ValueError):
                    deploy.extract_release(self.archive(info),base/str(index))
            self.assertFalse((base.parent/'outside').exists())

    def test_database_backup_is_consistent_and_preserves_live_data(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            database=base/'app.sqlite3'
            with sqlite3.connect(database) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE orders(id INTEGER PRIMARY KEY, quantity INTEGER)')
                db.execute('INSERT INTO orders VALUES(1,4)')
                db.commit()
                env=base/'api.env'
                env.write_text('DB_PATH='+str(database)+'\n')
                with patch.multiple(deploy,ENVIRONMENT=env,DATA_DIRECTORY=base,BACKUPS=base/'backups'):
                    backup=deploy.backup_database()
                with sqlite3.connect(backup) as saved:
                    self.assertEqual(saved.execute('SELECT quantity FROM orders').fetchone()[0],4)
                    self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(db.execute('SELECT quantity FROM orders').fetchone()[0],4)
                self.assertEqual(backup.stat().st_mode & 0o777,0o600)

    def test_failed_health_restores_previous_code_without_restoring_database(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            old,new,current=base/'old',base/'new',base/'app'
            old.mkdir();new.mkdir();current.symlink_to(old)
            with patch.multiple(deploy,CURRENT=current,RELEASES=base), \
                    patch.object(deploy,'backup_database',return_value=base/'backup') as backup, \
                    patch.object(deploy,'restart_api') as restart, \
                    patch.object(deploy,'wait_healthy',side_effect=[RuntimeError('failed'),None]):
                with self.assertRaises(RuntimeError):
                    deploy.activate(new,'b'*40)
            self.assertEqual(current.resolve(),old.resolve())
            self.assertTrue(new.is_dir())
            self.assertEqual(restart.call_count,2)
            backup.assert_called_once()

    def test_frontend_build_uses_hashes_and_rewrites_admin_module(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'dist'
            frontend.build(output,commit='a'*40)
            version=json.loads((output/'version.json').read_text())
            html=(output/'index.html').read_text()
            self.assertEqual(version['commit'],'a'*40)
            for name in ['app','config','css']:
                self.assertIn(version[name],html)
                self.assertTrue((output/version[name].lstrip('/')).is_file())
            app=(output/version['app'].lstrip('/')).read_text()
            self.assertNotIn("'./admin.js'",app)
            self.assertRegex(app,r'/build/admin\.[a-f0-9]{16}\.js')
            self.assertFalse((output/'app.js').exists())
            self.assertEqual((output/'_redirects').read_text().strip(),'/admin / 200\n/admin/ / 200')
            self.assertIn('Cache-Control: no-store',(output/'_headers').read_text())
            self.assertFalse((output/'server').exists())
            frontend.build(output,commit='a'*40)
            self.assertEqual(json.loads((output/'version.json').read_text()),version)
            with self.assertRaises(ValueError):
                frontend.build(ROOT)
            with self.assertRaises(ValueError):
                frontend.build(Path(folder))
