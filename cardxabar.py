import os
import re
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple

import aiosqlite
from dotenv import load_dotenv
load_dotenv()

from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ------------------ Logging ------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper().strip()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cardx_userbot")

# ------------------ Env ------------------

def _req(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v

TG_API_ID = int(os.getenv("TG_API_ID", os.getenv("API_ID", "0")) or "0")
TG_API_HASH = os.getenv("TG_API_HASH", os.getenv("API_HASH", "")).strip()

# Use one of these:
# - TG_SESSION_STRING : Telethon StringSession
# - TG_SESSION        : session file name (default: cardxabar_userbot)
TG_SESSION_STRING = os.getenv("TG_SESSION_STRING", "").strip()
TG_SESSION = os.getenv("TG_SESSION", "cardxabar_userbot").strip()

DB_PATH = os.getenv("DB_PATH", "stars_prod.db").strip()

# Which chats to watch. Default: your private chat with @CardXabarBot
# You can add more: TRACK_CHATS=CardXabarBot,SomeOtherBot,-1001234567890
TRACK_CHATS: List[str] = [x.strip() for x in os.getenv("TRACK_CHATS", "CardXabarBot").split(",") if x.strip()]

# Optional keyword filters (lowercase). If empty -> no keyword check.
KEYWORDS = [x.strip().lower() for x in os.getenv("CARDX_KEYWORDS", "perevod na kartu,перевод на карту").split(",") if x.strip()]
CURRENCY = os.getenv("CARDX_CURRENCY", "UZS").upper().strip()

# Notify (optional) – send a message from your user account when a payment is matched.
NOTIFY_CHAT = os.getenv("NOTIFY_CHAT", "").strip()  # username or chat_id

# ------------------ Helpers ------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

_amount_re = re.compile(r"([0-9][0-9\s,]*)(?:[\.,]([0-9]{1,2}))?\s*(UZS)", re.IGNORECASE)


def extract_amount_uzs(text: str) -> Optional[int]:
    if not text:
        return None

    t = text.replace("\u00a0", " ")
    up = t.upper()
    if CURRENCY not in up:
        return None

    # Accept only incoming transfers (your examples contain a plus sign)
    if ("➕" not in t) and ("+" not in t):
        return None

    # If keywords exist, require at least one keyword OR green circle.
    low = t.lower()
    if KEYWORDS:
        if not any(k in low for k in KEYWORDS) and ("🟢" not in t):
            return None

    m = _amount_re.search(up)
    if not m:
        return None

    num_part = re.sub(r"[^0-9]", "", m.group(1) or "")
    if not num_part:
        return None

    try:
        return int(num_part)
    except Exception:
        return None


# ------------------ DB ------------------

_db: Optional[aiosqlite.Connection] = None
_db_lock = asyncio.Lock()


async def db_open() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=5000")
        # Dedupe table
        await _db.execute(
            """
            CREATE TABLE IF NOT EXISTS cardx_events (
                chat_id INTEGER NOT NULL,
                msg_id INTEGER NOT NULL,
                amount INTEGER,
                order_id INTEGER,
                created_at TEXT NOT NULL,
                raw TEXT,
                PRIMARY KEY(chat_id, msg_id)
            )
            """
        )
        await _db.commit()
    return _db


async def db_try_mark_paid(amount: int, chat_id: int, msg_id: int, raw: str) -> Tuple[bool, Optional[int]]:
    """Returns (matched, order_id)."""
    async with _db_lock:
        db = await db_open()
        # Deduplicate by message
        try:
            await db.execute(
                "INSERT INTO cardx_events(chat_id, msg_id, amount, created_at, raw) VALUES(?, ?, ?, ?, ?)",
                (int(chat_id), int(msg_id), int(amount), now_iso(), raw[:2000])
            )
            await db.commit()
        except Exception:
            # already processed
            return False, None

        nowts = now_iso()
        # Match a pending, not expired order with the same unique amount
        cur = await db.execute(
            """
            SELECT id
            FROM orders
            WHERE pay_status='pending'
              AND pay_amount=?
              AND expires_at > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(amount), nowts)
        )
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "UPDATE cardx_events SET order_id=NULL WHERE chat_id=? AND msg_id=?",
                (int(chat_id), int(msg_id))
            )
            await db.commit()
            return False, None

        order_id = int(row[0])
        paid_at = now_iso()
        await db.execute(
            "UPDATE orders SET pay_status='paid', pay_paid_at=?, updated_at=? WHERE id=?",
            (paid_at, paid_at, order_id)
        )
        await db.execute(
            "UPDATE cardx_events SET order_id=? WHERE chat_id=? AND msg_id=?",
            (order_id, int(chat_id), int(msg_id))
        )
        await db.commit()
        return True, order_id


# ------------------ Telethon ------------------

def build_client() -> TelegramClient:
    if not TG_API_ID or not TG_API_HASH:
        raise RuntimeError("TG_API_ID / TG_API_HASH missing")

    if TG_SESSION_STRING:
        sess = StringSession(TG_SESSION_STRING)
        return TelegramClient(sess, TG_API_ID, TG_API_HASH)

    # File session (Telethon stores as TG_SESSION.session)
    return TelegramClient(TG_SESSION, TG_API_ID, TG_API_HASH)


async def main():
    client = build_client()

    @client.on(events.NewMessage(chats=TRACK_CHATS))
    async def handler(event):
        text = event.raw_text or ""
        amount = extract_amount_uzs(text)
        if amount is None:
            return

        matched, order_id = await db_try_mark_paid(amount, int(event.chat_id), int(event.id), text)
        if matched:
            logger.info("MATCHED payment: amount=%s UZS -> order_id=%s (chat=%s msg=%s)", amount, order_id, event.chat_id, event.id)
            if NOTIFY_CHAT:
                try:
                    await client.send_message(
                        NOTIFY_CHAT,
                        f"✅ Payment matched: {amount} UZS → Order #{order_id} (msg {event.id})"
                    )
                except Exception as e:
                    logger.warning("notify failed: %s", e)
        else:
            logger.info("Payment observed but NOT matched: amount=%s UZS (chat=%s msg=%s)", amount, event.chat_id, event.id)

    logger.info("Starting userbot. Watching chats: %s | DB: %s", TRACK_CHATS, DB_PATH)

    await client.start()
    # keep running
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
