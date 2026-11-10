"""Small SQL adapter. Every write uses a cross-process database lock."""
import contextlib
import os
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 phone TEXT UNIQUE,
 role TEXT NOT NULL CHECK (role IN ('buyer','staff')),
 password_hash TEXT NOT NULL,
 score INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0),
 dice_balance INTEGER NOT NULL DEFAULT 0 CHECK (dice_balance >= 0),
 rewards_claimed INTEGER NOT NULL DEFAULT 0 CHECK (rewards_claimed >= 0),
 created_at TEXT NOT NULL,
 CHECK ((role='buyer' AND phone IS NOT NULL) OR (role='staff' AND phone IS NULL)),
 CHECK (phone IS NULL OR (length(phone)=13 AND substr(phone,1,4)='010-' AND substr(phone,9,1)='-'
  AND replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(phone,
  '0',''),'1',''),'2',''),'3',''),'4',''),'5',''),'6',''),'7',''),'8',''),'9','')='--'))
);
CREATE TABLE IF NOT EXISTS badges (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL,
 icon TEXT NOT NULL CHECK (icon IN ('spark','flask','star','heart','bread','trophy')),
 rule TEXT NOT NULL CHECK (rule IN ('milestone','manual','achievement')),
 threshold INTEGER,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 CHECK ((rule='milestone' AND threshold IS NOT NULL AND threshold>0) OR (rule IN ('manual','achievement') AND threshold IS NULL))
);
CREATE TABLE IF NOT EXISTS titles (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL,
 style TEXT NOT NULL CHECK (style IN ('magic','gold','lightning')),
 rule TEXT NOT NULL CHECK (rule IN ('milestone','manual','achievement')),
 threshold INTEGER,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 CHECK ((rule='milestone' AND threshold IS NOT NULL AND threshold>0) OR (rule IN ('manual','achievement') AND threshold IS NULL))
);
CREATE TABLE IF NOT EXISTS user_profiles (
 user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(id),
 appearance TEXT NOT NULL,
 badge_id TEXT REFERENCES badges(id),
 title_id TEXT REFERENCES titles(id),
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL,
 subtitle TEXT NOT NULL,
 price INTEGER NOT NULL CHECK (price >= 0),
 stock INTEGER NOT NULL CHECK (stock >= 0),
 preorder_stock INTEGER NOT NULL DEFAULT 0 CHECK (preorder_stock >= 0),
 reward_stock INTEGER NOT NULL DEFAULT 0 CHECK (reward_stock >= 0), -- legacy, merged into stock on startup
 category TEXT NOT NULL,
 image TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 phone TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved','pending','approved')),
 user_id INTEGER REFERENCES users(id),
 order_id INTEGER,
 created_at TEXT NOT NULL,
 UNIQUE(name,phone)
);
CREATE TABLE IF NOT EXISTS reservation_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 reservation_id INTEGER NOT NULL REFERENCES reservations(id),
 product_id INTEGER NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL CHECK (quantity > 0),
 price INTEGER NOT NULL CHECK (price >= 0)
);
CREATE TABLE IF NOT EXISTS preorder_verifications (
 user_id INTEGER NOT NULL REFERENCES users(id),
 reservation_id INTEGER NOT NULL REFERENCES reservations(id),
 expires_at TEXT NOT NULL,
 PRIMARY KEY(user_id,reservation_id)
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER REFERENCES users(id),
 customer_name TEXT NOT NULL,
 type TEXT NOT NULL CHECK (type IN ('walkin','preorder','manual')),
 status TEXT NOT NULL CHECK (status IN ('pending','approved','cancelled')),
 reservation_id INTEGER REFERENCES reservations(id),
 total INTEGER NOT NULL CHECK (total >= 0),
 quantity INTEGER NOT NULL CHECK (quantity > 0),
 created_at TEXT NOT NULL,
 approved_at TEXT,
 cancelled_at TEXT
);
CREATE TABLE IF NOT EXISTS guest_order_access (
 token_hash TEXT PRIMARY KEY,
 order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
 fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id),
 name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK (quantity > 0),
 price INTEGER NOT NULL CHECK (price >= 0)
);
CREATE TABLE IF NOT EXISTS inventory_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER REFERENCES products(id),
 product_name TEXT NOT NULL,
 bucket TEXT NOT NULL,
 delta INTEGER NOT NULL,
 reason TEXT NOT NULL,
 actor TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 customer_name TEXT NOT NULL,
 type TEXT NOT NULL,
 milk_quantity INTEGER NOT NULL CHECK (milk_quantity >= 0),
 dice INTEGER NOT NULL CHECK (dice >= 0),
 created_at TEXT NOT NULL,
 UNIQUE(user_id,type)
);
CREATE TABLE IF NOT EXISTS rewards (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 product_id INTEGER NOT NULL REFERENCES products(id),
 product_name TEXT NOT NULL,
 threshold INTEGER NOT NULL CHECK (threshold > 0),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dice_rolls (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 value INTEGER NOT NULL CHECK (value BETWEEN 1 AND 6),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dice_wallet (
 user_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK (quantity >= 0),
 PRIMARY KEY(user_id,kind)
);
CREATE TABLE IF NOT EXISTS typed_dice_rolls (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL,
 result TEXT NOT NULL CHECK (result IN ('score','milk')),
 value INTEGER NOT NULL CHECK (value >= 0 AND value <= 22),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS milestone_claims (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 threshold INTEGER NOT NULL CHECK (threshold IN (5,10,15,20,30)),
 kind TEXT NOT NULL,
 product_id INTEGER REFERENCES products(id),
 product_name TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(user_id,threshold)
);
CREATE TABLE IF NOT EXISTS event_supplies (
 key TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 stock INTEGER NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS user_achievements (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 achievement_key TEXT NOT NULL,
 scope TEXT NOT NULL DEFAULT '',
 exclusive_key TEXT UNIQUE,
 order_id INTEGER REFERENCES orders(id),
 reservation_id INTEGER REFERENCES reservations(id),
 earned_at TEXT NOT NULL,
 UNIQUE(user_id,achievement_key,scope)
);
CREATE TABLE IF NOT EXISTS user_badges (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 badge_id TEXT NOT NULL REFERENCES badges(id),
 source TEXT NOT NULL CHECK (source IN ('milestone','manual','achievement')),
 milestone_id INTEGER REFERENCES milestone_claims(id),
 achievement_id INTEGER REFERENCES user_achievements(id),
 granted_by INTEGER REFERENCES users(id),
 reason TEXT NOT NULL,
 earned_at TEXT NOT NULL,
 UNIQUE(user_id,badge_id),
 CHECK ((source='milestone' AND milestone_id IS NOT NULL AND achievement_id IS NULL AND granted_by IS NULL)
     OR (source='manual' AND milestone_id IS NULL AND achievement_id IS NULL AND granted_by IS NOT NULL)
     OR (source='achievement' AND milestone_id IS NULL AND achievement_id IS NOT NULL AND granted_by IS NULL))
);
CREATE TABLE IF NOT EXISTS user_titles (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 title_id TEXT NOT NULL REFERENCES titles(id),
 source TEXT NOT NULL CHECK (source IN ('milestone','manual','achievement')),
 milestone_id INTEGER REFERENCES milestone_claims(id),
 achievement_id INTEGER REFERENCES user_achievements(id),
 granted_by INTEGER REFERENCES users(id),
 reason TEXT NOT NULL,
 earned_at TEXT NOT NULL,
 UNIQUE(user_id,title_id),
 CHECK ((source='milestone' AND milestone_id IS NOT NULL AND achievement_id IS NULL AND granted_by IS NULL)
     OR (source='manual' AND milestone_id IS NULL AND achievement_id IS NULL AND granted_by IS NOT NULL)
     OR (source='achievement' AND milestone_id IS NULL AND achievement_id IS NOT NULL AND granted_by IS NULL))
);
CREATE TABLE IF NOT EXISTS manual_event_grants (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER REFERENCES users(id),
 customer_name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK (kind IN ('bread','gift','score')),
 product_id INTEGER REFERENCES products(id),
 supply_key TEXT REFERENCES event_supplies(key),
 gift_key TEXT CHECK (gift_key IN ('oatmeal','milk','soymilk','sunglasses','custom')),
 item_name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK (quantity > 0),
 points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
 reason TEXT NOT NULL,
 staff_id INTEGER NOT NULL REFERENCES users(id),
 staff_name TEXT NOT NULL,
 created_at TEXT NOT NULL,
 CHECK ((kind='score' AND user_id IS NOT NULL AND points>0 AND quantity=1)
     OR (kind IN ('bread','gift') AND points=0)),
 CHECK ((kind='bread' AND product_id IS NOT NULL AND supply_key IS NULL AND gift_key IS NULL)
     OR (kind='gift' AND gift_key IS NOT NULL)
     OR (kind='score' AND product_id IS NULL AND supply_key IS NULL AND gift_key IS NULL)),
 CHECK (product_id IS NULL OR supply_key IS NULL),
 CHECK (gift_key!='sunglasses' OR (user_id IS NOT NULL AND quantity=1))
);
CREATE TABLE IF NOT EXISTS reward_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 milestone_id INTEGER UNIQUE REFERENCES milestone_claims(id),
 roll_id INTEGER UNIQUE REFERENCES typed_dice_rolls(id),
 kind TEXT NOT NULL CHECK (kind IN ('bread','milk','oatmeal')),
 status TEXT NOT NULL CHECK (status IN ('awaiting_choice','pending','approved','cancelled')),
 product_id INTEGER REFERENCES products(id),
 supply_key TEXT REFERENCES event_supplies(key),
 product_name TEXT NOT NULL,
 created_at TEXT NOT NULL,
 requested_at TEXT,
 processed_at TEXT,
 processed_by TEXT,
 CHECK ((milestone_id IS NOT NULL AND roll_id IS NULL) OR (milestone_id IS NULL AND roll_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS memos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 content TEXT NOT NULL,
 author TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 time TEXT NOT NULL,
 role TEXT NOT NULL,
 event_date TEXT
);
CREATE TABLE IF NOT EXISTS settings (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
 user_id INTEGER NOT NULL REFERENCES users(id),
 scope TEXT NOT NULL,
 request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 response TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(user_id,scope,request_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_reservation_items_parent ON reservation_items(reservation_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_name ON users(name) WHERE role='staff';
"""


class Transaction:
    def __init__(self, conn, postgres):
        self.conn = conn
        self.postgres = postgres

    def execute(self, sql, values=()):
        return self.conn.execute(sql.replace("?", "%s") if self.postgres else sql, values)

    def one(self, sql, values=()):
        row = self.execute(sql, values).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql, values=()):
        return [dict(row) for row in self.execute(sql, values).fetchall()]

    def insert(self, sql, values=()):
        if self.postgres:
            return self.execute(sql + " RETURNING id", values).fetchone()["id"]
        return self.execute(sql, values).lastrowid


class Database:
    def __init__(self, root):
        self.url = os.environ.get("DATABASE_URL", "").strip()
        self.postgres = bool(self.url)
        if self.postgres and not self.url.startswith(("postgres://", "postgresql://")):
            raise RuntimeError("DATABASE_URL must use postgres:// or postgresql://")
        self.path = Path(os.environ.get("DB_PATH", str(root / "data" / "kambodelight.db"))).expanduser()
        if not self.postgres:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        if self.postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("PostgreSQL requires: pip install -r requirements-postgres.txt") from exc
            return psycopg.connect(self.url, row_factory=dict_row)
        conn = sqlite3.connect(str(self.path), timeout=20, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 20000")
        return conn

    @contextlib.contextmanager
    def transaction(self, write=False):
        conn = self.connect()
        tx = Transaction(conn, self.postgres)
        try:
            if self.postgres:
                # psycopg opens a transaction before the first command.
                if write:
                    # All application writes share this lock, across workers and hosts.
                    conn.execute("SELECT pg_advisory_xact_lock(731042026)")
            else:
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield tx
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.transaction() as tx:
            if self.postgres:
                columns=tx.all("SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='users'")
            else:
                columns=tx.all('PRAGMA table_info(users)')
            if columns and 'phone' not in {row['name'] for row in columns}:
                raise RuntimeError('전화번호 계정용 DB 재생성이 필요합니다. 서버를 멈춘 뒤 python3 ops/reset-db.py --yes 를 실행하세요. 기존 DB는 자동 백업됩니다.')
        if not self.postgres:
            conn = self.connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            finally:
                conn.close()
        self.allow_guest_orders()
        schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") if self.postgres else SCHEMA
        with self.transaction(write=True) as tx:
            for statement in schema.split(";"):
                if statement.strip():
                    tx.execute(statement)
            if self.postgres:
                columns=tx.all("SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='user_profiles'")
            else:
                columns=tx.all('PRAGMA table_info(user_profiles)')
            if 'badge_id' not in {row['name'] for row in columns}:
                tx.execute('ALTER TABLE user_profiles ADD COLUMN badge_id TEXT REFERENCES badges(id)')
            if 'title_id' not in {row['name'] for row in columns}:
                tx.execute('ALTER TABLE user_profiles ADD COLUMN title_id TEXT REFERENCES titles(id)')
            if self.postgres:
                schedule_columns=tx.all("SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='schedule'")
            else:
                schedule_columns=tx.all('PRAGMA table_info(schedule)')
            if 'event_date' not in {row['name'] for row in schedule_columns}:
                tx.execute('ALTER TABLE schedule ADD COLUMN event_date TEXT')
            tx.execute("INSERT INTO settings(key,value) VALUES('schema_version','phone_accounts_v1') ON CONFLICT(key) DO NOTHING")
        self.allow_achievement_badges()

    def allow_achievement_badges(self):
        """Extend the previous badge CHECKs without resetting ownership or profiles."""
        if self.postgres:
            with self.transaction(write=True) as tx:
                columns=tx.all("SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='user_badges'")
                if 'achievement_id' in {row['name'] for row in columns}:
                    return
                tx.execute('ALTER TABLE user_badges ADD COLUMN achievement_id BIGINT REFERENCES user_achievements(id)')
                for table in ('badges','user_badges'):
                    constraints=tx.all("SELECT conname FROM pg_constraint WHERE conrelid=?::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE ?",(table,'%rule%' if table=='badges' else '%source%'))
                    for row in constraints:
                        name=row['conname'].replace('"','""')
                        tx.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
                tx.execute("ALTER TABLE badges ADD CHECK (rule IN ('milestone','manual','achievement'))")
                tx.execute("ALTER TABLE badges ADD CHECK ((rule='milestone' AND threshold IS NOT NULL AND threshold>0) OR (rule IN ('manual','achievement') AND threshold IS NULL))")
                tx.execute("ALTER TABLE user_badges ADD CHECK (source IN ('milestone','manual','achievement'))")
                tx.execute("ALTER TABLE user_badges ADD CHECK ((source='milestone' AND milestone_id IS NOT NULL AND achievement_id IS NULL AND granted_by IS NULL) OR (source='manual' AND milestone_id IS NULL AND achievement_id IS NULL AND granted_by IS NOT NULL) OR (source='achievement' AND milestone_id IS NULL AND achievement_id IS NOT NULL AND granted_by IS NULL))")
            return
        conn=self.connect()
        try:
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute('BEGIN IMMEDIATE')
            for table in ('badges','user_badges'):
                old=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                if "'achievement'" in old['sql']:
                    continue
                columns=','.join(row['name'] for row in conn.execute(f'PRAGMA table_info({table})'))
                sequence=conn.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
                objects=conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL",(table,)).fetchall()
                ddl=SCHEMA[SCHEMA.index(f'CREATE TABLE IF NOT EXISTS {table} ('):].split(';',1)[0]
                conn.execute(ddl.replace(f'IF NOT EXISTS {table}',f'{table}_achievement_upgrade',1))
                conn.execute(f'INSERT INTO {table}_achievement_upgrade ({columns}) SELECT {columns} FROM {table}')
                conn.execute(f'DROP TABLE {table}')
                conn.execute(f'ALTER TABLE {table}_achievement_upgrade RENAME TO {table}')
                if sequence:
                    conn.execute('UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?',(sequence['seq'],table))
                for row in objects:
                    conn.execute(row['sql'])
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('배지·도전과제 구조 업데이트 중 외래키 검사에 실패했습니다. 기존 DB를 유지합니다.')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def allow_guest_orders(self):
        """Make the existing order owner optional, preserving records and IDs."""
        if self.postgres:
            with self.transaction(write=True) as tx:
                if tx.one("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='orders'"):
                    tx.execute('ALTER TABLE orders ALTER COLUMN user_id DROP NOT NULL')
            return
        conn = self.connect()
        try:
            # SQLite requires a table rebuild to remove NOT NULL. Disable FK
            # enforcement only on this connection, before the atomic rebuild.
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute('BEGIN IMMEDIATE')
            columns = conn.execute('PRAGMA table_info(orders)').fetchall()
            if any(row['name']=='user_id' and row['notnull'] for row in columns):
                sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='orders'").fetchone()
                objects = conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name='orders' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
                ddl = SCHEMA[SCHEMA.index('CREATE TABLE IF NOT EXISTS orders ('):].split(';',1)[0]
                conn.execute(ddl.replace('IF NOT EXISTS orders', 'orders_guest_upgrade'))
                fields = ','.join(row['name'] for row in columns)
                conn.execute(f'INSERT INTO orders_guest_upgrade ({fields}) SELECT {fields} FROM orders')
                conn.execute('DROP TABLE orders')
                conn.execute('ALTER TABLE orders_guest_upgrade RENAME TO orders')
                if sequence:
                    conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='orders'", (sequence['seq'],))
                for row in objects:
                    conn.execute(row['sql'])
                if conn.execute('PRAGMA foreign_key_check').fetchone():
                    raise RuntimeError('비회원 주문 구조 업데이트 중 외래키 검사에 실패했습니다. 기존 DB를 유지합니다.')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
