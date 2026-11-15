#!/usr/bin/env python3
"""Validate a flat preorder CSV; reserve existing stock only with --apply."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.app import Application, optional_phone, person_name
from server.catalog import PRODUCTS
from server.db import Database


def header_key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', value))


MENU_HEADERS = {header_key(product[1]): product[0] for product in PRODUCTS}
MENU_HEADERS.update({
    '휘낭시에(플레인)': 101, '휘낭시에(초코)': 102, '휘낭시에(카라멜)': 103,
    '휘낭시에(무화과)': 104, '다쿠아즈(레몬)': 106, '다쿠아즈(얼그레이)': 107,
    '글레이즈드도넛': 108,
})


def read_preorders(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.reader(handle, strict=True))
    if not rows:
        raise ValueError('빈 CSV입니다.')
    headers = [header_key(cell) for cell in rows[0]]
    while headers and not headers[-1]:
        headers.pop()
    if headers.count('이름') != 1 or headers.count('연락처') != 1:
        raise ValueError('첫 행에 이름·연락처 열을 각각 한 번 넣어 주세요.')
    columns = {}
    for index, header in enumerate(headers):
        if header in ('이름', '연락처'):
            continue
        product_id = MENU_HEADERS.get(header)
        if product_id is None:
            raise ValueError(f'알 수 없는 메뉴 열입니다: {rows[0][index]}')
        if product_id in columns.values():
            raise ValueError(f'같은 메뉴 열이 중복됐습니다: {rows[0][index]}')
        columns[index] = product_id
    if not columns:
        raise ValueError('메뉴 수량 열을 하나 이상 넣어 주세요.')
    reservations = []
    seen = set()
    for line, raw in enumerate(rows[1:], 2):
        if not any(cell.strip() for cell in raw):
            continue
        try:
            if any(cell.strip() for cell in raw[len(headers):]):
                raise ValueError('제목이 없는 열에 값이 있습니다.')
            row = [cell.strip() for cell in raw[:len(headers)]]
            row += [''] * (len(headers) - len(row))
            name = person_name(row[headers.index('이름')])
            phone = optional_phone(row[headers.index('연락처')])
            if phone is not None and (name, phone) in seen:
                raise ValueError('같은 이름·연락처가 중복됐습니다. 예약 건수를 확인해 주세요.')
            seen.add((name, phone))
            items = []
            for index, product_id in columns.items():
                value = row[index] or '0'
                if not re.fullmatch(r'[0-9]+', value) or int(value) > 100:
                    raise ValueError(f'{rows[0][index]} 수량은 0~100 정수로 입력해 주세요.')
                if int(value):
                    items.append({'product_id': product_id, 'quantity': int(value)})
            if not items or sum(item['quantity'] for item in items) > 100:
                raise ValueError('예약 한 건의 총수량은 1~100개여야 합니다.')
            reservations.append({'name': name, 'phone': phone, 'items': items})
        except Exception as error:
            raise ValueError(f'CSV {line}행: {error}') from error
    if not 1 <= len(reservations) <= 500:
        raise ValueError('예약 목록은 1~500건이어야 합니다.')
    return reservations


def run_import(path, *, apply=False, actor='CSV 예판 등록'):
    reservations = read_preorders(path)
    canonical = [{**row, 'items': sorted(row['items'], key=lambda item: item['product_id'])} for row in reservations]
    batch = hashlib.sha256(json.dumps(sorted(canonical, key=lambda row: json.dumps(row, sort_keys=True)), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    database = Database(ROOT)
    if database.postgres:
        raise RuntimeError('이 도구는 현재 운영 중인 SQLite DB 전용입니다.')
    if database.path.is_symlink() or not database.path.is_file():
        raise RuntimeError('기존 DB의 DB_PATH를 지정해 주세요. 새 DB를 자동 생성하지 않습니다.')
    # Reuse API validation without Application startup, catalog changes or demo seeding.
    with database.transaction(write=apply) as tx:
        columns = {row['name']: row for row in tx.all('PRAGMA table_info(reservations)')}
        if 'import_batch' not in columns or columns['phone']['notnull']:
            raise RuntimeError('예판 DB 구조를 업데이트하려면 새 코드로 API 서버를 한 번 재시작해 주세요.')
        report = Application.import_reservations(tx, reservations, actor, dry_run=True, import_batch=batch)
        if apply and report['ready']:
            Application.import_reservations(tx, reservations, actor, import_batch=batch)
    return {'database': str(database.path.absolute()), 'mode': 'apply' if apply else 'check',
            'applied': apply and report['ready'], **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--apply', action='store_true', help='검증 후 예약 등록·재고 이동; 기본은 미리보기')
    parser.add_argument('--env-file', type=Path, help='DB_PATH 등 설정 파일')
    args = parser.parse_args()
    try:
        if args.env_file:
            # Share the same KEY=value loader as the reset tool.
            import runpy
            runpy.run_path(str(ROOT / 'ops/reset-db.py'))['load_environment'](args.env_file)
        result = run_import(args.csv, apply=args.apply)
    except Exception as error:
        parser.exit(1, f'예판 CSV 등록 실패: {error}\n')
    print(json.dumps(result, ensure_ascii=False))
    if not result['ready']:
        parser.exit(2, '예판 배정 재고가 부족합니다. 관리자 재고관리에서 총재고를 먼저 입력해 주세요.\n')


if __name__ == '__main__':
    main()
