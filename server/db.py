"""Small SQL adapter. Every write uses a cross-process database lock."""
import contextlib
import os
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('buyer','staff')),
 password_hash TEXT NOT NULL,
 score INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0),
 dice_balance INTEGER NOT NULL DEFAULT 0 CHECK (dice_balance >= 0),
 rewards_claimed INTEGER NOT NULL DEFAULT 0 CHECK (rewards_claimed >= 0),
 created_at TEXT NOT NULL,
 UNIQUE(name, role)
);
CREATE TABLE IF NOT EXISTS user_profiles (
 user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(id),
 appearance TEXT NOT NULL,
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
 user_id INTEGER NOT NULL REFERENCES users(id),
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
 role TEXT NOT NULL
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
        if not self.postgres:
            conn = self.connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            finally:
                conn.close()
        schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") if self.postgres else SCHEMA
        with self.transaction(write=True) as tx:
            for statement in schema.split(";"):
                if statement.strip():
                    tx.execute(statement)
