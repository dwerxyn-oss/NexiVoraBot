import time
from typing import Any, List, Optional

import aiosqlite

from bot.config import DB_PATH, PRODUCTS, PUBLIC_ID_START, ensure_dirs


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    public_id INTEGER UNIQUE,
    username TEXT,
    balance_usd REAL NOT NULL DEFAULT 0,
    task_channel_done INTEGER NOT NULL DEFAULT 0,
    referrer_id INTEGER,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_key TEXT NOT NULL,
    payment TEXT NOT NULL,
    price_usd REAL NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    tg_contact TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);

CREATE TABLE IF NOT EXISTS crypto_topups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL UNIQUE,
    amount_usd REAL NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topups_user ON crypto_topups(user_id);

CREATE TABLE IF NOT EXISTS star_topups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    telegram_charge_id TEXT UNIQUE,
    stars INTEGER NOT NULL,
    amount_usd REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_star_topups_user ON star_topups(user_id);

CREATE TABLE IF NOT EXISTS used_promos (
    user_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    PRIMARY KEY (user_id, code)
);
"""


async def init_db() -> None:
    ensure_dirs()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await _migrate_users(db)
        await db.commit()


async def _migrate_users(db: aiosqlite.Connection) -> None:
    cur = await db.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in await cur.fetchall()}
    await cur.close()
    if "referrer_id" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
    if "created_at" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN created_at REAL")
    if "public_id" not in cols:
        # SQLite не позволяет ADD COLUMN ... UNIQUE на существующей таблице
        await db.execute("ALTER TABLE users ADD COLUMN public_id INTEGER")
    await _backfill_public_ids(db)
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_public_id ON users(public_id)"
    )
    if "nova" in cols:
        pass  # legacy column ignored
    cur = await db.execute("PRAGMA table_info(orders)")
    ocols = {row[1] for row in await cur.fetchall()}
    await cur.close()
    if "extra" not in ocols:
        await db.execute("ALTER TABLE orders ADD COLUMN extra TEXT NOT NULL DEFAULT ''")
    if "price_nova" in ocols:
        pass  # legacy


async def _next_public_id(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT COALESCE(MAX(public_id), ?) FROM users", (PUBLIC_ID_START - 1,))
    row = await cur.fetchone()
    await cur.close()
    return int(row[0]) + 1


async def _backfill_public_ids(db: aiosqlite.Connection) -> None:
    cur = await db.execute("SELECT user_id FROM users WHERE public_id IS NULL ORDER BY user_id")
    rows = await cur.fetchall()
    await cur.close()
    for (uid,) in rows:
        pid = await _next_public_id(db)
        await db.execute("UPDATE users SET public_id = ? WHERE user_id = ?", (pid, uid))


async def ensure_user(user_id: int, username: Optional[str]) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if row:
            d = _row_to_dict(row)
            if d.get("public_id") is None:
                pid = await _next_public_id(db)
                await db.execute("UPDATE users SET public_id = ? WHERE user_id = ?", (pid, user_id))
                await db.commit()
                d["public_id"] = pid
            if username is not None:
                await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
                await db.commit()
            cur2 = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row2 = await cur2.fetchone()
            await cur2.close()
            return _row_to_dict(row2)
        now = time.time()
        pid = await _next_public_id(db)
        await db.execute(
            "INSERT INTO users (user_id, public_id, username, created_at) VALUES (?, ?, ?, ?)",
            (user_id, pid, username or "", now),
        )
        await db.commit()
        cur3 = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row3 = await cur3.fetchone()
        await cur3.close()
        return _row_to_dict(row3)


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


async def fetch_user_by_public_id(public_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE public_id = ?", (public_id,))
        row = await cur.fetchone()
        await cur.close()
        return _row_to_dict(row) if row else None


async def list_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        await cur.close()
        return [int(r[0]) for r in rows]


async def fetch_user(user_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        return _row_to_dict(row) if row else {}


async def set_balance(user_id: int, balance_usd: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance_usd = ? WHERE user_id = ?", (balance_usd, user_id))
        await db.commit()


async def add_balance(user_id: int, delta: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?",
            (delta, user_id),
        )
        await db.commit()


async def set_referrer_if_empty(user_id: int, referrer_id: int) -> bool:
    """Возвращает True, если реферер только что записан."""
    if user_id == referrer_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return False
        if row[0] is not None:
            return False
        ref_cur = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
        ref_row = await ref_cur.fetchone()
        await ref_cur.close()
        if not ref_row:
            return False
        await db.execute(
            "UPDATE users SET referrer_id = ? WHERE user_id = ? AND referrer_id IS NULL",
            (referrer_id, user_id),
        )
        await db.commit()
        return True


async def list_referrals(referrer_id: int) -> List[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT user_id, username, balance_usd FROM users
            WHERE referrer_id = ?
            ORDER BY user_id DESC
            """,
            (referrer_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [_row_to_dict(r) for r in rows]


async def count_user_orders(user_id: int) -> int:
    """Заказы, оплаченные с баланса (для реферальной логики «первая покупка»)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND payment = 'balance_usd'",
            (user_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        return int(row[0]) if row else 0


async def count_orders_total(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        return int(row[0]) if row else 0


async def mark_task_done(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET task_channel_done = 1 WHERE user_id = ?", (user_id,))
        await db.commit()


async def _order_columns(db: aiosqlite.Connection) -> set[str]:
    cur = await db.execute("PRAGMA table_info(orders)")
    cols = {row[1] for row in await cur.fetchall()}
    await cur.close()
    return cols


async def create_order(
    user_id: int,
    product_key: str,
    payment: str,
    price_usd: float,
    email: str,
    tg_contact: str,
    extra: str = "",
    status: str = "performing",
) -> int:
    created = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        cols = await _order_columns(db)
        if "price_nova" in cols:
            cur = await db.execute(
                """
                INSERT INTO orders (
                    user_id, product_key, payment, price_usd, price_nova,
                    email, tg_contact, extra, status, created_at
                )
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (user_id, product_key, payment, price_usd, email, tg_contact, extra, status, created),
            )
        else:
            cur = await db.execute(
                """
                INSERT INTO orders (user_id, product_key, payment, price_usd, email, tg_contact, extra, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, product_key, payment, price_usd, email, tg_contact, extra, status, created),
            )
        await db.commit()
        return int(cur.lastrowid)


async def list_orders(user_id: int) -> List[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [_row_to_dict(r) for r in rows]


async def get_order(order_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = await cur.fetchone()
        await cur.close()
        return _row_to_dict(row) if row else None


async def set_order_status(order_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()


def product_title(key: str) -> str:
    return PRODUCTS[key].title if key in PRODUCTS else key


async def insert_crypto_topup(user_id: int, invoice_id: int, amount_usd: float, payload: str) -> int:
    created = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO crypto_topups (user_id, invoice_id, amount_usd, payload, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (user_id, invoice_id, amount_usd, payload, created),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_topup_internal(topup_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM crypto_topups WHERE id = ?", (topup_id,))
        row = await cur.fetchone()
        await cur.close()
        return _row_to_dict(row) if row else None


async def credit_topup_if_pending(topup_id: int, user_id: int) -> Optional[float]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            cur = await db.execute(
                "SELECT status, amount_usd FROM crypto_topups WHERE id = ? AND user_id = ?",
                (topup_id, user_id),
            )
            row = await cur.fetchone()
            if not row or row[0] != "pending":
                await db.rollback()
                return None
            amount_usd = float(row[1])
            await db.execute(
                "UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?",
                (amount_usd, user_id),
            )
            await db.execute(
                "UPDATE crypto_topups SET status = 'completed' WHERE id = ? AND user_id = ?",
                (topup_id, user_id),
            )
            await db.commit()
            return amount_usd
        except Exception:
            await db.rollback()
            raise


async def insert_star_topup(user_id: int, stars: int, amount_usd: float) -> int:
    created = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO star_topups (user_id, stars, amount_usd, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (user_id, stars, amount_usd, created),
        )
        await db.commit()
        return int(cur.lastrowid)


async def credit_star_topup(topup_id: int, charge_id: str, user_id: int) -> Optional[float]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            cur = await db.execute(
                """
                SELECT status, amount_usd FROM star_topups
                WHERE id = ? AND user_id = ?
                """,
                (topup_id, user_id),
            )
            row = await cur.fetchone()
            if not row or row[0] != "pending":
                await db.rollback()
                return None
            amount_usd = float(row[1])
            await db.execute(
                "UPDATE star_topups SET status = 'completed', telegram_charge_id = ? WHERE id = ?",
                (charge_id, topup_id),
            )
            await db.execute(
                "UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?",
                (amount_usd, user_id),
            )
            await db.commit()
            return amount_usd
        except Exception:
            await db.rollback()
            raise


async def promo_already_used(user_id: int, code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?",
            (user_id, code.lower()),
        )
        row = await cur.fetchone()
        await cur.close()
        return row is not None


async def mark_promo_used(user_id: int, code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO used_promos (user_id, code) VALUES (?, ?)",
            (user_id, code.lower()),
        )
        await db.commit()
