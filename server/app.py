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
from .catalog import PRODUCT_IDS, PRODUCT_UNITS, sync_catalog

ROOT = Path(__file__).resolve().parents[1]
REWARD_STEP = 10
MAX_CHARACTER_LEVEL = 5
PUBLIC_USER_FIELDS = ("id", "name", "role", "score", "dice_balance", "rewards_claimed")


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
    check(isinstance(value, str), "전화번호를 입력해 주세요.")
    result = re.sub(r"[\s()-]", "", value)
    check(re.fullmatch(r"[0-9]{10,11}", result) is not None, "전화번호는 숫자 10~11자리로 입력해 주세요.")
    return result


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
    # A level is earned together with a bread reward, never by score alone.
    user["level"] = min(MAX_CHARACTER_LEVEL, row["rewards_claimed"])
    return user


def user_by_id(tx, user_id, buyer=False):
    user = tx.one("SELECT * FROM users WHERE id = ?", (user_id,))
    check(user is not None and (not buyer or user["role"] == "buyer"), "구매자 계정을 찾을 수 없습니다.", 404)
    return user


def products(tx):
    placeholders = ','.join('?' for _ in PRODUCT_IDS)
    rows = tx.all(f"SELECT * FROM products WHERE id IN ({placeholders}) ORDER BY id", PRODUCT_IDS)
    return [{**row, "unit": PRODUCT_UNITS.get(row["id"], "개")} for row in rows]


def milk_stock(tx):
    return int(tx.one("SELECT value FROM settings WHERE key = 'milk_stock'")["value"])


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
        count = milk_stock(tx)
        check(count + delta >= 0, "우유 재고가 부족합니다.", 409)
        tx.execute("UPDATE settings SET value = ? WHERE key = 'milk_stock'", (str(count + delta),))
        inventory_log(tx, None, bucket, delta, reason, actor)
        return
    check(bucket in ("stock", "preorder_stock"), "잘못된 재고 구분입니다.")
    product = tx.one("SELECT * FROM products WHERE id = ?", (product_id,))
    check(product is not None, "빵을 찾을 수 없습니다.", 404)
    check(product[bucket] + delta >= 0, f"{product['name']} 재고가 부족합니다.", 409)
    # Column name is selected from the fixed allowlist above.
    tx.execute(f"UPDATE products SET {bucket} = {bucket} + ? WHERE id = ?", (delta, product_id))
    inventory_log(tx, product, bucket, delta, reason, actor)


def normalize_items(tx, raw):
    check(isinstance(raw, list) and 1 <= len(raw) <= 30, "구매할 빵을 1종 이상 선택해 주세요.")
    quantities = {}
    for item in raw:
        check(isinstance(item, dict), "빵 선택 정보가 올바르지 않습니다.")
        product_id = integer(item.get("product_id"), "빵 번호", maximum=1_000_000)
        count = integer(item.get("quantity"), "빵 수량", maximum=100)
        quantities[product_id] = quantities.get(product_id, 0) + count
    check(sum(quantities.values()) <= 100, "한 번에 최대 100개까지 구매할 수 있습니다.")
    result = []
    for product_id, count in sorted(quantities.items()):
        product = tx.one("SELECT * FROM products WHERE id = ?", (product_id,))
        check(product is not None and product_id in PRODUCT_IDS, "판매 중인 빵을 찾을 수 없습니다.", 404)
        result.append({"product_id": product_id, "name": product["name"], "quantity": count, "price": product["price"]})
    return result


def order_data(tx, order_id):
    order = tx.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    check(order is not None, "주문을 찾을 수 없습니다.", 404)
    order["items"] = tx.all("SELECT product_id, name, quantity, price FROM order_items WHERE order_id = ? ORDER BY id", (order_id,))
    return order


def all_orders(tx, user_id=None):
    rows = tx.all("SELECT id FROM orders" + (" WHERE user_id = ?" if user_id else "") + " ORDER BY id DESC LIMIT 500", (user_id,) if user_id else ())
    return [order_data(tx, row["id"]) for row in rows]


def insert_order(tx, buyer, items, order_type, actor, approved=False, reservation_id=None):
    bucket = "preorder_stock" if order_type == "preorder" else "stock"
    stamp = now()
    for item in items:
        change_inventory(tx, item["product_id"], bucket, -item["quantity"], "예판 수령 요청" if order_type == "preorder" else "현판 주문 접수", actor)
    order_id = tx.insert("INSERT INTO orders (user_id,customer_name,type,status,reservation_id,total,quantity,created_at,approved_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (buyer["id"], buyer["name"], order_type, "approved" if approved else "pending", reservation_id,
                          sum(i["price"] * i["quantity"] for i in items), sum(i["quantity"] for i in items), stamp, stamp if approved else None))
    for item in items:
        tx.insert("INSERT INTO order_items (order_id,product_id,name,quantity,price) VALUES (?,?,?,?,?)",
                  (order_id, item["product_id"], item["name"], item["quantity"], item["price"]))
    if approved:
        tx.execute("UPDATE users SET dice_balance = dice_balance + ? WHERE id = ?", (sum(i["quantity"] for i in items), buyer["id"]))
    return order_data(tx, order_id)


def reservation_data(tx, reservation):
    result = {key: reservation[key] for key in ("id", "name", "phone", "status")}
    result["items"] = tx.all("SELECT ri.product_id,p.name,ri.quantity,ri.price FROM reservation_items ri JOIN products p ON p.id = ri.product_id WHERE reservation_id = ? ORDER BY ri.id", (reservation["id"],))
    result["total"] = sum(item["price"] * item["quantity"] for item in result["items"])
    return result


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
        self.demo = not self.production and os.environ.get("DEMO_SEED", "1") == "1"
        self.allowed_origins = {value.strip().rstrip("/") for value in os.environ.get("ALLOWED_ORIGINS", "").split(",") if value.strip()}
        check("*" not in self.allowed_origins, "ALLOWED_ORIGINS must contain exact origins, not *.")
        self.db = Database(ROOT)
        self.db.initialize()
        self.seed()

    def seed(self):
        with self.db.transaction(write=True) as tx:
            sync_catalog(tx, demo=self.demo)
            merge_legacy_reward_stock(tx)
            if not tx.one("SELECT key FROM settings WHERE key = 'milk_stock'"):
                tx.execute("INSERT INTO settings (key,value) VALUES ('milk_stock',?)", ("40" if self.demo else "0",))
            if self.demo and not tx.one("SELECT id FROM schedule LIMIT 1"):
                for name, time, role in [("오픈팀", "11:00–13:00", "판매 · 포장"), ("오후팀", "13:00–15:00", "판매 · 이벤트"), ("마감팀", "15:00–17:00", "판매 · 재고 마감")]:
                    tx.insert("INSERT INTO schedule (name,time,role) VALUES (?,?,?)", (name, time, role))
            if not self.demo or tx.one("SELECT key FROM settings WHERE key = 'demo_seeded'"):
                return
            stamp = now()
            ids = {}
            pin_hash = hash_pin("1234")
            for name, score, dice in [("김소연", 42, 3), ("이서연", 96, 0), ("박지우", 81, 0), ("정다은", 68, 0), ("최민준", 37, 2), ("한유진", 24, 1)]:
                existing = tx.one("SELECT id FROM users WHERE name = ? AND role = 'buyer'", (name,))
                ids[name] = existing["id"] if existing else tx.insert("INSERT INTO users (name,role,password_hash,score,dice_balance,created_at) VALUES (?,'buyer',?,?,?,?)", (name, pin_hash, score, dice, stamp))
            if not tx.one("SELECT id FROM reservations WHERE name = ? AND phone = ?", ("김소연", "01012345678")):
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
            row = tx.one("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?", (token_hash, now()))
        check(row is not None, "로그인이 만료되었습니다. 다시 로그인해 주세요.", 401)
        return row

    def session(self, tx, user):
        token = secrets.token_urlsafe(36)
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="milliseconds")
        tx.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))
        tx.execute("INSERT INTO sessions (token_hash,user_id,expires_at) VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], expires))
        return {"token": token, "user": public_user(user)}

    def handle(self, method, path, query, body, authorization):
        if method == "GET" and path == "/api/health":
            return {"ok": True, **self.release}
        if method == "GET" and path == "/api/config":
            result = {"demo": self.demo, "reward_step": REWARD_STEP}
            if self.demo:
                result["staff_password_hint"] = self.staff_password
            return result
        if method == "GET" and path == "/api/products":
            with self.db.transaction() as tx:
                return {"products": products(tx)}
        if method == "POST" and path in ("/api/auth/register", "/api/auth/login"):
            name, pin = person_name(body.get("name")), pin_value(body.get("pin"))
            with self.db.transaction(write=True) as tx:
                user = tx.one("SELECT * FROM users WHERE name = ? AND role = 'buyer'", (name,))
                if path.endswith("register"):
                    check(user is None, "같은 이름의 계정이 있습니다. 기존 계정으로 로그인해 주세요.", 409)
                    user_id = tx.insert("INSERT INTO users (name,role,password_hash,created_at) VALUES (?,'buyer',?,?)", (name, hash_pin(pin), now()))
                    user = user_by_id(tx, user_id)
                else:
                    check(user is not None and verify_pin(pin, user["password_hash"]), "이름 또는 비밀번호가 맞지 않습니다.", 401)
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
            return {"user": public_user(user)}
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
            name = person_name(query.get("name", [""])[0])
            phone = phone_number(query.get("phone", [""])[0])
            check(name == user["name"], "로그인한 본인의 이름으로 예약을 조회해 주세요.", 403)
            with self.db.transaction(write=True) as tx:
                reservation = tx.one("SELECT * FROM reservations WHERE name = ? AND phone = ?", (name, phone))
                check(reservation is not None, "해당 이름과 전화번호의 예약이 없습니다. 담당자에게 문의해 주세요.", 404)
                expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="milliseconds")
                tx.execute("INSERT INTO preorder_verifications (user_id,reservation_id,expires_at) VALUES (?,?,?) ON CONFLICT (user_id,reservation_id) DO UPDATE SET expires_at = excluded.expires_at", (user["id"], reservation["id"], expires))
                return {"reservation": reservation_data(tx, reservation)}
        match = re.fullmatch(r"/api/preorders/([0-9]+)/claim", path)
        if method == "POST" and match:
            with self.db.transaction(write=True) as tx:
                def claim_preorder():
                    reservation = tx.one("SELECT * FROM reservations WHERE id = ?", (int(match.group(1)),))
                    check(reservation is not None and reservation["name"] == user["name"], "본인의 예약을 찾을 수 없습니다.", 404)
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
                    value = secrets.randbelow(6) + 1
                    tx.execute("UPDATE users SET dice_balance = dice_balance - 1, score = score + ? WHERE id = ?", (value, user["id"]))
                    tx.insert("INSERT INTO dice_rolls (user_id,value,created_at) VALUES (?,?,?)", (user["id"], value, now()))
                    return {"value": value, "score": current["score"] + value, "dice_balance": current["dice_balance"] - 1}
                return idempotent(tx, user, "roll", body, roll)
        if method == "GET" and path == "/api/leaderboard":
            with self.db.transaction() as tx:
                rows = tx.all("SELECT id,name,score FROM users WHERE role = 'buyer' ORDER BY score DESC,id ASC")
                entries = [{"rank": index + 1, **row, "is_me": row["id"] == user["id"]} for index, row in enumerate(rows)]
                position = next(index for index, row in enumerate(entries) if row["is_me"])
                return {"leaders": entries[:3], "neighbors": entries[max(0, position - 2):position + 3], "me": entries[position], "total_participants": len(entries)}
        if method == "GET" and path == "/api/rewards":
            with self.db.transaction() as tx:
                return {"rewards": tx.all("SELECT id,product_id,product_name,threshold,created_at FROM rewards WHERE user_id = ? ORDER BY id DESC", (user["id"],))}
        if method == "POST" and path == "/api/rewards/claim":
            with self.db.transaction(write=True) as tx:
                def reward():
                    current = user_by_id(tx, user["id"])
                    threshold = (current["rewards_claimed"] + 1) * REWARD_STEP
                    check(current["score"] >= threshold, f"다음 빵 뽑기는 {threshold}점부터 가능해요.", 409)
                    available = [product for product in products(tx) if product["stock"] > 0]
                    total = sum(product["stock"] ** 2 for product in available)
                    check(total > 0, "현판 빵 재고가 모두 소진되었습니다. 담당자에게 문의해 주세요.", 409)
                    ticket = secrets.randbelow(total)
                    for product in available:
                        ticket -= product["stock"] ** 2
                        if ticket < 0:
                            selected = product
                            break
                    change_inventory(tx, selected["id"], "stock", -1, f"{current['name']} {threshold}점 이벤트 당첨", current["name"])
                    reward_id = tx.insert("INSERT INTO rewards (user_id,product_id,product_name,threshold,created_at) VALUES (?,?,?,?,?)", (user["id"], selected["id"], selected["name"], threshold, now()))
                    tx.execute("UPDATE users SET rewards_claimed = rewards_claimed + 1 WHERE id = ?", (user["id"],))
                    result = tx.one("SELECT id,product_id,product_name,threshold,created_at FROM rewards WHERE id = ?", (reward_id,))
                    return {"reward": result, "user": public_user(user_by_id(tx, user["id"]))}
                return idempotent(tx, user, "reward", body, reward)
        raise APIError(404, "요청한 API를 찾을 수 없습니다.")

    def handle_staff(self, method, path, body, user):
        if method == "GET" and path == "/api/staff/dashboard":
            with self.db.transaction() as tx:
                stats = tx.one("SELECT COALESCE(SUM(CASE WHEN status = 'approved' THEN total ELSE 0 END),0) AS revenue, COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END),0) AS approved_orders, COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END),0) AS pending_orders, COALESCE(SUM(CASE WHEN status = 'approved' THEN quantity ELSE 0 END),0) AS bread_sold FROM orders")
                stats["milk_stock"] = milk_stock(tx)
                return {"orders": all_orders(tx), "products": products(tx), "stats": stats,
                        "users": [public_user(row) for row in tx.all("SELECT * FROM users WHERE role = 'buyer' ORDER BY name,id")],
                        "inventory_logs": tx.all("SELECT * FROM inventory_logs ORDER BY id DESC LIMIT 300"),
                        "events": tx.all("SELECT * FROM events ORDER BY id DESC LIMIT 300"),
                        "memos": tx.all("SELECT * FROM memos ORDER BY id DESC LIMIT 100"),
                        "schedule": tx.all("SELECT * FROM schedule ORDER BY id"),
                        "rewards": tx.all("SELECT r.id,r.product_id,r.product_name,r.threshold,r.created_at,u.name AS customer_name FROM rewards r JOIN users u ON u.id = r.user_id ORDER BY r.id DESC LIMIT 300")}
        match = re.fullmatch(r"/api/staff/orders/([0-9]+)/(approve|cancel)", path)
        if method == "POST" and match:
            with self.db.transaction(write=True) as tx:
                order = order_data(tx, int(match.group(1)))
                desired = "approved" if match.group(2) == "approve" else "cancelled"
                if order["status"] == desired:
                    return {"order": order}
                check(order["status"] == "pending", "이미 처리된 주문입니다. 현재 상태를 확인해 주세요.", 409)
                if desired == "approved":
                    tx.execute("UPDATE orders SET status = 'approved', approved_at = ? WHERE id = ?", (now(), order["id"]))
                    tx.execute("UPDATE users SET dice_balance = dice_balance + ? WHERE id = ?", (order["quantity"], order["user_id"]))
                    if order["reservation_id"]:
                        tx.execute("UPDATE reservations SET status = 'approved' WHERE id = ?", (order["reservation_id"],))
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
        if method == "POST" and path == "/api/staff/manual-sale":
            with self.db.transaction(write=True) as tx:
                def manual_sale():
                    if body.get("user_id") is not None:
                        buyer = user_by_id(tx, integer(body.get("user_id"), "구매자 번호", maximum=1_000_000), buyer=True)
                    else:
                        name, pin = person_name(body.get("name")), pin_value(body.get("pin"))
                        buyer = tx.one("SELECT * FROM users WHERE name = ? AND role = 'buyer'", (name,))
                        if buyer is None:
                            buyer_id = tx.insert("INSERT INTO users (name,role,password_hash,created_at) VALUES (?,'buyer',?,?)", (name, hash_pin(pin), now()))
                            buyer = user_by_id(tx, buyer_id)
                        else:
                            check(verify_pin(pin, buyer["password_hash"]), "같은 이름의 계정이 있습니다. 기존 비밀번호를 입력하거나 구매자를 선택해 주세요.", 409)
                    order = insert_order(tx, buyer, normalize_items(tx, body.get("items")), "manual", user["name"], approved=True)
                    return {"order": order, "user": public_user(user_by_id(tx, buyer["id"]))}
                return idempotent(tx, user, "manual-sale", body, manual_sale)
        if method == "POST" and path == "/api/staff/instagram":
            with self.db.transaction(write=True) as tx:
                def instagram():
                    buyer = user_by_id(tx, integer(body.get("user_id"), "구매자 번호", maximum=1_000_000), buyer=True)
                    count = integer(body.get("milk_quantity", 1), "우유 수량", maximum=5)
                    dice = integer(body.get("dice", 1), "주사위 수량", maximum=10)
                    check(not tx.one("SELECT id FROM events WHERE user_id = ? AND type = 'instagram'", (buyer["id"],)), "이미 인스타 이벤트에 참여한 구매자입니다.", 409)
                    change_inventory(tx, None, "milk", -count, f"{buyer['name']} 인스타 이벤트", user["name"])
                    tx.execute("UPDATE users SET dice_balance = dice_balance + ? WHERE id = ?", (dice, buyer["id"]))
                    event_id = tx.insert("INSERT INTO events (user_id,customer_name,type,milk_quantity,dice,created_at) VALUES (?,?,'instagram',?,?,?)", (buyer["id"], buyer["name"], count, dice, now()))
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
