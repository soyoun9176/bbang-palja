#!/usr/bin/env python3
"""Five-minute offsite SQLite snapshots; restore is always an explicit operation."""
import argparse
import configparser
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 256 * 1024
SNAPSHOT_NAME = re.compile(r'(\d{8}T\d{12}Z)-[0-9a-f]{8}\.tar\.gz')


class BackupError(RuntimeError):
    """A safe, operator-facing error that never includes credentials or DB records."""


class AlreadyRunning(BackupError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise BackupError('백업 시각에 시간대가 없습니다.')
    return parsed.astimezone(timezone.utc)


def private_directory(path):
    if path.is_symlink():
        raise BackupError('작업 폴더는 심볼릭 링크일 수 없습니다.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n').encode()


def write_json(path, value):
    descriptor, name = tempfile.mkstemp(prefix='.json-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def environment_files(paths):
    environment = dict(os.environ)
    for path in paths:
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                raise BackupError('환경 파일은 KEY=value 형식이어야 합니다.')
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            environment[key] = value
    return environment


def local_path(value):
    path = Path(value).expanduser()
    return path.absolute() if path.is_absolute() else (ROOT / path).absolute()


@dataclass(frozen=True)
class Settings:
    database: Path
    state: Path
    app_directory: Path = ROOT
    prefix: str = 'cambo-delight/production'
    recent: int = 12
    hourly: int = 48
    max_bytes: int = 256 * 1024 * 1024
    snapshot_timeout: int = 45
    stale_seconds: int = 900

    @classmethod
    def from_environment(cls, environment):
        if environment.get('DATABASE_URL'):
            raise BackupError('이 도구는 SQLite 전용입니다. DATABASE_URL을 확인하세요.')
        prefix = environment.get('BACKUP_PREFIX', cls.prefix).strip('/')
        if not prefix or any(not re.fullmatch(r'[A-Za-z0-9_-]+', part)
                             for part in prefix.split('/')):
            raise BackupError('BACKUP_PREFIX는 영문·숫자·밑줄·하이픈으로 된 전용 경로여야 합니다.')
        settings = cls(
            database=local_path(environment.get('DB_PATH', 'data/prototype.sqlite3')),
            state=local_path(environment.get('BACKUP_STATE_DIR', 'data/remote-backup-state')),
            app_directory=local_path(environment.get('BACKUP_APP_DIR', str(ROOT))),
            prefix=prefix,
            recent=int(environment.get('BACKUP_KEEP_RECENT', cls.recent)),
            hourly=int(environment.get('BACKUP_KEEP_HOURLY', cls.hourly)),
            max_bytes=int(environment.get('BACKUP_MAX_DB_BYTES', cls.max_bytes)),
            snapshot_timeout=int(environment.get('BACKUP_SNAPSHOT_TIMEOUT', cls.snapshot_timeout)),
            stale_seconds=int(environment.get('BACKUP_STALE_SECONDS', cls.stale_seconds)))
        if not (1 <= settings.recent <= 288 and 0 <= settings.hourly <= 168
                and 4096 <= settings.max_bytes <= 1024**3
                and 1 <= settings.snapshot_timeout <= 90
                and settings.stale_seconds >= 300):
            raise BackupError('백업 보관 개수·용량·시간 제한 설정이 범위를 벗어났습니다.')
        return settings

    @property
    def snapshots(self):
        return self.prefix + '/snapshots/'

    @property
    def latest(self):
        return self.prefix + '/latest.json'

    @property
    def max_archive_bytes(self):
        return self.max_bytes + self.max_bytes // 100 + 1024 * 1024


@contextmanager
def operation_lock(settings):
    private_directory(settings.state)
    descriptor = os.open(settings.state / 'operation.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlreadyRunning('다른 백업/복원 작업이 진행 중입니다.') from None
        yield
    finally:
        os.close(descriptor)


def copy_stream(source, destination, maximum, deadline=None):
    total = 0
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise BackupError('백업 시간 제한을 초과했습니다.')
        chunk = source.read(min(CHUNK, maximum - total + 1))
        if not chunk:
            return total
        total += len(chunk)
        if total > maximum:
            raise BackupError('백업 파일이 설정된 최대 용량을 초과했습니다.')
        destination.write(chunk)


def digest(path, deadline=None):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(CHUNK):
            if deadline is not None and time.monotonic() > deadline:
                raise BackupError('백업 시간 제한을 초과했습니다.')
            checksum.update(chunk)
    return checksum.hexdigest()


def verify_database(path, deadline=None):
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        if deadline is not None:
            connection.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError('SQLite 무결성 검사에 실패했습니다.')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise BackupError('SQLite 참조 무결성 검사에 실패했습니다.')
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone() is None:
            raise BackupError('테이블이 없는 빈 SQLite DB는 백업/복원하지 않습니다.')
        return connection.execute('PRAGMA user_version').fetchone()[0]
    finally:
        connection.close()


def snapshot_database(source_path, target_path, settings):
    if source_path.is_symlink() or not source_path.is_file():
        raise BackupError('DB_PATH에 기존 SQLite 일반 파일을 지정하세요. 새 DB를 만들지 않습니다.')
    if source_path.stat().st_size > settings.max_bytes:
        raise BackupError('DB가 설정된 최대 백업 용량을 초과했습니다.')
    deadline = time.monotonic() + settings.snapshot_timeout
    descriptor = os.open(target_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True, timeout=0.2)) as source, \
            closing(sqlite3.connect(target_path)) as destination:
        page_size = source.execute('PRAGMA page_size').fetchone()[0]

        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise BackupError('SQLite 사본 생성 시간 제한을 초과했습니다.')
            if total * page_size > settings.max_bytes:
                raise BackupError('DB가 설정된 최대 백업 용량을 초과했습니다.')

        # SQLite's backup API includes committed WAL records without copying live WAL files.
        source.backup(destination, pages=128, progress=progress, sleep=0.05)
        destination.execute('PRAGMA journal_mode=DELETE')
    if target_path.stat().st_size > settings.max_bytes:
        raise BackupError('DB가 설정된 최대 백업 용량을 초과했습니다.')
    user_version = verify_database(target_path, deadline)
    return {'database_bytes': target_path.stat().st_size,
            'database_sha256': digest(target_path, deadline), 'sqlite_user_version': user_version}


def release_commit(directory=ROOT):
    try:
        commit = json.loads((directory / 'release.json').read_text()).get('commit', '')
        return commit if re.fullmatch(r'[0-9a-f]{40}', commit) else None
    except (OSError, ValueError):
        return None


def pack_snapshot(database, archive, manifest):
    # A single atomic object contains both the DB and its checksums/recovery metadata.
    with archive.open('xb') as raw:
        os.fchmod(raw.fileno(), 0o600)
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=1, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as bundle:
                metadata = json_bytes(manifest)
                info = tarfile.TarInfo('manifest.json')
                info.size, info.mode = len(metadata), 0o600
                bundle.addfile(info, io.BytesIO(metadata))
                info = tarfile.TarInfo('database.sqlite3')
                info.size, info.mode = database.stat().st_size, 0o600
                with database.open('rb') as source:
                    bundle.addfile(info, source)


def unpack_snapshot(archive, destination, settings):
    with tarfile.open(archive, mode='r|gz') as bundle:
        member = bundle.next()
        if member is None or member.name != 'manifest.json' or not member.isreg() or member.size > 16384:
            raise BackupError('백업 메타데이터가 올바르지 않습니다.')
        manifest = json.loads(bundle.extractfile(member).read())
        if (manifest.get('format') != 1 or not isinstance(manifest.get('database_bytes'), int)
                or not 0 < manifest['database_bytes'] <= settings.max_bytes
                or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('database_sha256', ''))):
            raise BackupError('지원하지 않거나 손상된 백업 메타데이터입니다.')
        parse_time(manifest['snapshot_started_at'])
        member = bundle.next()
        if (member is None or member.name != 'database.sqlite3' or not member.isreg()
                or member.size != manifest['database_bytes']):
            raise BackupError('백업 DB 항목 또는 크기가 올바르지 않습니다.')
        with destination.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            copied = copy_stream(bundle.extractfile(member), output, settings.max_bytes)
            output.flush()
            os.fsync(output.fileno())
        if copied != member.size or bundle.next() is not None:
            raise BackupError('백업 파일이 불완전하거나 예상하지 않은 항목이 있습니다.')
    if digest(destination) != manifest['database_sha256']:
        raise BackupError('백업 DB 체크섬이 일치하지 않습니다.')
    verify_database(destination, time.monotonic() + settings.snapshot_timeout)
    return manifest


class LocalStore:
    """Filesystem stand-in for an offsite store, solely for local verification."""
    def __init__(self, root):
        self.root = root.absolute()
        private_directory(self.root)

    def path(self, key):
        parts = PurePosixPath(key).parts
        if not parts or key.startswith('/') or '..' in parts or '\\' in key:
            raise BackupError('잘못된 백업 객체 경로입니다.')
        path = self.root.joinpath(*parts)
        if self.root.resolve() not in path.resolve().parents:
            raise BackupError('백업 저장소 밖의 경로는 사용할 수 없습니다.')
        return path

    def put(self, key, source):
        destination = self.path(key)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.upload-', dir=destination.parent)
        try:
            with os.fdopen(descriptor, 'wb') as output, source.open('rb') as input_file:
                shutil.copyfileobj(input_file, output, CHUNK)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)

    def get(self, key, destination, maximum):
        with self.path(key).open('rb') as source, destination.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            copy_stream(source, output, maximum)

    def keys(self, prefix):
        directory = self.path(prefix)
        return [path.relative_to(self.root).as_posix()
                for path in directory.rglob('*') if path.is_file()] if directory.exists() else []

    def delete(self, keys):
        for key in keys:
            self.path(key).unlink(missing_ok=True)


class GoogleDriveStore:
    """Use rclone with drive.file permission and one dedicated backup folder."""
    def __init__(self, environment, settings):
        self.settings = settings
        self.binary = local_path(environment.get('BACKUP_RCLONE_BIN', '/usr/local/lib/bbang-palja-backup/rclone'))
        self.config = local_path(environment.get('BACKUP_RCLONE_CONFIG',
                                                 str(settings.state / 'gdrive/rclone.conf')))
        self.remote = environment.get('BACKUP_DRIVE_REMOTE', 'cambo-backup:cambo-delight-backups').rstrip('/')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*:(?:[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)?', self.remote):
            raise BackupError('Google Drive remote에 백업 전용 폴더를 지정하세요.')
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise BackupError('백업 전용 rclone 실행 파일이 없습니다.')
        if self.config.is_symlink() or not self.config.is_file() or self.config.stat().st_mode & 0o077:
            raise BackupError('Google Drive 인증 파일은 일반 파일·권한 0600이어야 합니다.')
        config = configparser.ConfigParser(interpolation=None)
        config.read(self.config)
        name = self.remote.split(':', 1)[0]
        if (not config.has_section(name) or config[name].get('type') != 'drive'
                or config[name].get('scope') != 'drive.file' or not config[name].get('token')):
            raise BackupError('백업 전용 Drive 인증과 drive.file 권한이 필요합니다.')
        if self.remote.endswith(':') and not re.fullmatch(r'[A-Za-z0-9_-]{10,}', config[name].get('root_folder_id', '')):
            raise BackupError('Drive 루트를 쓰려면 백업 전용 root_folder_id가 필요합니다.')
        # Keep this transport on the personal Drive OAuth flow used during setup.
        client_credentials = config[name].get('client_credentials', '').strip().lower()
        if (client_credentials not in ('', 'false', '0', 'no', 'off')
                or any(config[name].get(key, '').strip() for key in (
                    'service_account_file', 'service_account_credentials', 'team_drive'))):
            raise BackupError('이 백업 도구는 개인 Drive의 제한된 사용자 인증만 지원합니다.')

    def _path(self, key):
        parts = key.rstrip('/').split('/')
        if (any(not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part in ('.', '..') for part in parts)
                or not (key == self.settings.latest or key.startswith(self.settings.snapshots))):
            raise BackupError('이 환경의 백업 경로만 Google Drive에서 접근할 수 있습니다.')
        return self.remote + ('' if self.remote.endswith(':') else '/') + key.rstrip('/')

    def _run(self, arguments, allow_missing=False):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('RCLONE_')}
        environment.update(GOMAXPROCS='1', GOMEMLIMIT='96MiB')
        command = [str(self.binary), '--config', str(self.config), '--log-level', 'ERROR',
                   '--retries', '1', '--low-level-retries', '2', '--contimeout', '5s',
                   '--timeout', '15s', '--transfers', '1', '--checkers', '1', '--buffer-size', '0',
                   '--multi-thread-streams', '0', '--drive-skip-shortcuts', *arguments]
        try:
            result = subprocess.run(command, env=environment, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            raise BackupError('Google Drive 요청 시간 제한을 초과했습니다.') from None
        if allow_missing and result.returncode == 3:
            return b'[]'
        if result.returncode:
            # Do not echo rclone's raw diagnostics: OAuth data must never enter API/journal logs.
            text = result.stderr.decode(errors='replace').lower()
            reason = '인증·용량·네트워크 확인 필요'
            if 'ratelimit' in text or 'rate limit' in text:
                reason = 'Google 요청 제한'
            elif 'invalid_grant' in text or 'unauthorized' in text:
                reason = 'Google 재인증 필요'
            elif 'not found' in text or 'notfound' in text:
                reason = '파일/폴더 조회 실패'
            elif 'timeout' in text or 'deadline' in text:
                reason = 'Google 응답 시간 초과'
            raise BackupError(f'Google Drive 작업 실패 (exit {result.returncode}, {reason}).')
        return result.stdout

    def _stat(self, key):
        # Listing the parent works reliably with drive.file even when rclone's direct
        # file stat cannot resolve an object. Also detect duplicate names explicitly.
        parent, _, name = self._path(key).rpartition('/')
        for attempt in range(3):
            entries = json.loads(self._run(['lsjson', parent, '--files-only', '--max-depth', '1',
                                           '--hash', '--hash-type', 'MD5'], allow_missing=True))
            if (not isinstance(entries, list) or any(not isinstance(item, dict)
                    or not isinstance(item.get('Path'), str) for item in entries)):
                raise BackupError('Google Drive 파일 목록 응답이 올바르지 않습니다.')
            matches = [item for item in entries if item.get('Path') == name]
            if len(matches) > 1:
                raise BackupError('Google Drive에 중복 파일 이름이 있습니다. 기존 백업을 유지합니다.')
            if matches:
                value = matches[0]
                break
            if attempt < 2:
                time.sleep(attempt + 1)
        else:
            raise BackupError('Google Drive에서 백업 파일을 아직 찾을 수 없습니다. 기존 백업을 유지합니다.')
        if (not isinstance(value, dict) or value.get('IsDir') or not isinstance(value.get('Size'), int)
                or value['Size'] < 0 or not re.fullmatch(r'[0-9a-f]{32}', value.get('Hashes', {}).get('md5', ''))):
            raise BackupError('Google Drive 백업 파일의 크기·체크섬을 확인하지 못했습니다.')
        return value

    @staticmethod
    def _md5(path):
        checksum = hashlib.md5(usedforsecurity=False)
        with path.open('rb') as source:
            while chunk := source.read(CHUNK):
                checksum.update(chunk)
        return checksum.hexdigest()

    def put(self, key, source):
        self._run(['copyto', str(source), self._path(key), '--ignore-times'])
        remote = self._stat(key)
        if remote['Size'] != source.stat().st_size or remote['Hashes']['md5'] != self._md5(source):
            raise BackupError('Google Drive 업로드 크기·체크섬이 일치하지 않습니다.')

    def get(self, key, destination, maximum):
        if destination.exists():
            raise BackupError('다운로드 대상 파일이 이미 있습니다.')
        remote = self._stat(key)
        if remote['Size'] > maximum:
            raise BackupError('Google Drive 백업이 최대 다운로드 용량을 초과했습니다.')
        self._run(['copyto', self._path(key), str(destination), '--ignore-times',
                   '--max-transfer', str(maximum), '--cutoff-mode', 'hard'])
        destination.chmod(0o600)
        if destination.stat().st_size != remote['Size'] or self._md5(destination) != remote['Hashes']['md5']:
            raise BackupError('Google Drive 다운로드 크기·체크섬이 일치하지 않습니다.')

    def keys(self, prefix):
        if prefix != self.settings.snapshots:
            raise BackupError('이 환경의 snapshots 폴더만 조회할 수 있습니다.')
        items = json.loads(self._run(['lsjson', self._path(prefix), '--files-only', '--max-depth', '1'],
                                    allow_missing=True))
        if (not isinstance(items, list) or any(not isinstance(item, dict)
                or not isinstance(item.get('Path'), str) for item in items)):
            raise BackupError('Google Drive 파일 목록 응답이 올바르지 않습니다.')
        keys = []
        for item in items:
            name = item.get('Path', '')
            if '/' in name or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
                continue
            keys.append(prefix + name)
        if len(keys) != len(set(keys)):
            raise BackupError('Google Drive에 중복 이름이 있습니다. 기존 사본을 유지하고 정리를 멈춥니다.')
        return keys

    def delete(self, keys):
        if not keys:
            return
        for key in keys:
            if snapshot_time(self.settings, key) is None:
                raise BackupError('이 환경의 자동 백업 파일만 정리할 수 있습니다.')
        # Delete only explicitly selected old snapshots; never empty the user's whole trash.
        descriptor, name = tempfile.mkstemp(prefix='.delete-', dir=self.config.parent)
        try:
            with os.fdopen(descriptor, 'w') as output:
                output.write(''.join(key[len(self.settings.snapshots):] + '\n' for key in keys))
            self._run(['delete', self._path(self.settings.snapshots), '--files-from-raw', name,
                       '--drive-use-trash=false'])
        finally:
            Path(name).unlink(missing_ok=True)


def remote_store(environment, settings):
    backend = environment.get('BACKUP_BACKEND', 'gdrive')
    if backend == 'gdrive':
        return GoogleDriveStore(environment, settings)
    raise BackupError('BACKUP_BACKEND는 gdrive여야 합니다.')


def snapshot_time(settings, key):
    if not key.startswith(settings.snapshots):
        return None
    match = SNAPSHOT_NAME.fullmatch(key[len(settings.snapshots):])
    if match is None:
        return None
    try:
        return datetime.strptime(match[1], '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def prune_snapshots(settings, store, protected):
    snapshots = [(date, key) for key in store.keys(settings.snapshots)
                 if (date := snapshot_time(settings, key)) is not None]
    snapshots.sort(reverse=True)
    keep = {key for _, key in snapshots[:settings.recent]} | {protected}
    hours = set()
    for date, key in snapshots:
        hour = date.replace(minute=0, second=0, microsecond=0)
        if hour not in hours and len(hours) < settings.hourly:
            hours.add(hour)
            keep.add(key)
    obsolete = [key for _, key in snapshots if key not in keep]
    store.delete(obsolete)
    return len(obsolete)


def read_state(settings):
    path = settings.state / 'status.json'
    return json.loads(path.read_text()) if path.exists() else {}


def perform_backup(settings, store, now=None):
    now = now or utc_now()
    with operation_lock(settings):
        # A killed run can leave private working files. No previous run holds the lock now.
        for leftover in settings.state.glob('.run-*'):
            if leftover.is_dir() and not leftover.is_symlink():
                shutil.rmtree(leftover)
        status = read_state(settings)
        status.update(last_attempt_at=iso(now), last_error=None)
        write_json(settings.state / 'status.json', status)
        try:
            with tempfile.TemporaryDirectory(prefix='.run-', dir=settings.state) as folder:
                work = Path(folder)
                database, archive = work / 'database.sqlite3', work / 'snapshot.tar.gz'
                details = snapshot_database(settings.database, database, settings)
                manifest = {'format': 1, 'snapshot_started_at': iso(now),
                            'snapshot_completed_at': iso(utc_now()),
                            'code_commit': release_commit(settings.app_directory), **details}
                pack_snapshot(database, archive, manifest)
                if archive.stat().st_size > settings.max_archive_bytes:
                    raise BackupError('압축된 백업이 최대 용량을 초과했습니다.')
                name = now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8] + '.tar.gz'
                key = settings.snapshots + name
                store.put(key, archive)
                latest = {**manifest, 'key': key, 'archive_bytes': archive.stat().st_size,
                          'archive_sha256': digest(archive)}
                pointer = work / 'latest.json'
                write_json(pointer, latest)
                # Publish only a fully uploaded object; failed uploads never move the pointer.
                store.put(settings.latest, pointer)
                status.update(last_success_at=iso(utc_now()), snapshot_started_at=iso(now),
                              latest_key=key, database_bytes=details['database_bytes'],
                              archive_bytes=archive.stat().st_size)
                write_json(settings.state / 'status.json', status)
                deleted = prune_snapshots(settings, store, protected=key)
                status['deleted_snapshots'] = deleted
                write_json(settings.state / 'status.json', status)
                return {'ok': True, 'key': key, 'snapshot_started_at': iso(now),
                        'database_bytes': details['database_bytes'], 'archive_bytes': archive.stat().st_size,
                        'deleted_snapshots': deleted}
        except Exception as error:
            # OS/transport exception text can contain URLs or sensitive paths; store only its type.
            status['last_error'] = type(error).__name__
            write_json(settings.state / 'status.json', status)
            raise


def backup_status(settings, now=None):
    status = read_state(settings)
    snapshot_at = status.get('snapshot_started_at')
    age = max(0, ((now or utc_now()) - parse_time(snapshot_at)).total_seconds()) if snapshot_at else None
    return {**status, 'ok': age is not None and age <= settings.stale_seconds and not status.get('last_error'),
            'snapshot_age_seconds': round(age) if age is not None else None}


def read_latest(settings, store, directory):
    pointer = directory / 'latest.json'
    store.get(settings.latest, pointer, 16384)
    value = json.loads(pointer.read_text())
    if (value.get('format') != 1 or snapshot_time(settings, value.get('key', '')) is None
            or not re.fullmatch(r'[0-9a-f]{64}', value.get('archive_sha256', ''))):
        raise BackupError('최신 백업 포인터가 올바르지 않습니다.')
    return value


def restore_backup(settings, store, destination, key='latest', replace=False, api_stopped=False):
    if not api_stopped:
        raise BackupError('대상 API와 배포·백업 타이머를 멈춘 뒤 --api-stopped를 지정하세요.')
    destination = destination.absolute()
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise BackupError('복원 경로는 일반 파일이어야 합니다.')
    if destination.exists() and not replace:
        raise BackupError('기존 DB를 보존했습니다. 교체하려면 --replace를 명시하세요.')
    if key != 'latest' and snapshot_time(settings, key) is None:
        raise BackupError('이 환경의 snapshots 아래에 있는 백업 키를 지정하세요.')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with operation_lock(settings):
        with tempfile.TemporaryDirectory(prefix='.restore-', dir=destination.parent) as folder:
            work = Path(folder)
            latest = read_latest(settings, store, work) if key == 'latest' else None
            object_key = latest['key'] if latest else key
            archive, fresh = work / 'snapshot.tar.gz', work / 'database.sqlite3'
            store.get(object_key, archive, settings.max_archive_bytes)
            if latest and digest(archive) != latest['archive_sha256']:
                raise BackupError('다운로드한 백업 체크섬이 최신 포인터와 일치하지 않습니다.')
            manifest = unpack_snapshot(archive, fresh, settings)
            metadata = destination.stat() if destination.exists() else None
            rollback = None
            if metadata:
                directory = destination.parent / 'before-restore'
                private_directory(directory)
                rollback = directory / (utc_now().strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
                snapshot_database(destination, rollback, settings)
                # Never allow old WAL records to be replayed into the restored DB.
                original = sqlite3.connect(destination, timeout=1)
                try:
                    if original.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                        raise BackupError('기존 DB가 사용 중입니다. API를 종료하세요.')
                    if original.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
                        raise BackupError('기존 DB 저널을 정리하지 못했습니다.')
                finally:
                    original.close()
                if os.geteuid() == 0:
                    os.chown(fresh, metadata.st_uid, metadata.st_gid)
                fresh.chmod(stat.S_IRUSR | stat.S_IWUSR)
            elif any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-shm')):
                raise BackupError('기존 DB 없는 경로에 WAL/SHM 파일이 있습니다. 경로를 확인하세요.')
            os.replace(fresh, destination)
            # Everything was checkpointed with the API stopped before the atomic replace.
            for suffix in ('-wal', '-shm'):
                Path(str(destination) + suffix).unlink(missing_ok=True)
            return {'ok': True, 'database': str(destination), 'key': object_key,
                    'snapshot_started_at': manifest['snapshot_started_at'],
                    'code_commit': manifest.get('code_commit'),
                    'before_restore': str(rollback) if rollback else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, action='append', default=[],
                        help='KEY=value 파일. 여러 번 지정하면 뒤 파일이 우선합니다.')
    parser.add_argument('--local-store', type=Path, help='로컬 검증용 저장 폴더. 실제 원격 백업이 아닙니다.')
    subcommands = parser.add_subparsers(dest='command', required=True)
    subcommands.add_parser('backup', help='사본 생성·검증·업로드 후 보관 개수 정리')
    subcommands.add_parser('list', help='이 환경에 보관된 백업 키 조회')
    subcommands.add_parser('status', help='마지막 백업 상태. 15분 이상 오래되거나 실패 시 exit 1')
    restore = subcommands.add_parser('restore', help='검증 후 명시적으로 DB 복원. API는 자동 시작하지 않음')
    restore.add_argument('--destination', type=Path, required=True)
    restore.add_argument('--key', default='latest')
    restore.add_argument('--replace', action='store_true')
    restore.add_argument('--api-stopped', action='store_true', help='대상 API·배포·백업 타이머 중지를 확인')
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        environment = environment_files(args.env_file)
        settings = Settings.from_environment(environment)
        if args.command == 'status':
            result = backup_status(settings)
        else:
            store = LocalStore(args.local_store) if args.local_store else remote_store(environment, settings)
            if args.command == 'backup':
                result = perform_backup(settings, store)
            elif args.command == 'list':
                result = {'ok': True, 'keys': sorted(key for key in store.keys(settings.snapshots)
                                                   if snapshot_time(settings, key) is not None)}
            else:
                result = restore_backup(settings, store, args.destination, args.key,
                                        args.replace, args.api_stopped)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 1
    except AlreadyRunning:
        if args.command == 'backup':
            print(json.dumps({'ok': True, 'skipped': 'another_operation_is_running'}))
            return 0
        print('다른 백업/복원 작업이 진행 중입니다.', file=sys.stderr)
        return 1
    except BackupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f'백업 작업 실패 ({type(error).__name__}). 상태·권한·네트워크를 확인하세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
