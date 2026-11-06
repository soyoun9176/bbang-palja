#!/usr/bin/env python3
"""Explicit SQLite rebuild with a verified backup. Stop the API before running."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.app import Application
from server.db import Database


def load_environment(path):
    for raw in path.read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith('#'):
            continue
        key,separator,value=line.partition('=')
        if not separator or not key.replace('_','').isalnum():
            raise ValueError('환경 파일은 KEY=value 형식이어야 합니다.')
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
            value=value[1:-1]
        os.environ[key]=value


def rebuild(*,demo=False,backup_dir=None):
    database=Database(ROOT)
    if database.postgres:
        raise RuntimeError('이 명령은 SQLite 전용입니다. DATABASE_URL을 확인하세요. PostgreSQL은 변경하지 않았습니다.')
    if demo and os.environ.get('APP_ENV','local').lower()=='production':
        raise RuntimeError('운영 환경에서는 데모 데이터를 만들 수 없습니다.')
    target=database.path.absolute()
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise RuntimeError('DB 경로는 일반 파일이어야 합니다.')
    metadata=target.stat() if target.exists() else None
    backup=None
    if metadata:
        directory=(backup_dir or target.parent/'backups').absolute()
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=directory/('before-reset-'+stamp+'.sqlite3')
        descriptor=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
        os.close(descriptor)
        source=sqlite3.connect(target.as_uri()+'?mode=ro',uri=True,timeout=20)
        copy=sqlite3.connect(backup)
        try:
            source.backup(copy)
            if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise RuntimeError('DB 백업 무결성 검사에 실패했습니다. 원본을 유지합니다.')
        finally:
            source.close();copy.close()
    descriptor,temporary=tempfile.mkstemp(prefix='.'+target.name+'.reset-',suffix='.sqlite3',dir=target.parent)
    os.close(descriptor)
    temporary=Path(temporary)
    old_environment=dict(os.environ)
    try:
        os.environ['DB_PATH']=str(temporary)
        os.environ['DEMO_SEED']='1' if demo else '0'
        app=Application()
        if not demo:
            with app.db.transaction(write=True) as tx:
                # Do not repopulate old sample accounts on a later default startup.
                tx.execute("INSERT INTO settings(key,value) VALUES('demo_seeded','1') ON CONFLICT(key) DO NOTHING")
        with sqlite3.connect(temporary) as fresh:
            if fresh.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or fresh.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('새 DB 검증에 실패했습니다. 원본을 유지합니다.')
            fresh.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            fresh.execute('PRAGMA journal_mode=DELETE')
        if metadata:
            with sqlite3.connect(target,timeout=20) as original:
                busy=original.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]
                if busy:
                    raise RuntimeError('DB 사용 중입니다. API를 멈추고 다시 실행하세요.')
            temporary.chmod(stat.S_IMODE(metadata.st_mode))
            if os.geteuid()==0:
                os.chown(temporary,metadata.st_uid,metadata.st_gid)
        os.replace(temporary,target)
        for suffix in ('-wal','-shm'):
            Path(str(target)+suffix).unlink(missing_ok=True)
        return {'database':str(target),'backup':str(backup) if backup else None,
                'schema':'phone_accounts_v1','mode':'demo' if demo else 'empty'}
    finally:
        os.environ.clear();os.environ.update(old_environment)
        for suffix in ('','-wal','-shm'):
            Path(str(temporary)+suffix).unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yes',action='store_true',help='계정·주문·재고를 백업 후 초기화하는 데 동의')
    parser.add_argument('--demo',action='store_true',help='빈 DB 대신 로컬 시연 데이터 생성')
    parser.add_argument('--env-file',type=Path,help='DB_PATH 등 설정 파일 (내용을 출력하지 않음)')
    parser.add_argument('--backup-dir',type=Path,help='백업 저장 폴더. 기본 DB 폴더/backups')
    args=parser.parse_args()
    if not args.yes:
        parser.error('API를 멈춘 뒤 --yes를 지정하세요. 계정·주문·예약·점수·재고가 새로 생성됩니다.')
    try:
        if args.env_file:
            load_environment(args.env_file)
        result=rebuild(demo=args.demo,backup_dir=args.backup_dir)
    except Exception as error:
        parser.exit(1,f'DB 재생성 실패: {error}\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
