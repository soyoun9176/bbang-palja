#!/usr/bin/env python3
"""Fixed-scope Oracle pull deployer. Installed root-owned; never self-updates."""
import argparse
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request

REPOSITORY = 'soyoun9176/bbang-palja'
STATE = Path('/var/lib/bbang-palja-deploy')
RELEASES = Path('/opt/bbang-palja/releases')
CURRENT = Path('/opt/bbang-palja/app')
ENVIRONMENT = Path('/etc/bbang-palja/api.env')
BACKUPS = Path('/var/backups/bbang-palja')
DATA_DIRECTORY = Path('/var/lib/bbang-palja')
API = 'http://127.0.0.1:8000'
SERVICE = 'bbang-palja-api.service'


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def get_json(url):
    request = urllib.request.Request(url, headers={'Accept':'application/vnd.github+json',
                                                  'User-Agent':'bbang-palja-deployer'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def verified_run(runs, sha):
    candidates = [run for run in runs if run.get('head_sha') == sha
                  and run.get('event') == 'push' and run.get('head_branch') == 'main'
                  and run.get('head_repository',{}).get('full_name') == REPOSITORY]
    latest = max(candidates, key=lambda run:(run['id'],run.get('run_attempt',1)), default={})
    return latest.get('status') == 'completed' and latest.get('conclusion') == 'success'


def extract_release(archive, destination):
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0].startswith('/') or '..' in parts:
                raise ValueError('Unsafe release archive path.')
            if len(parts) == 1:
                continue
            target = destination.joinpath(*parts[1:])
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
            elif member.isfile():
                total += member.size
                if member.size > 5_000_000 or total > 30_000_000:
                    raise ValueError('Release archive is unexpectedly large.')
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open('xb') as out:
                    shutil.copyfileobj(source,out)
                target.chmod(0o644)
            else:
                raise ValueError('Links and special files are not allowed in releases.')
    if not (destination/'server/app.py').is_file() or not (destination/'frontend/index.html').is_file():
        raise ValueError('Incomplete release.')


def backup_database():
    environment = dict(line.split('=',1) for line in ENVIRONMENT.read_text().splitlines()
                       if line and not line.startswith('#'))
    if environment.get('DATABASE_URL'):
        raise RuntimeError('Configure PostgreSQL backup support before enabling automatic deployment.')
    database = Path(environment['DB_PATH'])
    # systemd StateDirectory may be a link into /var/lib/private; validate the configured path.
    if database.parent != DATA_DIRECTORY or not database.is_file():
        raise RuntimeError('Unexpected or missing database; refusing deployment.')
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = BACKUPS / ('before-deploy-'+stamp()+'.sqlite3')
    source = sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=10)
    backup = sqlite3.connect(target)
    try:
        source.backup(backup)
        result = backup.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise RuntimeError('Database backup integrity check failed.')
    finally:
        backup.close()
        source.close()
    target.chmod(0o600)
    return target


def restart_api():
    subprocess.run(['systemctl','restart',SERVICE], check=True, timeout=35)


def wait_healthy(sha=None):
    deadline = time.monotonic()+30
    while True:
        try:
            health = get_json(API+'/api/health')
            if health.get('ok') and (sha is None or health.get('commit') == sha):
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('API health check failed.')
        time.sleep(1)


def switch_release(target):
    link = CURRENT.with_name('.app-next')
    link.unlink(missing_ok=True)
    link.symlink_to(target, target_is_directory=True)
    link.replace(CURRENT)


def activate(release, sha):
    backup = backup_database()
    previous = CURRENT.resolve()
    if not CURRENT.is_symlink():
        if not (CURRENT/'.bbang-palja-managed').exists():
            raise RuntimeError('Refusing to replace an unmanaged application.')
        subprocess.run(['systemctl','stop',SERVICE], check=True, timeout=30)
        previous = RELEASES / ('bootstrap-'+stamp())
        CURRENT.rename(previous)
    try:
        switch_release(release)
        restart_api()
        wait_healthy(sha)
    except Exception:
        switch_release(previous)
        restart_api()
        wait_healthy()
        raise
    return str(backup)


def save_state(state):
    temporary = STATE/'state.next.json'
    temporary.write_text(json.dumps(state, indent=2)+'\n')
    temporary.chmod(0o600)
    temporary.replace(STATE/'state.json')


def deploy(retry=False):
    state_path = STATE/'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    sha = get_json(f'https://api.github.com/repos/{REPOSITORY}/commits/main')['sha']
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('Invalid GitHub commit.')
    if state.get('deployed_sha') == sha:
        print('Already deployed: '+sha, flush=True)
        return
    if state.get('failed_sha') == sha and not retry:
        print('Previous deployment failed; inspect journal and retry explicitly: '+sha, flush=True)
        return
    query = urllib.parse.urlencode({'head_sha':sha,'event':'push','branch':'main','per_page':5})
    runs = get_json(f'https://api.github.com/repos/{REPOSITORY}/actions/workflows/ci.yml/runs?{query}')['workflow_runs']
    if not verified_run(runs,sha):
        print('Waiting for successful main-branch CI: '+sha, flush=True)
        return
    RELEASES.mkdir(mode=0o755, parents=True, exist_ok=True)
    release = RELEASES/sha
    if CURRENT.is_symlink() and CURRENT.resolve() == release:
        wait_healthy(sha)
        save_state({'deployed_sha':sha,'last_success':stamp(),'recovered':True})
        print('Recovered deployment state: '+sha, flush=True)
        return
    try:
        if release.exists():
            shutil.rmtree(release)  # Failed staging only; current release is checked above.
        release.mkdir(mode=0o755)
        request = urllib.request.Request(f'https://codeload.github.com/{REPOSITORY}/tar.gz/{sha}',
                                         headers={'User-Agent':'bbang-palja-deployer'})
        with urllib.request.urlopen(request,timeout=30) as response:
            archive = response.read(30_000_001)
        if len(archive)>30_000_000:
            raise ValueError('Release download is unexpectedly large.')
        extract_release(archive, release)
        # Repository code/tests run unprivileged, without production credentials.
        environment = {'PATH':'/usr/bin:/bin','HOME':'/tmp','LANG':'C.UTF-8',
                       'PYTHONDONTWRITEBYTECODE':'1'}
        subprocess.run(['/usr/bin/python3','-m','unittest','discover','-s','tests','-v'],
                       cwd=release, env=environment, user='nobody', group='nogroup',
                       extra_groups=[], timeout=180, check=True)
        (release/'release.json').write_text(json.dumps({'commit':sha})+'\n')
        (release/'.bbang-palja-managed').touch()
        backup = activate(release, sha)
    except Exception as error:
        state.update(failed_sha=sha,last_failure=stamp(),error=str(error))
        save_state(state)
        raise
    save_state({'deployed_sha':sha,'last_success':stamp(),'backup':backup})
    print('Deployment healthy: '+sha, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry', action='store_true', help='Retry a failed commit after inspecting the journal.')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run the installed deployer as root on Oracle.')
    os.umask(0o022)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE/'deploy.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another deployment is in progress.')
            return
        deploy(args.retry)


if __name__ == '__main__':
    main()
