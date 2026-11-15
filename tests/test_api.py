"""HTTP integration tests. The application runs against a disposable SQLite DB."""

import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from unittest.mock import patch


from account_support import account_payload, phone_for

ROOT = Path(__file__).resolve().parents[1]


def request_id():
    return uuid.uuid4().hex


class APIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="kambo-api-test-")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.log = open(Path(cls.temporary.name) / "server.log", "w+")
        environment = os.environ.copy()
        environment.update(
            APP_ENV="development",
            HOST="127.0.0.1",
            PORT=str(cls.port),
            STAFF_PASSWORD="test-staff-password",
            DEMO_SEED="1",
            DB_PATH=str(Path(cls.temporary.name) / "test.db"),
            ALLOWED_ORIGINS="http://test.example",
        )
        environment.pop("DATABASE_URL", None)
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "server", "--port", str(cls.port)],
            cwd=ROOT,
            env=environment,
            stdout=cls.log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    break
                try:
                    status, _ = cls.call("GET", "/api/config")
                    if status == 200:
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                cls.log.seek(0)
                raise RuntimeError("Test server did not become ready:\n" + cls.log.read())
            if cls.process.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            status, result = cls.call(
                "POST", "/api/staff/login",
                {"name": "테스트담당자", "password": "test-staff-password"},
            )
            if status != 200:
                raise RuntimeError(f"Staff login failed: {status} {result}")
            cls.staff_token = result["token"]
            status, result = cls.call("GET", "/api/products")
            if status != 200 or not result["products"]:
                raise RuntimeError("Demo products were not seeded")
            cls.product_id = result["products"][0]["id"]
        except Exception:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            cls.log.close()
            cls.temporary.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.log.close()
        cls.temporary.cleanup()

    @classmethod
    def call(cls, method, path, body=None, token=None, headers=None):
        body=account_payload(path,body)
        request_headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            cls.base + path, data=data, headers=request_headers, method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}

    def ok(self, method, path, body=None, token=None):
        status, result = self.call(method, path, body, token)
        self.assertGreaterEqual(status, 200, result)
        self.assertLess(status, 300, result)
        return result

    def buyer(self):
        name = "테스트" + uuid.uuid4().hex[:10]
        result = self.ok("POST", "/api/auth/register", {"name": name, "pin": "1234"})
        return result["token"], result["user"]

    def me(self, token):
        return self.ok("GET", "/api/auth/me", token=token)["user"]

    def product(self):
        products = self.ok("GET", "/api/products")["products"]
        return next(p for p in products if p["id"] == self.product_id)

    def set_stock(self, bucket, count):
        delta = count - self.product()[bucket]
        if delta:
            self.ok(
                "POST", "/api/staff/inventory",
                {"product_id": self.product_id, "bucket": bucket,
                 "delta": delta, "reason": "자동 검증용 재고 설정"},
                self.staff_token,
            )

    def order(self, token, quantity=1, identity=None):
        return self.ok(
            "POST", "/api/orders",
            {"items": [{"product_id": self.product_id, "quantity": quantity}],
             "request_id": identity or request_id()}, token,
        )["order"]

    def transition(self, order_id, action):
        return self.ok(
            "POST", f"/api/staff/orders/{order_id}/{action}", {}, self.staff_token,
        )["order"]

    def test_registration_authentication_and_ownership(self):
        first_token, first = self.buyer()
        second_token, second = self.buyer()
        status, _ = self.call("POST", "/api/auth/register", {"name": first["name"], "pin": "1234"})
        self.assertEqual(status, 409)
        status, _ = self.call("POST", "/api/auth/register", {"name": "잘못된비밀번호", "pin": "123"})
        self.assertEqual(status, 400)
        status, _ = self.call("POST", "/api/auth/login", {"name": first["name"], "pin": "4321"})
        self.assertEqual(status, 401)
        status, _ = self.call("GET", "/api/orders")
        self.assertEqual(status, 401)
        status, _ = self.call("GET", "/api/staff/dashboard", token=first_token)
        self.assertEqual(status, 403)

        self.set_stock("stock", 5)
        order = self.order(first_token)
        orders = self.ok("GET", "/api/orders", token=second_token)["orders"]
        self.assertNotIn(order["id"], [item["id"] for item in orders])
        status, _ = self.call("POST", f"/api/staff/orders/{order['id']}/approve", {}, second_token)
        self.assertEqual(status, 403)
        query = urllib.parse.urlencode({"name": second["name"], "phone": "01012345678"})
        status, _ = self.call("GET", "/api/preorders/lookup?" + query, token=first_token)
        self.assertEqual(status, 404)
        self.transition(order["id"], "cancel")

    def test_last_unit_concurrent_orders_and_cancel_exactly_once(self):
        tokens = [self.buyer()[0], self.buyer()[0]]
        self.set_stock("stock", 1)
        gate = threading.Barrier(2)

        def buy(token):
            gate.wait(timeout=5)
            return self.call(
                "POST", "/api/orders",
                {"items": [{"product_id": self.product_id, "quantity": 1}],
                 "request_id": request_id()}, token,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(buy, tokens))
        successful = [body["order"] for status, body in results if 200 <= status < 300]
        self.assertEqual(len(successful), 1, results)
        self.assertEqual([status for status, _ in results].count(409), 1, results)
        self.assertEqual(self.product()["stock"], 0)
        order_id = successful[0]["id"]
        self.transition(order_id, "cancel")
        self.transition(order_id, "cancel")
        self.assertEqual(self.product()["stock"], 1)
        status, _ = self.call("POST", f"/api/staff/orders/{order_id}/approve", {}, self.staff_token)
        self.assertEqual(status, 409)
        for token in tokens:
            self.assertEqual(self.me(token)["dice_balance"], 0)

    def test_order_retry_approval_and_roll_grant_once(self):
        token, _ = self.buyer()
        self.set_stock("stock", 5)
        identity = request_id()
        first = self.order(token, 2, identity)
        repeated = self.order(token, 2, identity)
        self.assertEqual(first["id"], repeated["id"])
        self.assertEqual(self.product()["stock"], 3)
        status, _ = self.call(
            "POST", "/api/orders",
            {"items": [{"product_id": self.product_id, "quantity": 1}],
             "request_id": identity}, token,
        )
        self.assertEqual(status, 409)
        self.transition(first["id"], "approve")
        self.transition(first["id"], "approve")
        self.assertEqual(self.me(token)["dice_balance"], 2)
        self.assertEqual(self.product()["stock"], 3)
        status, _ = self.call("POST", f"/api/staff/orders/{first['id']}/cancel", {}, self.staff_token)
        self.assertEqual(status, 409)
        roll_id = request_id()
        first_roll = self.ok("POST", "/api/dice/roll", {"request_id": roll_id}, token)
        retry_roll = self.ok("POST", "/api/dice/roll", {"request_id": roll_id}, token)
        self.assertEqual(first_roll, retry_roll)
        self.assertIn(first_roll["value"], range(1, 7))
        user = self.me(token)
        self.assertEqual(user["score"], first_roll["value"])
        self.assertEqual(user["dice_balance"], 1)

    def test_preorder_import_cancel_and_reclaim(self):
        token, user = self.buyer()
        phone = phone_for(user["name"])
        self.set_stock("stock", 10)
        before_reserved = self.product()["preorder_stock"]
        self.ok(
            "POST", "/api/staff/preorders/import",
            {"reservations": [{"name": user["name"], "phone": phone,
              "items": [{"product_id": self.product_id, "quantity": 2}]}]},
            self.staff_token,
        )
        self.assertEqual(self.product()["stock"], 8)
        self.assertEqual(self.product()["preorder_stock"], before_reserved + 2)
        query = urllib.parse.urlencode({"name": user["name"], "phone": phone})
        reservation = self.ok("GET", "/api/preorders/lookup?" + query, token=token)["reservation"]
        path = f"/api/preorders/{reservation['id']}/claim"
        first_id = request_id()
        order = self.ok("POST", path, {"request_id": first_id}, token)["order"]
        same = self.ok("POST", path, {"request_id": request_id()}, token)["order"]
        self.assertEqual(order["id"], same["id"])
        self.assertEqual(self.product()["preorder_stock"], before_reserved)
        self.transition(order["id"], "cancel")
        self.transition(order["id"], "cancel")
        self.assertEqual(self.product()["preorder_stock"], before_reserved + 2)
        self.assertEqual(self.me(token)["dice_balance"], 0)
        new = self.ok("POST", path, {"request_id": request_id()}, token)["order"]
        self.assertNotEqual(new["id"], order["id"])
        self.transition(new["id"], "approve")
        self.transition(new["id"], "approve")
        self.assertEqual(self.product()["preorder_stock"], before_reserved)
        self.assertEqual(self.me(token)["dice_balance"], 1)
        approved = self.ok("POST", path, {"request_id": request_id()}, token)["order"]
        self.assertEqual(approved["id"], new["id"])

    def test_preorder_claim_requires_phone_verification(self):
        # The demo fixture's first reservation belongs to 김소연. Knowing its
        # identifier must never replace verifying the reservation telephone.
        login = self.ok("POST", "/api/auth/login", {"name": "김소연", "pin": "1234"})
        token = login["token"]
        path = "/api/preorders/1/claim"
        status, _ = self.call("POST", path, {"request_id": request_id()}, token)
        self.assertEqual(status, 403)
        wrong = urllib.parse.urlencode({"name": "김소연", "phone": "01000000000"})
        status, _ = self.call("GET", "/api/preorders/lookup?" + wrong, token=token)
        self.assertEqual(status, 404)
        status, _ = self.call("POST", path, {"request_id": request_id()}, token)
        self.assertEqual(status, 403)
        correct = urllib.parse.urlencode({"name": "김소연", "phone": "01012345678"})
        reservation = self.ok("GET", "/api/preorders/lookup?" + correct, token=token)["reservation"]
        self.assertEqual(reservation["id"], 1)
        order = self.ok("POST", path, {"request_id": request_id()}, token)["order"]
        self.transition(order["id"], "cancel")

    def test_instagram_bonus_once_and_milk_inventory(self):
        token, user = self.buyer()
        dashboard = self.ok("GET", "/api/staff/dashboard", token=self.staff_token)
        milk_before = dashboard["stats"]["milk_stock"]
        if milk_before < 2:
            self.ok("POST", "/api/staff/inventory",
                    {"bucket": "milk", "delta": 2, "reason": "자동 검증용"}, self.staff_token)
            milk_before += 2
        body = {"user_id": user["id"], "request_id": request_id()}
        first = self.ok("POST", "/api/staff/instagram", body, self.staff_token)
        repeated = self.ok("POST", "/api/staff/instagram", body, self.staff_token)
        self.assertEqual(first, repeated)
        body["request_id"] = request_id()
        status, _ = self.call("POST", "/api/staff/instagram", body, self.staff_token)
        self.assertEqual(status, 409)
        dashboard = self.ok("GET", "/api/staff/dashboard", token=self.staff_token)
        self.assertEqual(dashboard["stats"]["milk_stock"], milk_before)
        self.assertEqual(self.me(token)["dice_balance"], 1)

    def test_preorder_import_atomic_and_inventory_bounds(self):
        token, user = self.buyer()
        _, other = self.buyer()
        self.set_stock("stock", 3)
        reserved_before = self.product()["preorder_stock"]
        status, _ = self.call(
            "POST", "/api/staff/preorders/import",
            {"reservations": [
                {"name": user["name"], "phone": phone_for(user["name"]),
                 "items": [{"product_id": self.product_id, "quantity": 2}]},
                {"name": other["name"], "phone": phone_for(other["name"]),
                 "items": [{"product_id": self.product_id, "quantity": 2}]},
            ]}, self.staff_token,
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.product()["stock"], 3)
        self.assertEqual(self.product()["preorder_stock"], reserved_before)
        query = urllib.parse.urlencode({"name": user["name"], "phone": phone_for(user["name"])})
        status, _ = self.call("GET", "/api/preorders/lookup?" + query, token=token)
        self.assertEqual(status, 404)
        status, _ = self.call(
            "POST", "/api/staff/inventory",
            {"product_id": self.product_id, "bucket": "stock",
             "delta": -4, "reason": "음수 재고 방지 검증"}, self.staff_token,
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.product()["stock"], 3)

    def test_manual_sale_creates_buyer_and_validates_existing_pin(self):
        self.set_stock("stock", 5)
        name = "수기" + uuid.uuid4().hex[:10]
        body = {"name": name, "pin": "4567",
                "items": [{"product_id": self.product_id, "quantity": 2}],
                "request_id": request_id()}
        first = self.ok("POST", "/api/staff/manual-sale", body, self.staff_token)
        repeated = self.ok("POST", "/api/staff/manual-sale", body, self.staff_token)
        self.assertEqual(first, repeated)
        self.assertEqual(first["order"]["type"], "manual")
        self.assertEqual(first["order"]["status"], "approved")
        self.assertEqual(self.product()["stock"], 3)
        buyer = self.ok("POST", "/api/auth/login", {"name": name, "pin": "4567"})
        self.assertEqual(self.me(buyer["token"])["dice_balance"], 2)
        body.update(pin="0000", request_id=request_id())
        status, _ = self.call("POST", "/api/staff/manual-sale", body, self.staff_token)
        self.assertEqual(status, 409)
        self.assertEqual(self.product()["stock"], 3)
        self.assertEqual(self.me(buyer["token"])["dice_balance"], 2)

    def test_inventory_retry_changes_stock_and_history_once(self):
        self.set_stock("stock", 5)
        reason = "재고 재시도 검증 " + request_id()
        body = {"product_id": self.product_id, "bucket": "stock", "delta": 2,
                "reason": reason, "request_id": request_id()}
        first = self.ok("POST", "/api/staff/inventory", body, self.staff_token)
        repeated = self.ok("POST", "/api/staff/inventory", body, self.staff_token)
        self.assertEqual(first, repeated)
        self.assertEqual(self.product()["stock"], 7)
        changed = dict(body, delta=3)
        status, _ = self.call("POST", "/api/staff/inventory", changed, self.staff_token)
        self.assertEqual(status, 409)
        self.assertEqual(self.product()["stock"], 7)
        dashboard = self.ok("GET", "/api/staff/dashboard", token=self.staff_token)
        matching_logs = [entry for entry in dashboard["inventory_logs"] if entry["reason"] == reason]
        self.assertEqual(len(matching_logs), 1)
        self.assertEqual(matching_logs[0]["delta"], 2)

    def test_reward_threshold_inventory_and_retry(self):
        token, user = self.buyer()
        self.set_stock("stock", 40)
        self.ok(
            "POST", "/api/staff/manual-sale",
            {"user_id": user["id"],
             "items": [{"product_id": self.product_id, "quantity": 30}],
             "request_id": request_id()}, self.staff_token,
        )
        self.assertEqual(self.me(token)["dice_balance"], 30)
        status, _ = self.call("POST", "/api/rewards/claim", {"request_id": request_id()}, token)
        self.assertEqual(status, 409)
        while self.me(token)["score"] < 20:
            self.ok("POST", "/api/dice/roll", {"request_id": request_id()}, token)

        self.ok('POST','/api/staff/event-supplies',{'key':'oatmeal','delta':1,'reason':'점수 보상 검증','request_id':request_id()},self.staff_token)
        self.ok('POST','/api/staff/inventory',{'product_id':112,'bucket':'stock','delta':1,'reason':'점수 보상 검증'},self.staff_token)
        for threshold in [5,10,15]:
            claimed=self.ok('POST','/api/rewards/claim',{'request_id':request_id()},token)
            self.assertEqual(claimed['reward']['threshold'],threshold)
        # A single eligible product makes the weighted draw deterministic.
        products = self.ok("GET", "/api/products")["products"]
        for product in products:
            target = 1 if product["id"] == self.product_id else 0
            delta = target - product["stock"]
            if delta:
                self.ok("POST", "/api/staff/inventory",
                        {"product_id": product["id"], "bucket": "stock",
                         "delta": delta, "reason": "자동 검증용 공용 재고"}, self.staff_token)
        identity = request_id()
        reward = self.ok("POST", "/api/rewards/claim", {"request_id": identity}, token)
        repeated = self.ok("POST", "/api/rewards/claim", {"request_id": identity}, token)
        self.assertEqual(reward, repeated)
        self.assertEqual(reward["reward"]["product_id"], self.product_id)
        self.assertEqual(reward["reward"]["threshold"], 20)
        self.assertEqual(self.product()["stock"], 0)
        self.assertEqual(self.me(token)["rewards_claimed"], 4)
        self.assertEqual(len(self.ok("GET", "/api/rewards", token=token)["rewards"]), 4)
        status, _ = self.call("POST", "/api/rewards/claim", {"request_id": request_id()}, token)
        self.assertEqual(status, 409)

    def test_profile_saves_through_the_http_and_allowed_origin_path(self):
        request=urllib.request.Request(self.base+'/api/profile',method='OPTIONS',headers={
            'Origin':'http://test.example','Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'Authorization,Content-Type'})
        with urllib.request.urlopen(request,timeout=10) as response:
            self.assertEqual(response.status,204)
            self.assertIn('POST',response.headers['Access-Control-Allow-Methods'])
            self.assertEqual(response.headers['Access-Control-Allow-Origin'],'http://test.example')
        token,user=self.buyer()
        avatar={'face_shape':'pound','skin':'warm','expression':'surprised','glasses':'round','hairpin':'none'}
        status,saved=self.call('POST','/api/profile',{'avatar':avatar},token,headers={'Origin':'http://test.example'})
        self.assertEqual(status,200,saved)
        self.assertEqual(saved['user']['avatar'],avatar)
        self.assertTrue(saved['user']['profile_customized'])
        self.assertEqual(self.me(token)['avatar'],avatar)

    def test_menu_prices_and_donut_set_grants_one_die_per_set(self):
        menu = self.ok('GET', '/api/products')['products']
        expected = {
            '플레인 휘낭시에': 2800, '초코 휘낭시에': 3000,
            '카라멜 휘낭시에': 3000, '무화과 휘낭시에': 3400,
            '로투스 브라우니 치즈케이크': 3800, '레몬 다쿠아즈': 3500,
            '얼그레이 다쿠아즈': 3500, '글레이즈드 도넛 5개 세트': 2000,
            '보늬밤 마들렌': 2800, '에그타르트': 2800, '치즈타르트': 2800, '우유': 1000, '두유': 1000,
        }
        self.assertEqual({p['name']: p['price'] for p in menu}, expected)
        donut = next(p for p in menu if p['name'] == '글레이즈드 도넛 5개 세트')
        self.assertEqual(donut['unit'], '세트')
        self.assertEqual(donut['subtitle'], '구슬')
        if donut['stock'] != 3:
            self.ok('POST', '/api/staff/inventory',
                    {'product_id': donut['id'], 'bucket': 'stock', 'delta': 3-donut['stock'],
                     'reason': '도넛 세트 단위 검증'}, self.staff_token)
        token, user = self.buyer()
        order = self.ok('POST', '/api/orders',
                        {'items': [{'product_id': donut['id'], 'quantity': 2}],
                         'request_id': request_id()}, token)['order']
        self.assertEqual((order['quantity'], order['total']), (2, 4000))
        self.ok('POST', f"/api/staff/orders/{order['id']}/approve", {}, self.staff_token)
        self.assertEqual(self.me(token)['dice_balance'], 2)
        after = self.ok('GET', '/api/products')['products']
        self.assertEqual(next(p for p in after if p['id'] == donut['id'])['stock'], 1)


class CatalogMigrationTests(unittest.TestCase):
    def test_new_menu_keeps_legacy_orders_and_reservations_without_refilling_stock(self):
        from server.app import Application, APIError, hash_pin, normalize_items, order_data, reservation_data
        from server.catalog import sync_catalog
        from server.db import Database
        with tempfile.TemporaryDirectory(prefix='kambo-catalog-test-') as directory:
            environment = dict(os.environ)
            environment.pop('DATABASE_URL', None)
            environment.update(DB_PATH=str(Path(directory)/'legacy.db'), APP_ENV='production',
                               DEMO_SEED='0', STAFF_PASSWORD='test-staff-password')
            with patch.dict(os.environ, environment, clear=True):
                db = Database(ROOT)
                db.initialize()
                with db.transaction(write=True) as tx:
                    tx.execute("INSERT INTO products VALUES (1,'이전 시연 빵','이전 설명',2500,9,2,4,'이전','salt-bread')")
                    buyer = tx.insert("INSERT INTO users (name,phone,role,password_hash,score,created_at) VALUES ('기존구매자','010-0000-0000','buyer',?,7,'2026-11-01')", (hash_pin('1234'),))
                    order = tx.insert("INSERT INTO orders (user_id,customer_name,type,status,total,quantity,created_at) VALUES (?,'기존구매자','walkin','pending',2500,1,'2026-11-01')", (buyer,))
                    tx.execute("INSERT INTO order_items (order_id,product_id,name,quantity,price) VALUES (?,1,'이전 시연 빵',1,2500)", (order,))
                    reservation = tx.insert("INSERT INTO reservations (name,phone,created_at) VALUES ('기존구매자','01000000000','2026-11-01')")
                    tx.execute('INSERT INTO reservation_items (reservation_id,product_id,quantity,price) VALUES (?,1,2,2500)', (reservation,))
                app = Application()
                menu = app.handle('GET', '/api/products', {}, {}, None)['products']
                self.assertEqual(len(menu), 13)
                self.assertNotIn(1, [p['id'] for p in menu])
                with db.transaction(write=True) as tx:
                    self.assertEqual(order_data(tx, order)['items'][0]['name'], '이전 시연 빵')
                    old_reservation = tx.one('SELECT * FROM reservations WHERE id=?', (reservation,))
                    self.assertEqual(reservation_data(tx, old_reservation)['total'], 5000)
                    self.assertEqual(tx.one('SELECT stock,reward_stock FROM products WHERE id=1'), {'stock':13,'reward_stock':0})
                    with self.assertRaises(APIError):
                        normalize_items(tx, [{'product_id':1,'quantity':1}])
                    tx.execute('UPDATE products SET stock=5 WHERE id=101')
                    sync_catalog(tx, demo=True)
                    self.assertEqual(tx.one('SELECT stock FROM products WHERE id=101')['stock'], 5)
                    tx.execute('UPDATE products SET stock=0 WHERE id=101')
                login = app.handle('POST', '/api/auth/login', {}, {'phone':'01000000000','pin':'1234'}, None)
                # Historical products remain outside the current menu, even after stock is merged.
                with self.assertRaises(APIError) as error:
                    app.handle('POST', '/api/rewards/claim', {}, {'request_id':request_id()}, 'Bearer '+login['token'])
                self.assertEqual(error.exception.status, 409)


class FreshDatabaseConfigurationTests(unittest.TestCase):
    def test_non_demo_and_production_have_clean_inventory(self):
        script = """
import json
from server.app import Application
app = Application()
login = app.handle('POST', '/api/staff/login', {},
                   {'name': '초기화검증', 'password': 'test-staff-password'}, None)
dashboard = app.handle('GET', '/api/staff/dashboard', {}, {}, 'Bearer ' + login['token'])
print(json.dumps({'demo': app.demo, 'dashboard': dashboard}))
"""
        for mode, demo_seed in (("development", "0"), ("production", "1")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="kambo-config-test-") as directory:
                environment = os.environ.copy()
                environment.pop("DATABASE_URL", None)
                environment.update(
                    APP_ENV=mode, DEMO_SEED=demo_seed,
                    DB_PATH=str(Path(directory) / "fresh.db"),
                    STAFF_PASSWORD="test-staff-password", ALLOWED_ORIGINS="",
                )
                completed = subprocess.run(
                    [sys.executable, "-c", script], cwd=ROOT, env=environment,
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertFalse(result["demo"])
                dashboard = result["dashboard"]
                self.assertTrue(dashboard["products"])
                for product in dashboard["products"]:
                    self.assertEqual(product["stock"], 0)
                    self.assertEqual(product["preorder_stock"], 0)
                    self.assertEqual(product["reward_stock"], 0)
                self.assertEqual(dashboard["stats"]["milk_stock"], 0)
                self.assertEqual(dashboard["schedule"], [])
                self.assertEqual(dashboard["users"], [])
                self.assertEqual(dashboard["orders"], [])


if __name__ == "__main__":
    unittest.main()
