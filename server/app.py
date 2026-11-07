"""HTTP application and atomic bakery event operations."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
from socketserver import TCPServer
import traceback
from urllib.parse import parse_qs, unquote, urlsplit

from .db import Database
from .catalog import PRODUCT_IDS, PRODUCT_UNITS, PRODUCT_PHOTOS, MILK_PRODUCT_ID, SOYMILK_PRODUCT_ID, DRINK_PRODUCT_IDS, REWARD_PRODUCT_IDS, dice_quantity, sync_catalog
from .game import DICE, MILESTONES, public_dice, preorder_kind

ROOT = Path(__file__).resolve().parents[1]
MAX_CHARACTER_LEVEL = 5
PUBLIC_USER_FIELDS = ("id", "name", "role", "score", "dice_balance", "rewards_claimed")
AVATAR_OPTIONS = {
    "face_shape": ("madeleine", "financier", "pound"),
    "skin": ("light", "warm", "deep"),
    "expression": ("smile", "happy", "wink", "surprised"),
    "glasses": ("none", "round", "square", "sunglasses"),
    "hairpin": ("none",) + tuple(f"bread_{pid}" for pid in REWARD_PRODUCT_IDS),
}
LEGACY_FACE_SHAPES = {"round": "madeleine", "oval": "financier", "square": "pound",
                      "soboro": "madeleine", "salt": "financier", "toast": "pound"}
LEGACY_HAIR_OPTIONS = {"hair_style": ("crop", "bob", "waves", "curls"),
                       "hair_color": ("cocoa", "ink", "honey", "plum")}


def default_avatar(user_id):
    seed = user_id or 0
    fixed = {"expression": "smile", "glasses": "none", "hairpin": "none"}
    return {key: fixed[key] if key in fixed else choices[seed % len(choices)]
            for key, choices in AVATAR_OPTIONS.items()}


def hairpin_ownership(tx, user_id=None):
    rows = tx.all("SELECT DISTINCT o.user_id,i.product_id FROM orders o JOIN order_items i ON i.order_id=o.id "
                  "WHERE o.status='approved'" + (" AND o.user_id=?" if user_id is not None else "") +
                  " ORDER BY o.user_id,i.product_id", (user_id,) if user_id is not None else ())
    owned = {}
    for row in rows:
        if row["product_id"] in REWARD_PRODUCT_IDS:
            owned.setdefault(row["user_id"], ["none"]).append(f"bread_{row['product_id']}")
    return owned


def profile_rows(tx, rows, user_id=None):
    owned = hairpin_ownership(tx, user_id)
    suffix, args = (" WHERE user_id=?", (user_id,)) if user_id is not None else ("", ())
    wallets, claims = {}, {}
    for item in tx.all("SELECT user_id,kind,quantity FROM dice_wallet" + suffix, args):
        if item['kind'] in DICE and item['quantity']:
            wallets.setdefault(item['user_id'], []).append({**public_dice(item['kind']), 'quantity': item['quantity']})
    for item in tx.all("SELECT user_id,threshold FROM milestone_claims" + suffix, args):
        claims.setdefault(item['user_id'], []).append(item['threshold'])
    manual_glasses = {item['user_id'] for item in tx.all(
        "SELECT DISTINCT user_id FROM manual_event_grants WHERE gift_key='sunglasses'" +
        (' AND user_id=?' if user_id is not None else ''), args)}
    return [{**row, "unlocked_hairpins": owned.get(row["id"], ["none"]),
             "dice": sorted(wallets.get(row['id'], []), key=lambda d: list(DICE).index(d['kind'])),
             "claimed_milestones": sorted(claims.get(row['id'], [])),
             "manual_sunglasses": row['id'] in manual_glasses} for row in rows]


def has_sunglasses(user):
    return 15 in user.get('claimed_milestones', []) or user.get('manual_sunglasses', False)


def profile_info(row):
    avatar = default_avatar(row["id"])
    stored = row.get("appearance")
    if stored:
        try:
            saved = json.loads(stored)
            if isinstance(saved, dict):
                if isinstance(saved.get("face_shape"), str):
                    saved["face_shape"] = LEGACY_FACE_SHAPES.get(saved["face_shape"], saved["face_shape"])
                avatar.update({key: value for key, value in saved.items()
                               if key in AVATAR_OPTIONS and isinstance(value, str) and value in AVATAR_OPTIONS[key]})
        except (ValueError, TypeError):
            pass
    if avatar["hairpin"] not in row.get("unlocked_hairpins", ["none"]):
        avatar["hairpin"] = "none"
    if avatar['glasses'] == 'sunglasses' and not has_sunglasses(row):
        avatar['glasses'] = 'none'
    return {"avatar": avatar, "profile_customized": bool(stored)}


def validate_avatar(value):
    check(isinstance(value, dict), "캐릭터 꾸미기 항목을 모두 선택해 주세요.")
    current = set(AVATAR_OPTIONS)
    legacy = (current - {"expression"}) | set(LEGACY_HAIR_OPTIONS)
    check(set(value) in (current, legacy, legacy | {"expression"}), "캐릭터 꾸미기 항목을 모두 선택해 주세요.")
    value = dict(value)
    for key, choices in LEGACY_HAIR_OPTIONS.items():
        if key in value:
            check(isinstance(value[key], str) and value[key] in choices, "선택할 수 없는 캐릭터 꾸미기 항목입니다.")
    if "hair_style" in value and value.get("hairpin") in ("star", "flower", "leaf"):
        value["hairpin"] = "none"
    value.setdefault("expression", "smile")
    if isinstance(value["face_shape"], str):
        value["face_shape"] = LEGACY_FACE_SHAPES.get(value["face_shape"], value["face_shape"])
    for key, choices in AVATAR_OPTIONS.items():
        check(isinstance(value[key], str) and value[key] in choices, "선택할 수 없는 캐릭터 꾸미기 항목입니다.")
    return {key: value[key] for key in AVATAR_OPTIONS}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def check(condition, message, status=400):
    if not condition:
        raise APIError(status, message)


def integer(value, label, minimum=1, maximum=999):
    check(type(value) is int and minimum <= value <= maximum, f"{label}: {minimum}~{maximum} 사이의 정수를 입력해 주세요.")
    return value


def string(value, label, maximum=100, minimum=1):
    check(isinstance(value, str), f"{label}을(를) 입력해 주세요.")
    result = value.strip()
    check(minimum <= len(result) <= maximum, f"{label}: {minimum}~{maximum}자로 입력해 주세요.")
    return result


def person_name(value):
    return string(value, "이름", maximum=30)


def phone_number(value):
    check(isinstance(value,str) and re.fullmatch(r'(?:010[0-9]{8}|010-[0-9]{4}-[0-9]{4})',value) is not None,
          '전화번호는 01012345678 또는 010-1234-5678 형식으로 입력해 주세요. 숫자와 정해진 위치의 대시만 사용할 수 있어요.')
    digits=value.replace('-','')
    return f'{digits[:3]}-{digits[3:7]}-{digits[7:]}'


def pin_value(value):
    check(isinstance(value, str) and re.fullmatch(r"[0-9]{4}", value) is not None, "비밀번호는 숫자 네 자리로 입력해 주세요.")
    return value


def hash_pin(pin):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 160_000).hex()
    return f"pbkdf2_sha256$160000${salt}${digest}"


def verify_pin(pin, encoded):
    try:
        _, rounds, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def public_user(row):
    user = {key: row[key] for key in PUBLIC_USER_FIELDS}
    user["level"] = min(MAX_CHARACTER_LEVEL, row["rewards_claimed"])
    user.update(profile_info(row))
    user["unlocked_hairpins"] = row.get("unlocked_hairpins", ["none"])
    user['dice'] = row.get('dice', [])
    user['claimed_milestones'] = row.get('claimed_milestones', [])
    user['sunglasses_unlocked'] = has_sunglasses(row)
    return user


def grant_dice(tx, user_id, kind, quantity):
    if not quantity:
        return
    tx.execute('INSERT INTO dice_wallet(user_id,kind,quantity) VALUES(?,?,?) '
               'ON CONFLICT(user_id,kind) DO UPDATE SET quantity=dice_wallet.quantity+excluded.quantity',
               (user_id, kind, quantity))
    tx.execute('UPDATE users SET dice_balance=dice_balance+? WHERE id=?', (quantity, user_id))


def order_dice(order):
    if 'user_id' in order and order['user_id'] is None:
        return ('walkin', 0)
    count = dice_quantity(order['items'])
    return (preorder_kind(order['total']), 1 if count else 0) if order['type'] == 'preorder' else ('walkin', count)


def reward_requests(tx, user_id=None):
    rows = tx.all('SELECT r.*,u.name AS customer_name,COALESCE(m.threshold,0) AS threshold '
                  'FROM reward_requests r JOIN users u ON u.id=r.user_id '
                  'LEFT JOIN milestone_claims m ON m.id=r.milestone_id' +
                  (' WHERE r.user_id=?' if user_id is not None else '') + ' ORDER BY r.id DESC',
                  (user_id,) if user_id is not None else ())
    if user_id is None:
        inventory = {p['id']: p['stock'] for p in tx.all('SELECT id,stock FROM products')}
        supplies = {p['key']: p['stock'] for p in tx.all('SELECT key,stock FROM event_supplies')}
        for row in rows:
            row['remaining_stock'] = inventory.get(row['product_id']) if row['product_id'] else supplies.get(row['supply_key'])
    else:
        for row in rows:
            row.pop('processed_by')
    return rows


def reward_request(tx, request_id):
    row = tx.one('SELECT * FROM reward_requests WHERE id=?', (request_id,))
    check(row is not None, '이벤트 지급 요청을 찾을 수 없습니다.', 404)
    return row


def change_supply(tx, key, delta, reason, actor):
    supply = tx.one('SELECT * FROM event_supplies WHERE key=?', (key,))
    check(supply is not None, '이벤트 물품을 찾을 수 없습니다.', 404)
    check(supply['stock'] + delta >= 0, f"{supply['name']} 재고가 부족합니다. 담당자에게 문의해 주세요.", 409)
    tx.execute('UPDATE event_supplies SET stock=stock+? WHERE key=?', (delta,key))
    tx.insert('INSERT INTO inventory_logs(product_name,bucket,delta,reason,actor,created_at) VALUES(?,?,?,?,?,?)',
              (supply['name'], 'event_supply', delta, reason, actor, now()))


def create_reward_request(tx, user, kind, selected=None, *, milestone_id=None, roll_id=None):
    selected = selected or {'id': None, 'name': '우유·두유 선택'}
    reason = f"{user['name']} 이벤트 지급 요청 · 재고 확보"
    if kind == 'bread':
        change_inventory(tx, selected['id'], 'stock', -1, reason, user['name'])
    elif kind == 'oatmeal':
        change_supply(tx, 'oatmeal', -1, reason, user['name'])
    stamp = now()
    request_id = tx.insert('INSERT INTO reward_requests(user_id,milestone_id,roll_id,kind,status,product_id,supply_key,product_name,created_at,requested_at) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (user['id'],milestone_id,roll_id,kind,'awaiting_choice' if kind=='milk' else 'pending',
                            selected['id'],'oatmeal' if kind=='oatmeal' else None,selected['name'],stamp,None if kind=='milk' else stamp))
    return reward_request(tx, request_id)


def process_reward_request(tx, row, action, actor):
    desired = 'approved' if action == 'approve' else 'cancelled'
    if row['status'] == desired:
        return row
    check(row['status'] in ('pending','awaiting_choice'), '이미 처리된 이벤트 요청입니다. 현재 상태를 확인해 주세요.', 409)
    if desired == 'approved':
        check(row['status'] == 'pending', '구매자가 우유 또는 두유를 먼저 선택해야 합니다.', 409)
    elif row['status'] == 'pending':
        reason = f"이벤트 요청 #{row['id']} 취소 · 재고 반환"
        if row['product_id'] is not None:
            change_inventory(tx, row['product_id'], 'stock', 1, reason, actor)
        else:
            change_supply(tx, row['supply_key'], 1, reason, actor)
    tx.execute('UPDATE reward_requests SET status=?,processed_at=?,processed_by=? WHERE id=?', (desired,now(),actor,row['id']))
    return reward_request(tx, row['id'])


def reward_history(tx, user_id=None):
    where, args = (' WHERE r.user_id=?', (user_id,)) if user_id is not None else ('', ())
    current = tx.all('SELECT r.id,r.user_id,r.product_id,r.product_name,r.threshold,r.kind,r.created_at,u.name AS customer_name '
                     'FROM milestone_claims r JOIN users u ON u.id=r.user_id' + where + ' ORDER BY r.id DESC LIMIT 300', args)
    legacy = tx.all("SELECT r.id,r.user_id,r.product_id,r.product_name,r.threshold,'legacy_bread' AS kind,r.created_at,u.name AS customer_name "
                    'FROM rewards r JOIN users u ON u.id=r.user_id' + where + ' ORDER BY r.id DESC LIMIT 300', args)
    milk = tx.all("SELECT r.id,r.user_id,NULL AS product_id,'우유' AS product_name,0 AS threshold,'dice_milk' AS kind,r.created_at,u.name AS customer_name "
                  "FROM typed_dice_rolls r JOIN users u ON u.id=r.user_id" +
                  (' WHERE r.user_id=? AND' if user_id is not None else ' WHERE') +
                  " r.result='milk' ORDER BY r.id DESC LIMIT 300", args)
    requests = reward_requests(tx, user_id)
    milestones = {r['milestone_id']:r for r in requests if r['milestone_id'] is not None}
    rolls = {r['roll_id']:r for r in requests if r['roll_id'] is not None}
    for item in current + milk:
        item['fulfillment'] = (rolls if item['kind']=='dice_milk' else milestones).get(item['id'])
        if item['fulfillment']:
            item['product_name'] = item['fulfillment']['product_name']
            item['product_id'] = item['fulfillment']['product_id']
    return sorted(current + legacy + milk, key=lambda r: r['created_at'], reverse=True)[:300]


def user_by_id(tx, user_id, buyer=False):
    user = tx.one("SELECT u.*,p.appearance FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id WHERE u.id = ?", (user_id,))
    check(user is not None and (not buyer or user["role"] == "buyer"), "구매자 계정을 찾을 수 없습니다.", 404)
    return profile_rows(tx, [user], user_id)[0]


def products(tx):
    placeholders = ','.join('?' for _ in PRODUCT_IDS)
    rows = tx.all(f"SELECT * FROM products WHERE id IN ({placeholders}) ORDER BY id", PRODUCT_IDS)
    return [{**row, "unit": PRODUCT_UNITS.get(row["id"], "개"), "photo": PRODUCT_PHOTOS.get(row["id"], ""),
             "dice_per_unit": 0 if row["id"] in DRINK_PRODUCT_IDS else 1,
             "beverage_reward_eligible": row['id'] in DRINK_PRODUCT_IDS,
             "reward_eligible": row["id"] in REWARD_PRODUCT_IDS} for row in rows]


def milk_stock(tx):
    return tx.one("SELECT stock FROM products WHERE id = ?", (MILK_PRODUCT_ID,))["stock"]


def merge_legacy_milk_stock(tx):
    legacy = tx.one("SELECT value FROM settings WHERE key = 'milk_stock'")
    count = int(legacy['value']) if legacy else 0
    if count:
        tx.execute('UPDATE products SET stock = stock + ? WHERE id = ?', (count,MILK_PRODUCT_ID))
        tx.execute("UPDATE settings SET value = '0' WHERE key = 'milk_stock'")
        milk = tx.one('SELECT * FROM products WHERE id = ?', (MILK_PRODUCT_ID,))
        reason = '별도 우유 재고를 일반 품목 재고로 통합'
        inventory_log(tx, milk, 'milk', -count, reason, '시스템')
        inventory_log(tx, milk, 'stock', count, reason, '시스템')


def inventory_log(tx, product, bucket, delta, reason, actor):
    tx.insert("INSERT INTO inventory_logs (product_id, product_name, bucket, delta, reason, actor, created_at) VALUES (?,?,?,?,?,?,?)",
              (product["id"] if product else None, product["name"] if product else "우유", bucket, delta, reason, actor, now()))


def merge_legacy_reward_stock(tx):
    """Close the old event bucket once per remaining unit, preserving totals."""
    for product in tx.all("SELECT * FROM products WHERE reward_stock > 0 ORDER BY id"):
        quantity = product["reward_stock"]
        tx.execute("UPDATE products SET stock = stock + ?, reward_stock = 0 WHERE id = ?",
                   (quantity, product["id"]))
        reason = "별도 이벤트 재고를 현판 재고에 통합"
        inventory_log(tx, product, "reward_stock", -quantity, reason, "시스템")
        inventory_log(tx, product, "stock", quantity, reason, "시스템")


def change_inventory(tx, product_id, bucket, delta, reason, actor):
    if bucket == "milk":
        # Compatibility for old clients; all milk now uses the product stock.
        product_id, bucket = MILK_PRODUCT_ID, 'stock'
    check(bucket in ("stock", "preorder_stock"), "잘못된 재고 구분입니다.")
    product = tx.one("SELECT * FROM products WHERE id = ?", (product_id,))
    check(product is not None, "빵을 찾을 수 없습니다.", 404)
    check(product[bucket] + delta >= 0, f"{product['name']} 재고가 부족합니다.", 409)
    # Column name is selected from the fixed allowlist above.
    tx.execute(f"UPDATE products SET {bucket} = {bucket} + ? WHERE id = ?", (delta, product_id))
    inventory_log(tx, product, bucket, delta, reason, actor)


def normalize_items(tx, raw):
    check(isinstance(raw, list) and 1 <= len(raw) <= 30, "구매할 품목을 1종 이상 선택해 주세요.")
    quantities = {}
    for item in raw:
        check(isinstance(item, dict), "품목 선택 정보가 올바르지 않습니다.")
        product_id = integer(item.get("product_id"), "빵 번호", maximum=1_000_000)
        count = integer(item.get("quantity"), "빵 수량", maximum=100)
        quantities[product_id] = quantities.get(product_id, 0) + count
    check(sum(quantities.values()) <= 100, "한 번에 최대 100개까지 구매할 수 있습니다.")
    result = []
    for product_id, count in sorted(quantities.items()):
        product = tx.one("SELECT * FROM products WHERE id = ?", (product_id,))
        check(product is not None and product_id in PRODUCT_IDS, "판매 중인 품목을 찾을 수 없습니다.", 404)
        result.append({"product_id": product_id, "name": product["name"], "quantity": count, "price": product["price"]})
    return result


def order_data(tx, order_id):
    order = tx.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    check(order is not None, "주문을 찾을 수 없습니다.", 404)
    order["items"] = tx.all("SELECT product_id, name, quantity, price FROM order_items WHERE order_id = ? ORDER BY id", (order_id,))
    kind, order['dice_quantity'] = order_dice(order)
    order['dice'] = public_dice(kind)
    return order


def all_orders(tx, user_id=None, *, include_inventory=False):
    rows = tx.all("SELECT id FROM orders" + (" WHERE user_id = ?" if user_id else "") + " ORDER BY id DESC LIMIT 500", (user_id,) if user_id else ())
    orders = [order_data(tx, row["id"]) for row in rows]
    if include_inventory:
        inventory = {row["id"]: row for row in tx.all("SELECT id,stock,preorder_stock FROM products")}
        for order in orders:
            bucket = "preorder_stock" if order["type"] == "preorder" else "stock"
            for item in order["items"]:
                item["remaining_stock"] = inventory[item["product_id"]][bucket]
                item["unit"] = PRODUCT_UNITS.get(item["product_id"], "개")
    return orders


def manual_buyer(tx, body, reservation_name=None):
    if body.get('user_id') is not None:
        buyer = user_by_id(tx, integer(body.get('user_id'), '구매자 번호', maximum=1_000_000), buyer=True)
    else:
        name = reservation_name if reservation_name is not None else person_name(body.get('name'))
        phone = phone_number(body.get('phone'))
        pin = pin_value(body.get('pin'))
        buyer = tx.one("SELECT * FROM users WHERE phone = ? AND role = 'buyer'", (phone,))
        if buyer is None:
            buyer_id = tx.insert("INSERT INTO users (name,phone,role,password_hash,created_at) VALUES (?,?,'buyer',?,?)", (name, phone, hash_pin(pin), now()))
            buyer = user_by_id(tx, buyer_id)
        else:
            check(verify_pin(pin, buyer['password_hash']), '이미 등록된 전화번호입니다. 기존 비밀번호를 입력하거나 구매자를 선택해 주세요.', 409)
    return buyer


def manual_event_grant(tx, body, staff):
    kind = body.get('kind')
    check(kind in ('bread','gift','score'), '지급할 항목을 선택해 주세요.')
    if body.get('guest') is True:
        check(not any(body.get(key) is not None for key in ('user_id','phone','pin')), '비회원 지급에는 이름만 입력해 주세요.')
        check(kind != 'score', '점수는 등록된 계정에만 지급할 수 있습니다.')
        buyer = {'id':None,'name':person_name(body.get('name'))}
    else:
        buyer = user_by_id(tx,integer(body.get('user_id'),'구매자 번호',maximum=1_000_000),buyer=True)
    reason = string(body.get('reason'), '지급 사유', maximum=200)
    quantity = 1 if kind == 'score' else integer(body.get('quantity'), '지급 수량', maximum=100)
    points = integer(body.get('points'),'지급 점수',maximum=10000) if kind == 'score' else 0
    product_id, supply_key, gift_key, item_name = None, None, None, '점수'
    if kind == 'bread':
        product_id = integer(body.get('product_id'),'빵 번호',maximum=1_000_000)
        check(product_id in REWARD_PRODUCT_IDS, '지급할 빵을 선택해 주세요.')
    elif kind == 'gift':
        gift_key = body.get('gift')
        check(gift_key in ('oatmeal','milk','soymilk','sunglasses','custom'), '지급할 상품을 선택해 주세요.')
        if gift_key in ('milk','soymilk'):
            product_id = MILK_PRODUCT_ID if gift_key == 'milk' else SOYMILK_PRODUCT_ID
        elif gift_key == 'oatmeal':
            supply_key = 'oatmeal'
            item_name = '오트밀 미니바이트'
        elif gift_key == 'sunglasses':
            check(buyer['id'] is not None, '프로필 선글라스는 등록된 계정에만 지급할 수 있습니다.')
            check(quantity == 1, '프로필 선글라스는 한 번에 1개만 지급할 수 있습니다.')
            check(not has_sunglasses(buyer), '이미 멋진 선글라스를 보유한 계정입니다.',409)
            item_name = '멋진 선글라스'
        else:
            item_name = string(body.get('gift_name'),'상품 이름',maximum=80)
    if product_id is not None:
        product = tx.one('SELECT name FROM products WHERE id=?',(product_id,))
        check(product is not None, '지급할 품목을 찾을 수 없습니다.',404)
        item_name = product['name']
    grant_id = tx.insert('INSERT INTO manual_event_grants(user_id,customer_name,kind,product_id,supply_key,gift_key,item_name,quantity,points,reason,staff_id,staff_name,created_at) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (buyer['id'],buyer['name'],kind,product_id,supply_key,gift_key,item_name,quantity,points,reason,staff['id'],staff['name'],now()))
    log_reason = f"임의 지급 #{grant_id} · {buyer['name']} · {reason}"
    if product_id is not None:
        change_inventory(tx,product_id,'stock',-quantity,log_reason,staff['name'])
    elif supply_key:
        change_supply(tx,supply_key,-quantity,log_reason,staff['name'])
    elif kind == 'score':
        tx.execute('UPDATE users SET score=score+? WHERE id=?',(points,buyer['id']))
    return {'grant':tx.one('SELECT * FROM manual_event_grants WHERE id=?',(grant_id,)),
            'user':public_user(user_by_id(tx,buyer['id'])) if buyer['id'] is not None else None}


def approve_order(tx, order):
    if order['status'] == 'approved':
        return order
    check(order['status'] == 'pending', '이미 처리된 주문입니다. 현재 상태를 확인해 주세요.', 409)
    tx.execute("UPDATE orders SET status = 'approved', approved_at = ? WHERE id = ?", (now(),order['id']))
    if order['user_id'] is not None:
        grant_dice(tx, order['user_id'], *order_dice(order))
    if order['reservation_id']:
        tx.execute("UPDATE reservations SET status = 'approved' WHERE id = ?", (order['reservation_id'],))
    return order_data(tx, order['id'])


def insert_order(tx, buyer, items, order_type, actor, approved=False, reservation_id=None):
    bucket = "preorder_stock" if order_type == "preorder" else "stock"
    stamp = now()
    for item in items:
        reason = ('예약 수기 수령' if approved else '예판 수령 요청') if order_type == 'preorder' else '현판 주문 접수'
        change_inventory(tx, item["product_id"], bucket, -item["quantity"], reason, actor)
    order_id = tx.insert("INSERT INTO orders (user_id,customer_name,type,status,reservation_id,total,quantity,created_at,approved_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (buyer["id"], buyer["name"], order_type, "approved" if approved else "pending", reservation_id,
                          sum(i["price"] * i["quantity"] for i in items), sum(i["quantity"] for i in items), stamp, stamp if approved else None))
    for item in items:
        tx.insert("INSERT INTO order_items (order_id,product_id,name,quantity,price) VALUES (?,?,?,?,?)",
                  (order_id, item["product_id"], item["name"], item["quantity"], item["price"]))
    if approved and buyer['id'] is not None:
        grant_dice(tx, buyer['id'], *order_dice({'items': items, 'type': order_type,
                   'total': sum(i['price'] * i['quantity'] for i in items)}))
    return order_data(tx, order_id)


def reservation_data(tx, reservation):
    result = {key: reservation[key] for key in ("id", "name", "phone", "status")}
    result["items"] = tx.all("SELECT ri.product_id,p.name,ri.quantity,ri.price FROM reservation_items ri JOIN products p ON p.id = ri.product_id WHERE reservation_id = ? ORDER BY ri.id", (reservation["id"],))
    result["total"] = sum(item["price"] * item["quantity"] for item in result["items"])
    return result


def staff_reservation_data(tx, reservation):
    result = reservation_data(tx, reservation)
    kind, result['dice_quantity'] = order_dice({**result, 'type': 'preorder'})
    result['dice'] = public_dice(kind)
    result['order'] = order_data(tx,reservation['order_id']) if reservation['order_id'] else None
    return result


def all_reservations(tx):
    reservations = tx.all('SELECT id,name,phone,status FROM reservations ORDER BY id DESC')
    by_id = {row['id']: row for row in reservations}
    for row in reservations:
        row['items'] = []
        row['total'] = 0
    items = tx.all('SELECT ri.reservation_id,ri.product_id,p.name,ri.quantity,ri.price FROM reservation_items ri JOIN products p ON p.id=ri.product_id ORDER BY ri.id')
    for item in items:
        reservation = by_id[item.pop('reservation_id')]
        reservation['items'].append(item)
        reservation['total'] += item['quantity'] * item['price']
    return reservations


def idempotent(tx, user, scope, body, operation):
    request_id = string(body.get("request_id"), "요청 번호", maximum=120)
    fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    cached = tx.one("SELECT fingerprint,response FROM idempotency WHERE user_id = ? AND scope = ? AND request_id = ?", (user["id"], scope, request_id))
    if cached:
        check(hmac.compare_digest(cached["fingerprint"], fingerprint), "같은 요청 번호가 다른 내용에 사용되었습니다. 다시 시도해 주세요.", 409)
        return json.loads(cached["response"])
    result = operation()
    tx.execute("INSERT INTO idempotency (user_id,scope,request_id,fingerprint,response,created_at) VALUES (?,?,?,?,?,?)",
               (user["id"], scope, request_id, fingerprint, json.dumps(result, ensure_ascii=False), now()))
    return result


class Application:
    def __init__(self):
        release_file = ROOT / 'release.json'
        self.release = {'commit': json.loads(release_file.read_text())['commit']} if release_file.exists() else {}
        self.production = os.environ.get("APP_ENV", "local").lower() == "production"
        self.staff_password = os.environ.get("STAFF_PASSWORD", "butter2026")
        if self.production and (self.staff_password == "butter2026" or len(self.staff_password) < 12):
            raise RuntimeError("Production requires a non-default STAFF_PASSWORD of at least 12 characters.")
        self.demo = not self.production and os.environ.get("DEMO_SEED", "0") == "1"
        self.allowed_origins = {value.strip().rstrip("/") for value in os.environ.get("ALLOWED_ORIGINS", "").split(",") if value.strip()}
        check("*" not in self.allowed_origins, "ALLOWED_ORIGINS must contain exact origins, not *.")
        self.db = Database(ROOT)
        self.db.initialize()
        self.seed()
        with self.db.transaction(write=True) as tx:
            if not tx.one("SELECT key FROM settings WHERE key='typed_dice_v1'"):
                # Preserve existing unspent dice exactly once; historical rolls stay untouched.
                for row in tx.all('SELECT id,dice_balance FROM users WHERE dice_balance>0'):
                    tx.execute("INSERT INTO dice_wallet(user_id,kind,quantity) VALUES(?,'walkin',?)", (row['id'], row['dice_balance']))
                tx.execute("INSERT INTO settings(key,value) VALUES('typed_dice_v1','1')")
            tx.execute("INSERT INTO event_supplies(key,name,stock) VALUES('oatmeal','오트밀 미니바이트',?) ON CONFLICT(key) DO NOTHING",
                       (40 if self.demo else 0,))

    def seed(self):
        with self.db.transaction(write=True) as tx:
            sync_catalog(tx, demo=self.demo)
            merge_legacy_reward_stock(tx)
            if not tx.one("SELECT key FROM settings WHERE key = 'milk_stock'"):
                tx.execute("INSERT INTO settings (key,value) VALUES ('milk_stock',?)", ("40" if self.demo else "0",))
            merge_legacy_milk_stock(tx)
            if self.demo and not tx.one("SELECT id FROM schedule LIMIT 1"):
                for name, time, role in [("오픈팀", "11:00–13:00", "판매 · 포장"), ("오후팀", "13:00–15:00", "판매 · 이벤트"), ("마감팀", "15:00–17:00", "판매 · 재고 마감")]:
                    tx.insert("INSERT INTO schedule (name,time,role) VALUES (?,?,?)", (name, time, role))
            if not self.demo or tx.one("SELECT key FROM settings WHERE key = 'demo_seeded'"):
                return
            stamp = now()
            ids = {}
            pin_hash = hash_pin("1234")
            for index,(name, score, dice) in enumerate([("김소연", 42, 3), ("이서연", 96, 0), ("박지우", 81, 0), ("정다은", 68, 0), ("최민준", 37, 2), ("한유진", 24, 1)],1):
                phone='010-1234-5678' if index==1 else f'010-0000-{index:04d}'
                existing = tx.one("SELECT id FROM users WHERE phone = ? AND role = 'buyer'", (phone,))
                ids[name] = existing["id"] if existing else tx.insert("INSERT INTO users (name,phone,role,password_hash,score,dice_balance,created_at) VALUES (?,?,'buyer',?,?,?,?)", (name, phone, pin_hash, score, dice, stamp))
            if not tx.one("SELECT id FROM reservations WHERE name = ? AND phone = ?", ("김소연", "010-1234-5678")):
                self.import_reservations(tx, [{"name": "김소연", "phone": "01012345678", "items": [{"product_id": 101, "quantity": 2}, {"product_id": 102, "quantity": 1}]}], "데모 준비")
            buyer = user_by_id(tx, ids["최민준"])
            insert_order(tx, buyer, normalize_items(tx, [{"product_id": 105, "quantity": 1}, {"product_id": 106, "quantity": 2}]), "walkin", "데모 준비")
            tx.insert("INSERT INTO memos (content,author,created_at) VALUES (?,?,?)", ("오픈 준비 완료! 현판은 입금과 빵 전달을 모두 확인한 뒤 승인해 주세요. 예판은 이름과 예약 빵을 한 번 더 확인해 주세요.", "오픈팀", stamp))
            tx.execute("INSERT INTO settings (key,value) VALUES ('demo_seeded','1')")

    def import_reservations(self, tx, raw, actor):
        check(isinstance(raw, list) and 1 <= len(raw) <= 500, "예약 목록은 1~500건으로 입력해 주세요.")
        prepared = []
        seen = set()
        for item in raw:
            check(isinstance(item, dict), "예약 데이터 형식이 올바르지 않습니다.")
            name = person_name(item.get("name"))
            phone = phone_number(item.get("phone"))
            key = (name, phone)
            check(key not in seen and not tx.one("SELECT id FROM reservations WHERE name = ? AND phone = ?", key), f"{name}님의 같은 전화번호 예약이 이미 있습니다.", 409)
            seen.add(key)
            prepared.append((name, phone, normalize_items(tx, item.get("items"))))
        for name, phone, items in prepared:
            reservation_id = tx.insert("INSERT INTO reservations (name,phone,created_at) VALUES (?,?,?)", (name, phone, now()))
            for item in items:
                change_inventory(tx, item["product_id"], "stock", -item["quantity"], f"{name} 예판 배정", actor)
                change_inventory(tx, item["product_id"], "preorder_stock", item["quantity"], f"{name} 예판 배정", actor)
                tx.insert("INSERT INTO reservation_items (reservation_id,product_id,quantity,price) VALUES (?,?,?,?)", (reservation_id, item["product_id"], item["quantity"], item["price"]))
        return {"imported": len(prepared)}

    def authenticate(self, authorization):
        check(isinstance(authorization, str) and authorization.startswith("Bearer "), "먼저 로그인해 주세요.", 401)
        token = authorization[7:].strip()
        check(len(token) >= 32, "로그인이 만료되었습니다. 다시 로그인해 주세요.", 401)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.db.transaction() as tx:
            row = tx.one("SELECT u.*,p.appearance FROM sessions s JOIN users u ON u.id = s.user_id LEFT JOIN user_profiles p ON p.user_id=u.id WHERE s.token_hash = ? AND s.expires_at > ?", (token_hash, now()))
            if row is not None:
                row = profile_rows(tx, [row], row["id"])[0]
        check(row is not None, "로그인이 만료되었습니다. 다시 로그인해 주세요.", 401)
        return row

    def session(self, tx, user):
        token = secrets.token_urlsafe(36)
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="milliseconds")
        tx.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))
        tx.execute("INSERT INTO sessions (token_hash,user_id,expires_at) VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], expires))
        return {"token": token, "user": public_user(user_by_id(tx, user["id"]))}

    def handle(self, method, path, query, body, authorization):
        if method == "GET" and path == "/api/health":
            return {"ok": True, **self.release}
        if method == "GET" and path == "/api/config":
            result = {"demo": self.demo, "milestones": MILESTONES,
                      "dice_types": [public_dice(kind) for kind in DICE]}
            if self.demo:
                result["staff_password_hint"] = self.staff_password
            return result
        if method == "GET" and path == "/api/products":
            with self.db.transaction() as tx:
                return {"products": products(tx)}
        if method == 'POST' and path == '/api/guest/orders':
            name = person_name(body.get('name'))
            receipt = body.get('request_id')
            check(isinstance(receipt,str) and re.fullmatch(r'(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})',receipt),
                  '주문 요청 번호가 올바르지 않습니다. 다시 시도해 주세요.')
            digest = hashlib.sha256(receipt.encode()).hexdigest()
            fingerprint = hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            with self.db.transaction(write=True) as tx:
                cached = tx.one('SELECT * FROM guest_order_access WHERE token_hash=?', (digest,))
                if cached:
                    check(hmac.compare_digest(cached['fingerprint'],fingerprint), '같은 요청 번호가 다른 내용에 사용되었습니다. 다시 시도해 주세요.',409)
                    return {'order':order_data(tx,cached['order_id'])}
                order = insert_order(tx,{'id':None,'name':name},normalize_items(tx,body.get('items')),'walkin',name)
                tx.execute('INSERT INTO guest_order_access(token_hash,order_id,fingerprint,created_at) VALUES(?,?,?,?)',
                           (digest,order['id'],fingerprint,now()))
                return {'order':order}
        guest_match = re.fullmatch(r'/api/guest/orders/([0-9]+)',path)
        if method == 'GET' and guest_match:
            receipt = authorization[7:].strip() if authorization and authorization.startswith('Bearer ') else ''
            with self.db.transaction() as tx:
                access = tx.one('SELECT order_id FROM guest_order_access WHERE order_id=? AND token_hash=?',
                                (int(guest_match.group(1)),hashlib.sha256(receipt.encode()).hexdigest()))
                check(access is not None, '이 기기의 비회원 주문을 찾을 수 없습니다.',404)
                return {'order':order_data(tx,access['order_id'])}
        if method == "POST" and path in ("/api/auth/register", "/api/auth/login"):
            phone, pin = phone_number(body.get('phone')), pin_value(body.get('pin'))
            with self.db.transaction(write=True) as tx:
                user = tx.one("SELECT * FROM users WHERE phone = ? AND role = 'buyer'", (phone,))
                if path.endswith("register"):
                    name=person_name(body.get('name'))
                    check(user is None, "이미 있는 번호입니다", 409)
                    user_id = tx.insert("INSERT INTO users (name,phone,role,password_hash,created_at) VALUES (?,?,'buyer',?,?)", (name, phone, hash_pin(pin), now()))
                    user = user_by_id(tx, user_id)
                else:
                    check(user is not None and verify_pin(pin, user["password_hash"]), "전화번호 또는 비밀번호가 맞지 않습니다.", 401)
                return self.session(tx, user)
        if method == "POST" and path == "/api/staff/login":
            name = person_name(body.get("name"))
            password = body.get("password")
            check(isinstance(password, str) and hmac.compare_digest(password.encode(), self.staff_password.encode()), "담당자 비밀번호가 맞지 않습니다.", 401)
            with self.db.transaction(write=True) as tx:
                user = tx.one("SELECT * FROM users WHERE name = ? AND role = 'staff'", (name,))
                if user is None:
                    user_id = tx.insert("INSERT INTO users (name,role,password_hash,created_at) VALUES (?,'staff','',?)", (name, now()))
                    user = user_by_id(tx, user_id)
                return self.session(tx, user)

        user = self.authenticate(authorization)
        if method == "GET" and path == "/api/auth/me":
            result = {"user": public_user(user)}
            if user['role'] == 'buyer':
                result['pickup_defaults'] = {'name':user['name'],'phone':user['phone']}
            return result
        if method == "POST" and path == "/api/profile":
            check(set(body) == {"avatar"}, "저장할 캐릭터 꾸미기 정보만 보내 주세요.")
            avatar = validate_avatar(body["avatar"])
            with self.db.transaction(write=True) as tx:
                current = user_by_id(tx, user["id"])
                check(avatar["hairpin"] in current["unlocked_hairpins"], "이 빵의 구매가 승인되면 머리핀을 고를 수 있어요.", 403)
                check(avatar['glasses'] != 'sunglasses' or has_sunglasses(current),
                      '15점 선글라스 보상을 받은 뒤 착용할 수 있어요.', 403)
                appearance = json.dumps(avatar, separators=(",", ":"))
                tx.execute("INSERT INTO user_profiles(user_id,appearance,updated_at) VALUES(?,?,?) "
                           "ON CONFLICT(user_id) DO UPDATE SET appearance=excluded.appearance,updated_at=excluded.updated_at",
                           (user["id"], appearance, now()))
                current["appearance"] = appearance
                return {"user": public_user(current)}
        if method == "POST" and path == "/api/auth/logout":
            with self.db.transaction(write=True) as tx:
                tx.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(authorization[7:].strip().encode()).hexdigest(),))
            return {"ok": True}
        if path.startswith("/api/staff/"):
            check(user["role"] == "staff", "담당자만 이용할 수 있습니다.", 403)
            return self.handle_staff(method, path, body, user)
        check(user["role"] == "buyer", "구매자 계정으로 로그인해 주세요.", 403)
        if method == "GET" and path == "/api/orders":
            with self.db.transaction() as tx:
                return {"orders": all_orders(tx, user["id"])}
        if method == "POST" and path == "/api/orders":
            with self.db.transaction(write=True) as tx:
                return idempotent(tx, user, "order", body, lambda: {"order": insert_order(tx, user, normalize_items(tx, body.get("items")), "walkin", user["name"])})
        if method == "GET" and path == "/api/preorders/lookup":
            name = person_name(query.get('name', [user['name']])[0])
            phone = phone_number(query.get('phone', [user['phone']])[0])
            with self.db.transaction(write=True) as tx:
                reservation = tx.one("SELECT * FROM reservations WHERE name = ? AND phone = ?", (name, phone))
                check(reservation is not None, "해당 이름과 전화번호의 예약이 없습니다. 담당자에게 문의해 주세요.", 404)
                expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="milliseconds")
                tx.execute("INSERT INTO preorder_verifications (user_id,reservation_id,expires_at) VALUES (?,?,?) ON CONFLICT (user_id,reservation_id) DO UPDATE SET expires_at = excluded.expires_at", (user["id"], reservation["id"], expires))
                result=reservation_data(tx,reservation)
                result.pop('phone')
                return {"reservation": result}
        match = re.fullmatch(r"/api/preorders/([0-9]+)/claim", path)
        if method == "POST" and match:
            with self.db.transaction(write=True) as tx:
                def claim_preorder():
                    reservation = tx.one("SELECT * FROM reservations WHERE id = ?", (int(match.group(1)),))
                    check(reservation is not None, "예약을 찾을 수 없습니다.", 404)
                    verification = tx.one("SELECT expires_at FROM preorder_verifications WHERE user_id = ? AND reservation_id = ? AND expires_at > ?", (user["id"], reservation["id"], now()))
                    check(verification is not None, "이름과 전화번호로 예약을 먼저 조회해 주세요.", 403)
                    check(reservation["user_id"] in (None, user["id"]), "이미 다른 계정으로 접수된 예약입니다.", 409)
                    if reservation["order_id"]:
                        return {"order": order_data(tx, reservation["order_id"])}
                    items = reservation_data(tx, reservation)["items"]
                    order = insert_order(tx, user, items, "preorder", user["name"], reservation_id=reservation["id"])
                    tx.execute("UPDATE reservations SET status = 'pending', user_id = ?, order_id = ? WHERE id = ?", (user["id"], order["id"], reservation["id"]))
                    return {"order": order}
                return idempotent(tx, user, f"preorder:{match.group(1)}", body, claim_preorder)
        if method == "POST" and path == "/api/dice/roll":
            with self.db.transaction(write=True) as tx:
                def roll():
                    current = user_by_id(tx, user["id"])
                    check(current["dice_balance"] > 0, "사용할 수 있는 주사위가 없습니다. 빵 구매 승인 후 다시 확인해 주세요.", 409)
                    check(set(body) <= {'request_id', 'kind'}, '주사위 종류와 요청 번호만 보내 주세요.')
                    kind = body.get('kind', current['dice'][0]['kind'] if current['dice'] else None)
                    check(isinstance(kind, str) and kind in DICE, '사용할 주사위를 선택해 주세요.')
                    held = tx.one('SELECT quantity FROM dice_wallet WHERE user_id=? AND kind=?', (user['id'], kind))
                    check(held is not None and held['quantity'] > 0, '선택한 주사위가 없습니다. 보유 주사위를 다시 확인해 주세요.', 409)
                    face = DICE[kind]['faces'][secrets.randbelow(6)]
                    value = 0 if face == 'milk' else face
                    tx.execute('UPDATE dice_wallet SET quantity=quantity-1 WHERE user_id=? AND kind=?', (user['id'], kind))
                    tx.execute("UPDATE users SET dice_balance = dice_balance - 1, score = score + ? WHERE id = ?", (value, user["id"]))
                    roll_id = tx.insert('INSERT INTO typed_dice_rolls(user_id,kind,result,value,created_at) VALUES(?,?,?,?,?)',
                                        (user['id'], kind, 'milk' if face == 'milk' else 'score', value, now()))
                    fulfillment = create_reward_request(tx, current, 'milk', roll_id=roll_id) if face=='milk' else None
                    return {'id': roll_id, 'dice': public_dice(kind), 'result': 'milk' if face == 'milk' else 'score',
                            "value": value, "score": current["score"] + value, "dice_balance": current["dice_balance"] - 1,
                            'user': public_user(user_by_id(tx, user['id'])), 'fulfillment': fulfillment}
                return idempotent(tx, user, "roll", body, roll)
        if method == "GET" and path == "/api/leaderboard":
            with self.db.transaction() as tx:
                rows = profile_rows(tx, tx.all("SELECT u.id,u.name,u.score,p.appearance FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id WHERE u.role = 'buyer' ORDER BY u.score DESC,u.id ASC"))
                entries = [{"rank": index + 1, "id": row["id"], "name": row["name"], "score": row["score"],
                            **profile_info(row), "is_me": row["id"] == user["id"]} for index, row in enumerate(rows)]
                position = next(index for index, row in enumerate(entries) if row["is_me"])
                return {"leaders": entries[:3], "neighbors": entries[max(0, position - 2):position + 3], "me": entries[position], "total_participants": len(entries)}
        if method == "GET" and path == "/api/rewards":
            with self.db.transaction() as tx:
                return {"rewards": reward_history(tx, user['id']), 'requests': reward_requests(tx, user['id'])}
        match = re.fullmatch(r'/api/reward-requests/([0-9]+)/(choose|decline)', path)
        if method == 'POST' and match:
            with self.db.transaction(write=True) as tx:
                def choose_reward():
                    row = reward_request(tx, int(match.group(1)))
                    check(row['user_id'] == user['id'], '본인의 이벤트 지급 요청만 처리할 수 있습니다.', 403)
                    if match.group(2) == 'decline':
                        if row['status']=='cancelled':
                            return {'request':row}
                        check(row['status']=='awaiting_choice', '이미 선택한 물품은 담당자에게 취소를 요청해 주세요.', 409)
                        return {'request':process_reward_request(tx,row,'cancel',user['name'])}
                    product_id = integer(body.get('product_id'), '음료 번호', maximum=1_000_000)
                    check(product_id in DRINK_PRODUCT_IDS and row['kind']=='milk', '우유 또는 두유를 선택해 주세요.')
                    if row['status'] in ('pending','approved') and row['product_id']==product_id:
                        return {'request':row}
                    check(row['status']=='awaiting_choice', '이미 처리된 요청입니다. 현재 상태를 확인해 주세요.', 409)
                    product = tx.one('SELECT * FROM products WHERE id=?', (product_id,))
                    change_inventory(tx,product_id,'stock',-1,f"이벤트 요청 #{row['id']} 음료 선택 · 재고 확보",user['name'])
                    tx.execute("UPDATE reward_requests SET product_id=?,product_name=?,status='pending',requested_at=? WHERE id=?",
                               (product_id,product['name'],now(),row['id']))
                    if row['milestone_id'] is not None:
                        tx.execute('UPDATE milestone_claims SET product_id=?,product_name=? WHERE id=?', (product_id,product['name'],row['milestone_id']))
                    return {'request':reward_request(tx,row['id'])}
                return idempotent(tx,user,f'reward-choice:{match.group(1)}',body,choose_reward)
        if method == "POST" and path == "/api/rewards/claim":
            with self.db.transaction(write=True) as tx:
                def reward():
                    current = user_by_id(tx, user["id"])
                    if 'threshold' in body:
                        requested = integer(body['threshold'], '보상 점수', maximum=30)
                        milestone = next((m for m in MILESTONES if m['threshold']==requested), None)
                        check(milestone is not None, '해당 점수의 보상이 없습니다.')
                        check(requested not in current['claimed_milestones'], '이미 받은 점수 보상입니다.', 409)
                    else:
                        milestone = next((m for m in MILESTONES if m['threshold'] not in current['claimed_milestones']), None)
                    check(milestone is not None, '모든 점수 보상을 받았어요.', 409)
                    threshold, kind = milestone['threshold'], milestone['kind']
                    check(current["score"] >= threshold, f"다음 보상은 {threshold}점부터 가능해요.", 409)
                    selected = {'id': None, 'name': milestone['name']}
                    if kind == 'bread':
                        available = [p for p in products(tx) if p['stock'] > 0 and p['reward_eligible']]
                        total = sum(p['stock'] ** 2 for p in available)
                        check(total > 0, "현판 빵 재고가 모두 소진되었습니다. 담당자에게 문의해 주세요.", 409)
                        ticket = secrets.randbelow(total)
                        for product in available:
                            ticket -= product['stock'] ** 2
                            if ticket < 0:
                                selected = product
                                break
                    elif kind == 'milk':
                        selected = {'id':None, 'name':'우유·두유 선택'}
                    reward_id = tx.insert('INSERT INTO milestone_claims(user_id,product_id,product_name,threshold,kind,created_at) VALUES(?,?,?,?,?,?)',
                                          (user['id'], selected['id'], selected['name'], threshold, kind, now()))
                    tx.execute("UPDATE users SET rewards_claimed = rewards_claimed + 1 WHERE id = ?", (user["id"],))
                    result = tx.one('SELECT id,product_id,product_name,threshold,kind,created_at FROM milestone_claims WHERE id=?', (reward_id,))
                    result['fulfillment'] = create_reward_request(tx,current,kind,selected,milestone_id=reward_id) if kind!='sunglasses' else None
                    return {"reward": result, "user": public_user(user_by_id(tx, user["id"]))}
                return idempotent(tx, user, "reward", body, reward)
        raise APIError(404, "요청한 API를 찾을 수 없습니다.")

    def handle_staff(self, method, path, body, user):
        if method == "GET" and path == "/api/staff/dashboard":
            with self.db.transaction() as tx:
                stats = tx.one("SELECT COALESCE(SUM(CASE WHEN status = 'approved' THEN total ELSE 0 END),0) AS revenue, COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END),0) AS approved_orders, COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END),0) AS pending_orders FROM orders")
                stats["bread_sold"] = tx.one("SELECT COALESCE(SUM(i.quantity),0) AS count FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.status='approved' AND i.product_id NOT IN (?,?)", DRINK_PRODUCT_IDS)["count"]
                stats["milk_stock"] = milk_stock(tx)
                stats['pending_rewards'] = tx.one("SELECT COUNT(*) AS n FROM reward_requests WHERE status='pending'")['n']
                return {"orders": all_orders(tx, include_inventory=True), "products": products(tx), "stats": stats,
                        "event_supplies": tx.all('SELECT * FROM event_supplies ORDER BY key'),
                        'reward_requests': reward_requests(tx),
                        'manual_grants': tx.all('SELECT * FROM manual_event_grants ORDER BY id DESC LIMIT 300'),
                        "reservations": all_reservations(tx),
                        "users": [{**public_user(row),'phone':row['phone']} for row in profile_rows(tx, tx.all("SELECT u.*,p.appearance FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id WHERE u.role = 'buyer' ORDER BY u.name,u.id"))],
                        "inventory_logs": tx.all("SELECT * FROM inventory_logs ORDER BY id DESC LIMIT 300"),
                        "events": tx.all("SELECT * FROM events ORDER BY id DESC LIMIT 300"),
                        "memos": tx.all("SELECT * FROM memos ORDER BY id DESC LIMIT 100"),
                        "schedule": tx.all("SELECT * FROM schedule ORDER BY id"),
                        "rewards": reward_history(tx)}
        if method == 'POST' and path == '/api/staff/event-supplies':
            with self.db.transaction(write=True) as tx:
                def adjust_supply():
                    check(body.get('key') == 'oatmeal', '이벤트 품목을 확인해 주세요.')
                    delta = integer(body.get('delta'), '수정 수량', minimum=-10000, maximum=10000)
                    check(delta != 0, '수정 수량을 입력해 주세요.')
                    reason = string(body.get('reason'), '수정 사유', maximum=200)
                    change_supply(tx,'oatmeal',delta,reason,user['name'])
                    return {'supply': tx.one("SELECT * FROM event_supplies WHERE key='oatmeal'")}
                return idempotent(tx, user, 'event-supply', body, adjust_supply)
        if method == 'POST' and path == '/api/staff/manual-event-grants':
            with self.db.transaction(write=True) as tx:
                return idempotent(tx,user,'manual-event-grant',body,lambda:manual_event_grant(tx,body,user))
        match = re.fullmatch(r'/api/staff/reward-requests/([0-9]+)/(approve|cancel)', path)
        if method == 'POST' and match:
            with self.db.transaction(write=True) as tx:
                return {'request':process_reward_request(tx,reward_request(tx,int(match.group(1))),match.group(2),user['name'])}
        match = re.fullmatch(r"/api/staff/orders/([0-9]+)/(approve|cancel)", path)
        if method == "POST" and match:
            with self.db.transaction(write=True) as tx:
                order = order_data(tx, int(match.group(1)))
                desired = "approved" if match.group(2) == "approve" else "cancelled"
                if order["status"] == desired:
                    return {"order": order}
                check(order["status"] == "pending", "이미 처리된 주문입니다. 현재 상태를 확인해 주세요.", 409)
                if desired == "approved":
                    return {'order': approve_order(tx, order)}
                else:
                    bucket = "preorder_stock" if order["type"] == "preorder" else "stock"
                    for item in order["items"]:
                        change_inventory(tx, item["product_id"], bucket, item["quantity"], f"주문 #{order['id']} 취소", user["name"])
                    tx.execute("UPDATE orders SET status = 'cancelled', cancelled_at = ? WHERE id = ?", (now(), order["id"]))
                    if order["reservation_id"]:
                        tx.execute("UPDATE reservations SET status = 'reserved', user_id = NULL, order_id = NULL WHERE id = ?", (order["reservation_id"],))
                return {"order": order_data(tx, order["id"])}
        if method == "POST" and path == "/api/staff/inventory":
            with self.db.transaction(write=True) as tx:
                def adjust_inventory():
                    bucket = body.get("bucket")
                    check(bucket in ("stock", "preorder_stock", "milk"), "재고 구분이 올바르지 않습니다. 이벤트는 현판 재고를 사용합니다.")
                    delta = integer(body.get("delta"), "재고 수정량", minimum=-10_000, maximum=10_000)
                    check(delta != 0, "재고 수정량은 0이 될 수 없습니다.")
                    reason = string(body.get("reason"), "수정 사유", maximum=200)
                    product_id = None if bucket == "milk" else integer(body.get("product_id"), "빵 번호", maximum=1_000_000)
                    if bucket == "preorder_stock" and delta < 0:
                        required = tx.one("SELECT COALESCE(SUM(ri.quantity),0) AS quantity FROM reservation_items ri JOIN reservations r ON r.id = ri.reservation_id WHERE ri.product_id = ? AND r.status = 'reserved'", (product_id,))["quantity"]
                        product = tx.one("SELECT preorder_stock FROM products WHERE id = ?", (product_id,))
                        check(product is not None, "빵을 찾을 수 없습니다.", 404)
                        check(product["preorder_stock"] + delta >= required, "수령 전 예약에 필요한 예판 재고는 줄일 수 없습니다.", 409)
                    change_inventory(tx, product_id, bucket, delta, reason, user["name"])
                    return {"products": products(tx), "milk_stock": milk_stock(tx)}
                if "request_id" in body:
                    return idempotent(tx, user, "inventory", body, adjust_inventory)
                return adjust_inventory()
        if method == 'POST' and path == '/api/staff/preorders/lookup':
            name, phone = person_name(body.get('name')), phone_number(body.get('phone'))
            with self.db.transaction() as tx:
                reservation = tx.one('SELECT * FROM reservations WHERE name = ? AND phone = ?', (name,phone))
                check(reservation is not None, '해당 이름과 전화번호의 예약이 없습니다.', 404)
                return {'reservation': staff_reservation_data(tx,reservation)}
        pickup_match = re.fullmatch(r'/api/staff/preorders/([0-9]+)/complete',path)
        if method == 'POST' and pickup_match:
            with self.db.transaction(write=True) as tx:
                def complete_preorder():
                    name, phone = person_name(body.get('name')), phone_number(body.get('phone'))
                    reservation = tx.one('SELECT * FROM reservations WHERE id = ? AND name = ? AND phone = ?',
                                         (int(pickup_match.group(1)),name,phone))
                    check(reservation is not None, '예약자 이름과 전화번호를 다시 확인해 주세요.', 404)
                    if reservation['order_id']:
                        order = order_data(tx,reservation['order_id'])
                        check(order['type'] == 'preorder' and order['reservation_id'] == reservation['id'],
                              '예약에 연결된 주문을 확인할 수 없습니다.', 409)
                        buyer = user_by_id(tx,order['user_id'],buyer=True) if order['user_id'] is not None else {'id':None,'name':order['customer_name']}
                        check(body.get('guest') is not True or buyer['id'] is None,
                              '이미 계정에 연결된 수령 요청입니다. 기존 계정으로 처리해 주세요.',409)
                        if body.get('user_id') is not None:
                            check(integer(body.get('user_id'),'구매자 번호',maximum=1_000_000) == buyer['id'],
                                  '이미 접수된 예약의 구매자 계정과 다릅니다.', 409)
                        already_completed = order['status'] == 'approved'
                        order = approve_order(tx,order)
                    else:
                        check(reservation['status'] == 'reserved', '예약 상태를 다시 확인해 주세요.', 409)
                        buyer = {'id':None,'name':reservation['name']} if body.get('guest') is True else manual_buyer(tx,body,reservation_name=reservation['name'])
                        check(body.get('guest') is not True or not any(body.get(key) is not None for key in ('user_id','pin')),
                              '비회원 수령에는 계정을 선택하지 마세요.')
                        items = reservation_data(tx,reservation)['items']
                        check(bool(items), '예약된 품목이 없습니다.', 409)
                        order = insert_order(tx,buyer,items,'preorder',user['name'],approved=True,
                                             reservation_id=reservation['id'])
                        tx.execute("UPDATE reservations SET status = 'approved', user_id = ?, order_id = ? WHERE id = ?",
                                   (buyer['id'],order['id'],reservation['id']))
                        already_completed = False
                    current = tx.one('SELECT * FROM reservations WHERE id = ?', (reservation['id'],))
                    return {'order':order,'user':public_user(user_by_id(tx,buyer['id'])) if buyer['id'] is not None else None,
                            'reservation':staff_reservation_data(tx,current),'already_completed':already_completed}
                return idempotent(tx,user,'manual-preorder',body,complete_preorder)
        if method == "POST" and path == "/api/staff/manual-sale":
            with self.db.transaction(write=True) as tx:
                def manual_sale():
                    guest = body.get('guest') is True
                    check(not guest or not any(body.get(key) is not None for key in ('user_id','phone','pin')), '비회원 판매에는 이름만 입력해 주세요.')
                    buyer = {'id':None,'name':person_name(body.get('name'))} if guest else manual_buyer(tx, body)
                    order = insert_order(tx, buyer, normalize_items(tx, body.get("items")), "manual", user["name"], approved=True)
                    return {"order": order, "user": public_user(user_by_id(tx, buyer["id"])) if buyer['id'] is not None else None}
                return idempotent(tx, user, "manual-sale", body, manual_sale)
        if method == "POST" and path == "/api/staff/instagram":
            with self.db.transaction(write=True) as tx:
                def instagram():
                    buyer = user_by_id(tx, integer(body.get("user_id"), "구매자 번호", maximum=1_000_000), buyer=True)
                    check(body.get('milk_quantity', 0) == 0 and body.get('dice', 1) == 1,
                          '인스타 인증은 전용 주사위 1개만 지급합니다. 페이지를 새로고침해 주세요.')
                    check(not tx.one("SELECT id FROM events WHERE user_id = ? AND type = 'instagram'", (buyer["id"],)), "이미 인스타 이벤트에 참여한 구매자입니다.", 409)
                    grant_dice(tx, buyer['id'], 'instagram', 1)
                    event_id = tx.insert("INSERT INTO events (user_id,customer_name,type,milk_quantity,dice,created_at) VALUES (?,?,'instagram',0,1,?)", (buyer["id"], buyer["name"], now()))
                    return {"event": tx.one("SELECT * FROM events WHERE id = ?", (event_id,)), "user": public_user(user_by_id(tx, buyer["id"])), "milk_stock": milk_stock(tx)}
                return idempotent(tx, user, "instagram", body, instagram)
        if method == "POST" and path == "/api/staff/memos":
            content = string(body.get("content"), "메모", maximum=2000)
            with self.db.transaction(write=True) as tx:
                memo_id = tx.insert("INSERT INTO memos (content,author,created_at) VALUES (?,?,?)", (content, user["name"], now()))
                return {"memo": tx.one("SELECT * FROM memos WHERE id = ?", (memo_id,))}
        if method == "POST" and path == "/api/staff/preorders/import":
            with self.db.transaction(write=True) as tx:
                return self.import_reservations(tx, body.get("reservations"), user["name"])
        raise APIError(404, "요청한 담당자 API를 찾을 수 없습니다.")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)

    def server_bind(self):
        # HTTPServer's default performs reverse DNS during startup. A local
        # event server must also start promptly with no external DNS service.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    server_version = "Kambodelight/1.0"

    def log_message(self, format, *args):
        # Do not log phone numbers in preorder query strings or authentication data.
        print(f"{self.address_string()} {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}", flush=True)

    def origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        same_origin = {"http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")}
        return origin in self.server.app.allowed_origins or origin in same_origin

    def common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin and self.origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def json_response(self, status, value):
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_OPTIONS(self):
        if not self.origin_allowed():
            return self.json_response(403, {"error": "허용되지 않은 웹사이트입니다."})
        self.send_response(204)
        self.common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.dispatch()

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PUT(self):
        self.json_response(405, {"error": "지원하지 않는 요청 방식입니다."})

    do_DELETE = do_PUT
    do_PATCH = do_PUT

    def dispatch(self):
        try:
            check(self.origin_allowed(), "허용되지 않은 웹사이트입니다.", 403)
            parsed = urlsplit(self.path)
            path = unquote(parsed.path).rstrip("/") or "/"
            if path.startswith("/api/") or path == "/api":
                body = {}
                if self.command == "POST":
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise APIError(400, "요청 길이가 올바르지 않습니다.")
                    check(0 <= length <= 1_048_576, "요청 데이터가 너무 큽니다.", 413)
                    if length:
                        check(self.headers.get("Content-Type", "").split(";")[0].strip() == "application/json", "JSON 형식으로 요청해 주세요.", 415)
                        try:
                            body = json.loads(self.rfile.read(length).decode("utf-8"))
                        except (ValueError, UnicodeError):
                            raise APIError(400, "JSON 형식이 올바르지 않습니다.")
                        check(isinstance(body, dict), "JSON 객체 형식으로 요청해 주세요.")
                result = self.server.app.handle("GET" if self.command == "HEAD" else self.command, path, parse_qs(parsed.query), body, self.headers.get("Authorization"))
                self.json_response(200, result)
            else:
                check(self.command in ("GET", "HEAD"), "지원하지 않는 요청 방식입니다.", 405)
                self.serve_static(path)
        except APIError as exc:
            self.json_response(exc.status, {"error": exc.message})
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            traceback.print_exc()
            self.json_response(409 if isinstance(exc, sqlite3.IntegrityError) else 503, {"error": "요청을 처리하지 못했습니다. 잠시 후 현재 상태를 확인하고 다시 시도해 주세요."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            self.json_response(500, {"error": "서버 오류가 발생했습니다. 담당자에게 문의해 주세요."})

    def serve_static(self, path):
        static = ROOT / "frontend"
        if path in ("/", "/admin"):
            target = static / "index.html"
        else:
            target = (static / path.lstrip("/")).resolve()
        check(target.is_relative_to(static.resolve()) and target.is_file(), "페이지를 찾을 수 없습니다.", 404)
        data = target.read_bytes()
        self.send_response(200)
        self.common_headers()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
