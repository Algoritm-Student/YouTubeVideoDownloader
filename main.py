import os
import warnings
import secrets
warnings.filterwarnings("ignore", message=r'Field "model_.*".*protected namespace "model_".*')
import re
import html
import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite
import httpx
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Fragment.com direct requests (NO third-party Fragment API library)
# We only use TON wallet libs to sign/send the on-chain transaction returned by Fragment.
try:
    from tonutils.client import TonapiClient, ToncenterV3Client  # type: ignore
    from tonutils.wallet import WalletV4R2, WalletV5R1  # type: ignore
    from tonutils.wallet.messages import TransferMessage  # type: ignore
except Exception:
    TonapiClient = ToncenterV3Client = WalletV4R2 = WalletV5R1 = TransferMessage = None  # type: ignore

try:
    from pytoniq_core import Cell  # type: ignore
except Exception:
    Cell = None  # type: ignore

# ===================== Logging =====================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper().strip()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")


# ===================== Helpers =====================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()

def h(s: Any) -> str:
    return html.escape("" if s is None else str(s))

def fmt_som(n: int) -> str:
    # 9821 -> "9 821"
    s = f"{int(n):,}".replace(",", " ")
    return s

def clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def parse_int_list(csv_text: str) -> List[int]:
    out: List[int] = []
    for p in (csv_text or "").split(","):
        p = p.strip()
        if not p:
            continue
        if re.fullmatch(r"\d+", p):
            out.append(int(p))
    out = sorted(set([x for x in out if x > 0]))
    return out

def normalize_username(raw: str) -> str:
    t = (raw or "").strip()
    if t.startswith("@"):
        t = t[1:]
    # only allowed chars
    t = re.sub(r"[^a-zA-Z0-9_]", "", t)
    return t

def money_base(qty: int, rate: int, fee: int) -> int:
    return int(qty) * int(rate) + int(fee)

def safe_int(s: str, default: int) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default

# ===================== Config =====================
@dataclass
class Cfg:
    bot_token: str
    admins: List[int]
    db_path: str
    gold_base: str
    gold_api_key: str
    # defaults (DB can override)
    rate_uzs: int
    fee_uzs: int
    packs: List[int]
    rand_min: int
    rand_max: int
    ttl_minutes: int
    check_interval_sec: int
    broadcast_batch: int
    pay_card: str
    pay_name: str
    # fragment
    frag_cookies: str
    frag_hash: str
    wallet_mnemonic: str
    wallet_api_key: str
    wallet_version: str

def env_required(name: str) -> str:
    v = os.getenv(name)
    if not v or not v.strip():
        raise RuntimeError(f"Missing required env: {name}")
    return v.strip()

def build_cfg() -> Cfg:
    load_dotenv()
    bot_token = env_required("BOT_TOKEN")
    admins = [int(x.strip()) for x in (os.getenv("ADMINS", "")).split(",") if x.strip().isdigit()]
    db_path = os.getenv("DB_PATH", "stars_prod.db").strip()
    gold_base = env_required("GOLD_BASE").strip()
    gold_api_key = os.getenv("GOLD_API_KEY", "").strip()
    rate_uzs = safe_int(os.getenv("UZS_PER_STAR", "195"), 195)
    fee_uzs = safe_int(os.getenv("UZS_FIXED_FEE", "0"), 0)
    # Premium prices are stored in DB config (can be set via Admin panel).
    packs = parse_int_list(os.getenv("PACKS", "50,100,500,1000"))
    rand_min = safe_int(os.getenv("RAND_MIN", "1"), 1)
    rand_max = safe_int(os.getenv("RAND_MAX", "99"), 99)
    ttl_minutes = safe_int(os.getenv("ORDER_TTL_MINUTES", "30"), 30)
    check_interval_sec = safe_int(os.getenv("CHECK_INTERVAL_SEC", "10"), 10)
    broadcast_batch = safe_int(os.getenv("BROADCAST_BATCH", "30"), 30)
    pay_card = os.getenv("PAY_CARD", "").strip()
    pay_name = os.getenv("PAY_NAME", "").strip()
    frag_cookies = os.getenv("FRAGMENT_COOKIES", "").strip()
    frag_hash = os.getenv("FRAGMENT_HASH", "").strip()
    wallet_mnemonic = os.getenv("WALLET_MNEMONIC", "").strip()
    wallet_api_key = os.getenv("WALLET_API_KEY", os.getenv("TONAPI_KEY", "")).strip()
    wallet_version = os.getenv("WALLET_VERSION", "V4R2").strip()
    return Cfg(
        bot_token=bot_token,
        admins=admins,
        db_path=db_path,
        gold_base=gold_base,
        gold_api_key=gold_api_key,
        rate_uzs=rate_uzs,
        fee_uzs=fee_uzs,
        packs=packs or [50, 100, 500, 1000],
        rand_min=rand_min,
        rand_max=rand_max,
        ttl_minutes=ttl_minutes,
        check_interval_sec=check_interval_sec,
        broadcast_batch=broadcast_batch,
        pay_card=pay_card,
        pay_name=pay_name,
        frag_cookies=frag_cookies,
        frag_hash=frag_hash,
        wallet_mnemonic=wallet_mnemonic,
        wallet_api_key=wallet_api_key,
        wallet_version=wallet_version,
    )

# ===================== DB =====================
CREATE_SQL = [
    """
    CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_seen TEXT,
    last_seen TEXT,
    blocked INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    buyer_username TEXT,
    target_username TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT 'stars',
    qty INTEGER NOT NULL,
    base_amount INTEGER NOT NULL,
    pay_amount INTEGER NOT NULL,
    rand_delta INTEGER NOT NULL,
    payment_id TEXT NOT NULL,
    pay_status TEXT DEFAULT 'pending',          -- pending|paid|cancelled|failed|expired
    pay_created_at TEXT,
    pay_paid_at TEXT,
    delivery_status TEXT DEFAULT 'pending',     -- pending|success|failed
    delivery_tx TEXT,
    delivery_error TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS config (
    k TEXT PRIMARY KEY,
    v TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    source_chat_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    status TEXT DEFAULT 'queued',               -- queued|running|done
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    cursor_user_id INTEGER DEFAULT 0
    )
    """
]

DEFAULT_CONFIG = {
    "BOT_ENABLED": "1",
    "SALES_ENABLED": "1",
    "UZS_PER_STAR": "195",
    "UZS_FIXED_FEE": "0",
    "UZS_PREMIUM_3M": "0",
    "UZS_PREMIUM_6M": "0",
    "UZS_PREMIUM_12M": "0",
    "PACKS": "50,100,500,1000",
    "RAND_MIN": "1",
    "RAND_MAX": "99",
    "ORDER_TTL_MINUTES": "30",
    "CHECK_INTERVAL_SEC": "10",
    "BROADCAST_BATCH": "30",
    "PAY_CARD": "",
    "PAY_NAME": "",
}

async def db_init(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        for q in CREATE_SQL:
            await db.execute(q)
        await db.commit()

        # --- DB migrations (keep old DBs working) ---
        try:
            cur = await db.execute("PRAGMA table_info(orders)")
            cols = [r[1] for r in await cur.fetchall()]
            if "product" not in cols:
                await db.execute("ALTER TABLE orders ADD COLUMN product TEXT NOT NULL DEFAULT 'stars'")
                await db.commit()
        except Exception:
            # ignore migration errors (fresh DB already has correct schema)
            pass
        for k, v in DEFAULT_CONFIG.items():
            await db.execute("INSERT OR IGNORE INTO config(k, v) VALUES(?, ?)", (k, v))
        await db.commit()

        # Apply premium price defaults from env on first run (only if still 0 in DB)
        for key in ("UZS_PREMIUM_3M", "UZS_PREMIUM_6M", "UZS_PREMIUM_12M"):
            env_v = os.getenv(key, "").strip()
            if env_v.isdigit() and int(env_v) > 0:
                cur = await db.execute("SELECT v FROM config WHERE k=?", (key,))
                row = await cur.fetchone()
                if (not row) or (str(row[0]).strip() in ("", "0")):
                    await db.execute("INSERT INTO config(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, env_v))
        await db.commit()

async def db_get_cfg(db_path: str, k: str) -> str:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT v FROM config WHERE k=?", (k,))
        row = await cur.fetchone()
        if row and row[0] is not None:
            return str(row[0]).strip()
        return str(DEFAULT_CONFIG.get(k, "")).strip()

async def db_set_cfg(db_path: str, k: str, v: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO config(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, v)
        )
        await db.commit()

async def db_upsert_user(db_path: str, user_id: int, username: str):
    ts = iso(now_utc())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users(user_id, username, first_seen, last_seen)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, last_seen=excluded.last_seen
            """,
            (user_id, username, ts, ts)
        )
        await db.commit()

async def db_count_users(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return int(row[0] if row else 0)

async def db_create_order(
    db_path: str,
    user_id: int,
    buyer_username: str,
    target_username: str,
    product: str,
    qty: int,
    base_amount: int,
    pay_amount: int,
    rand_delta: int,
    payment_id: str,
    expires_at: str
) -> int:
    ts = iso(now_utc())
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO orders(
            user_id, buyer_username, target_username, product, qty,
            base_amount, pay_amount, rand_delta,
            payment_id, pay_status, pay_created_at,
            expires_at, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (user_id, buyer_username, target_username, product, qty, base_amount, pay_amount, rand_delta, payment_id, ts, expires_at, ts, ts)
        )
        await db.commit()
        return int(cur.lastrowid)

async def db_get_order(db_path: str, order_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def db_list_orders_by_user(db_path: str, user_id: int, limit: int, offset: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def db_count_orders_by_user(db_path: str, user_id: int) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return int(row[0] if row else 0)

async def db_amount_used_pending(db_path: str, pay_amount: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT 1 FROM orders WHERE pay_status='pending' AND expires_at > ? AND pay_amount=? LIMIT 1",
            (iso(now_utc()), int(pay_amount))
        )
        row = await cur.fetchone()
        return bool(row)

async def db_list_pending_pay(db_path: str, limit: int = 50) -> List[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id FROM orders WHERE pay_status='pending' AND expires_at > ? ORDER BY id ASC LIMIT ?",
            (iso(now_utc()), limit)
        )
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]

async def db_list_expired_pending(db_path: str, limit: int = 200) -> List[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id FROM orders WHERE pay_status='pending' AND expires_at <= ? ORDER BY id ASC LIMIT ?",
            (iso(now_utc()), limit)
        )
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]

async def db_list_paid_need_delivery(db_path: str, limit: int = 25) -> List[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id FROM orders WHERE pay_status='paid' AND delivery_status IN ('pending','failed') ORDER BY id ASC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]

async def db_update_payment(db_path: str, order_id: int, status: str, paid_at: Optional[str] = None):
    ts = iso(now_utc())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE orders SET pay_status=?, pay_paid_at=COALESCE(?, pay_paid_at), updated_at=?
            WHERE id=?
            """,
            (status, paid_at, ts, order_id)
        )
        await db.commit()

async def db_update_delivery(db_path: str, order_id: int, status: str, tx: Optional[str], err: Optional[str]):
    ts = iso(now_utc())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE orders SET delivery_status=?, delivery_tx=?, delivery_error=?, updated_at=?
            WHERE id=?
            """,
            (status, tx, err, ts, order_id)
        )
        await db.commit()

async def db_admin_stats(db_path: str) -> Dict[str, int]:
    async with aiosqlite.connect(db_path) as db:
        out: Dict[str, int] = {}
        queries = [
            ("users", "SELECT COUNT(*) FROM users"),
            ("orders", "SELECT COUNT(*) FROM orders"),
            ("pending", "SELECT COUNT(*) FROM orders WHERE pay_status='pending'"),
            ("paid", "SELECT COUNT(*) FROM orders WHERE pay_status='paid'"),
            ("delivered", "SELECT COUNT(*) FROM orders WHERE delivery_status='success'"),
            ("failed_delivery", "SELECT COUNT(*) FROM orders WHERE delivery_status='failed'"),
            ("revenue", "SELECT COALESCE(SUM(pay_amount),0) FROM orders WHERE pay_status='paid'"),
        ]
        for k, q in queries:
            cur = await db.execute(q)
            row = await cur.fetchone()
            out[k] = int(row[0] if row else 0)
        return out

async def db_admin_list_orders(db_path: str, where: str, params: Tuple[Any, ...], limit: int, offset: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def db_admin_count_orders(db_path: str, where: str, params: Tuple[Any, ...]) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(f"SELECT COUNT(*) FROM orders {where}", params)
        row = await cur.fetchone()
        return int(row[0] if row else 0)

# Broadcast
async def db_create_broadcast(db_path: str, admin_id: int, chat_id: int, msg_id: int) -> int:
    ts = iso(now_utc())
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO broadcasts(admin_id, source_chat_id, source_message_id, status, created_at, updated_at)
            VALUES(?, ?, ?, 'queued', ?, ?)
            """,
            (admin_id, chat_id, msg_id, ts, ts)
        )
        await db.commit()
        return int(cur.lastrowid)

async def db_get_next_broadcast(db_path: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM broadcasts WHERE status IN ('queued','running') ORDER BY id ASC LIMIT 1")
        row = await cur.fetchone()
        return dict(row) if row else None

async def db_update_broadcast(db_path: str, bc_id: int, status: str, sent: int, fail: int, cursor: int):
    ts = iso(now_utc())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE broadcasts SET status=?, sent_count=?, fail_count=?, cursor_user_id=?, updated_at=?
            WHERE id=?
            """,
            (status, sent, fail, cursor, ts, bc_id)
        )
        await db.commit()

async def db_iter_users_from(db_path: str, cursor_user_id: int, limit: int) -> List[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT user_id FROM users WHERE user_id>? AND blocked=0 ORDER BY user_id ASC LIMIT ?",
            (cursor_user_id, limit)
        )
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]

async def db_mark_user_blocked(db_path: str, user_id: int, blocked: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE users SET blocked=? WHERE user_id=?", (blocked, user_id))
        await db.commit()

# ===================== Gold Client =====================
class GoldClient:
    def __init__(self, base: str, api_key: str, http: httpx.AsyncClient):
        self.base = base.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.http = http

    async def create(self, amount_uzs: int) -> str:
        url = f"{self.base}?method=create"
        data = {"amount": str(int(amount_uzs))}
        if self.api_key:
            data["api_key"] = self.api_key
        r = await self.http.post(url, data=data)
        r.raise_for_status()
        js = r.json()
        pid = js.get("payment_id") or (js.get("data", {}) or {}).get("payment_id")
        if not pid:
            raise RuntimeError(f"Gold create bad response: {js}")
        return str(pid)

    async def check(self, payment_id: str) -> Tuple[str, Optional[str], Dict[str, Any]]:
        url = f"{self.base}?method=check"
        params = {"payment_id": payment_id}
        if self.api_key:
            params["api_key"] = self.api_key
        r = await self.http.get(url, params=params)
        r.raise_for_status()
        js = r.json()
        data = js.get("data") if isinstance(js, dict) else None
        status = None
        paid_at = None
        # Your real example: js["data"]["status"] == "paid"
        if isinstance(data, dict):
            status = data.get("status")
            paid_at = data.get("date") or data.get("paid_at")
        if not status:
            status = js.get("status") or js.get("pay_status")
        s = str(status).lower()
        if s in ("paid", "success", "ok", "done"):
            return "paid", paid_at, js
        if s in ("pending", "wait", "created", "processing"):
            return "pending", None, js
        if s in ("cancelled", "canceled"):
            return "cancelled", None, js
        if s in ("failed", "error"):
            return "failed", None, js
        return "pending", None, js

# ===================== Fragment Service (DIRECT fragment.com) =====================
FRAGMENT_API_URL = "https://fragment.com/api"

def _parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (cookie_header or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def _fragment_default_headers(referer: str) -> Dict[str, str]:
    # Mimic a normal browser request (helps Fragment return the right JSON)
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://fragment.com",
        "referer": referer,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }

def _extract_hash_from_html(html_text: str) -> Optional[str]:
    m = re.search(r"(?:https://fragment\.com)?/api\?hash=([a-f0-9]+)", html_text or "")
    return m.group(1) if m else None

def _b64_pad(s: str) -> str:
    s = (s or "").strip()
    s = "".join(ch for ch in s if ch.isalnum() or ch in "+/=")
    s += "=" * (-len(s) % 4)
    return s

def _payload_to_body(payload_b64: str) -> Any:
    # Best-effort convert Fragment payload (base64) to a TON Cell.
    # Falls back to plain string if pytoniq_core isn't available.
    try:
        if Cell is not None:
            import base64 as _b64
            return Cell.one_from_boc(_b64.b64decode(_b64_pad(payload_b64)))
    except Exception:
        pass
    return payload_b64

class FragmentService:
    def __init__(self, cfg: Cfg, http: httpx.AsyncClient):
        self.cfg = cfg
        self.http = http
        self.lock = asyncio.Lock()
        self.enabled = False

        self.cookies: Dict[str, str] = {}
        self.hash_cache: Dict[str, str] = {}  # page_url -> hash
        self.wallet = None
        self.pub_key_hex: Optional[str] = None

    async def start(self):
        required = [self.cfg.frag_cookies, self.cfg.wallet_mnemonic, self.cfg.wallet_api_key]
        if not all([x and x.strip() for x in required]):
            logger.warning("Fragment disabled: missing env (FRAGMENT_COOKIES / WALLET_MNEMONIC / WALLET_API_KEY)")
            self.enabled = False
            return

        if TonapiClient is None or (WalletV4R2 is None and WalletV5R1 is None) or TransferMessage is None:
            logger.warning("Fragment disabled: tonutils not installed. Install: pip install tonutils pytoniq-core")
            self.enabled = False
            return

        self.cookies = _parse_cookie_header(self.cfg.frag_cookies)
        self.enabled = True
        logger.info("Fragment delivery: ENABLED (direct fragment.com)")

    async def stop(self):
        # http client is managed by App
        pass

    def _mnemonic_words(self) -> List[str]:
        return [w for w in (self.cfg.wallet_mnemonic or "").strip().split() if w]

    async def _get_wallet_and_pubkey(self):
        if self.wallet is not None and self.pub_key_hex:
            return self.wallet, self.pub_key_hex

        mnemonic = self._mnemonic_words()
        client = TonapiClient(api_key=self.cfg.wallet_api_key, is_testnet=False)

        ver = (self.cfg.wallet_version or "V4R2").upper().strip()
        if ver in ("V5R1", "5", "V5"):
            wallet, pub_key, _, _ = WalletV5R1.from_mnemonic(client=client, mnemonic=mnemonic)
        else:
            wallet, pub_key, _, _ = WalletV4R2.from_mnemonic(client=client, mnemonic=mnemonic)

        self.wallet = wallet
        self.pub_key_hex = pub_key.hex() if hasattr(pub_key, "hex") else str(pub_key)
        return self.wallet, self.pub_key_hex

    async def _account_info(self) -> Dict[str, Any]:
        wallet, pub_hex = await self._get_wallet_and_pubkey()
        # state_init boc -> base64
        import base64 as _b64
        state_init = ""
        try:
            boc = wallet.state_init.serialize().to_boc()
            state_init = _b64.b64encode(boc).decode()
        except Exception:
            try:
                boc = bytes(wallet.state_init)
                state_init = _b64.b64encode(boc).decode()
            except Exception:
                state_init = ""

        return {
            "address": wallet.address.to_str(False, False),
            "publicKey": pub_hex,
            "chain": "-239",
            "walletStateInit": state_init,
        }

    async def _get_fragment_hash(self, page_url: str, referer: str) -> str:
        # 1) If user set FRAGMENT_HASH env, always use it (keeps existing env behavior).
        if self.cfg.frag_hash and self.cfg.frag_hash.strip():
            return self.cfg.frag_hash.strip()

        # 2) Otherwise auto-fetch + cache by page_url
        if page_url in self.hash_cache:
            return self.hash_cache[page_url]

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "user-agent": _fragment_default_headers(referer)["user-agent"],
            "referer": "https://fragment.com/",
        }
        r = await self.http.get(page_url, headers=headers, cookies=self.cookies)
        r.raise_for_status()
        hsh = _extract_hash_from_html(r.text)
        if not hsh:
            raise RuntimeError("Failed to extract Fragment hash from page HTML")
        self.hash_cache[page_url] = hsh
        return hsh

    async def _post_api(self, hsh: str, data: Dict[str, Any], referer: str) -> Dict[str, Any]:
        headers = _fragment_default_headers(referer)
        r = await self.http.post(FRAGMENT_API_URL, params={"hash": hsh}, data=data, headers=headers, cookies=self.cookies)
        r.raise_for_status()
        return r.json()

    async def _process_tx(self, tx_json: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        # Executes on-chain tx described by Fragment response.
        if "transaction" not in tx_json:
            return False, None, "no_transaction"

        tr = tx_json.get("transaction") or {}
        msgs = tr.get("messages") or []
        if not msgs:
            return False, None, "no_messages"

        msg = msgs[0]
        dest = msg.get("address")
        amount_nano = msg.get("amount")
        payload = msg.get("payload")
        if not dest or not amount_nano:
            return False, None, "bad_tx_fields"

        # Basic balance check (avoid wasting API calls)
        try:
            if ToncenterV3Client is not None:
                client = ToncenterV3Client(is_testnet=False, rps=1, max_retries=1)
                mnemonic = self._mnemonic_words()
                ver = (self.cfg.wallet_version or "V4R2").upper().strip()
                if ver in ("V5R1", "5", "V5"):
                    wallet, _, _, _ = WalletV5R1.from_mnemonic(client=client, mnemonic=mnemonic)
                else:
                    wallet, _, _, _ = WalletV4R2.from_mnemonic(client=client, mnemonic=mnemonic)
                bal = await wallet.balance()
                if float(bal) <= 0:
                    return False, None, "wallet_balance_zero"
        except Exception:
            pass

        client = TonapiClient(api_key=self.cfg.wallet_api_key, is_testnet=False)
        mnemonic = self._mnemonic_words()
        ver = (self.cfg.wallet_version or "V4R2").upper().strip()
        if ver in ("V5R1", "5", "V5"):
            wallet, _, _, _ = WalletV5R1.from_mnemonic(client=client, mnemonic=mnemonic)
        else:
            wallet, _, _, _ = WalletV4R2.from_mnemonic(client=client, mnemonic=mnemonic)

        body = _payload_to_body(payload or "")
        try:
            messages = [TransferMessage(destination=dest, amount=int(amount_nano) / 1_000_000_000, body=body)]
            tx_hash = await wallet.batch_transfer_messages(messages=messages)
            return True, str(tx_hash), None
        except Exception as e:
            return False, None, str(e)

    async def _link_wallet_if_needed(self, hsh: str, account: Dict[str, Any], referer: str) -> bool:
        js = await self._post_api(hsh, {"account": account, "device": "iPhone15,2", "method": "linkWallet"}, referer)
        if js.get("ok"):
            return True
        if "transaction" in js:
            ok, _, _ = await self._process_tx(js)
            return ok
        return False

    async def get_wallet_balance_ton(self) -> Tuple[Optional[float], Optional[str]]:
        if not self.enabled:
            return None, None
        try:
            mnemonic = self._mnemonic_words()
            if ToncenterV3Client is None:
                return None, None
            client = ToncenterV3Client(is_testnet=False, rps=1, max_retries=1)
            ver = (self.cfg.wallet_version or "V4R2").upper().strip()
            if ver in ("V5R1", "5", "V5"):
                wallet, _, _, _ = WalletV5R1.from_mnemonic(client=client, mnemonic=mnemonic)
            else:
                wallet, _, _, _ = WalletV4R2.from_mnemonic(client=client, mnemonic=mnemonic)
            bal = await wallet.balance()
            addr = wallet.address.to_str(is_user_friendly=True)
            return float(bal), addr
        except Exception:
            return None, None

    async def validate_stars_username(self, username: str) -> Tuple[bool, str]:
        if not self.enabled:
            return False, "fragment_not_ready"
        u = normalize_username(username)
        if not u:
            return False, "bad_username"

        async with self.lock:
            try:
                referer = "https://fragment.com/stars/buy"
                hsh = await self._get_fragment_hash("https://fragment.com/stars/buy", referer)
                js = await self._post_api(hsh, {"query": u, "quantity": "", "method": "searchStarsRecipient"}, referer)
                recipient = (js.get("found") or {}).get("recipient")
                if recipient:
                    return True, "ok"
                return False, "not_found"
            except Exception as e:
                return False, str(e)

    async def validate_premium_username(self, username: str, months: int) -> Tuple[bool, str]:
        if not self.enabled:
            return False, "fragment_not_ready"
        u = normalize_username(username)
        if not u:
            return False, "bad_username"
        if months not in (3, 6, 12):
            return False, "bad_months"

        async with self.lock:
            try:
                referer = "https://fragment.com/premium/gift"
                hsh = await self._get_fragment_hash("https://fragment.com/premium/gift", referer)
                js = await self._post_api(hsh, {"query": u, "months": months, "method": "searchPremiumGiftRecipient"}, referer)
                recipient = (js.get("found") or {}).get("recipient")
                if recipient:
                    return True, "ok"
                return False, "not_found"
            except Exception as e:
                return False, str(e)

    async def buy_stars(self, username: str, qty: int) -> Tuple[bool, Optional[str], Optional[str]]:
        if not self.enabled:
            return False, None, "fragment_not_ready"
        u = normalize_username(username)
        if not u or qty < 50:
            return False, None, "bad_params"

        async with self.lock:
            try:
                referer = "https://fragment.com/stars/buy"
                hsh = await self._get_fragment_hash("https://fragment.com/stars/buy", referer)
                account = await self._account_info()

                js = await self._post_api(hsh, {"query": u, "quantity": "", "method": "searchStarsRecipient"}, referer)
                recipient = (js.get("found") or {}).get("recipient")
                if not recipient:
                    return False, None, "not_found"

                js = await self._post_api(hsh, {"recipient": recipient, "quantity": int(qty), "method": "initBuyStarsRequest"}, referer)
                req_id = js.get("req_id")
                if not req_id:
                    return False, None, "init_failed"

                tx_data = {
                    "account": account,
                    "device": "iPhone15,2",
                    "transaction": 1,
                    "id": req_id,
                    "show_sender": 0,
                    "method": "getBuyStarsLink",
                }
                tx = await self._post_api(hsh, tx_data, referer)

                if tx.get("need_verify"):
                    ok = await self._link_wallet_if_needed(hsh, account, referer)
                    if not ok:
                        return False, None, "wallet_link_failed"
                    tx = await self._post_api(hsh, tx_data, referer)

                ok, tx_hash, err = await self._process_tx(tx)
                if ok:
                    return True, tx_hash, None
                return False, None, err or "tx_failed"
            except Exception as e:
                return False, None, str(e)

    async def buy_premium(self, username: str, months: int) -> Tuple[bool, Optional[str], Optional[str]]:
        if not self.enabled:
            return False, None, "fragment_not_ready"
        u = normalize_username(username)
        if not u or months not in (3, 6, 12):
            return False, None, "bad_params"

        async with self.lock:
            try:
                referer = "https://fragment.com/premium/gift"
                hsh = await self._get_fragment_hash("https://fragment.com/premium/gift", referer)
                account = await self._account_info()

                js = await self._post_api(hsh, {"query": u, "months": months, "method": "searchPremiumGiftRecipient"}, referer)
                recipient = (js.get("found") or {}).get("recipient")
                if not recipient:
                    return False, None, "not_found"

                import time as _time
                await self._post_api(hsh, {"mode": "new", "lv": "false", "dh": str(int(_time.time())), "method": "updatePremiumState"}, referer)

                js = await self._post_api(hsh, {"recipient": recipient, "months": months, "method": "initGiftPremiumRequest"}, referer)
                req_id = js.get("req_id")
                if not req_id:
                    return False, None, "init_failed"

                ref = "".join(random.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(9))
                tx_data = {
                    "account": account,
                    "device": {
                        "appVersion": "5.4.3",
                        "platform": "iphone",
                        "features": [
                            "SendTransaction",
                            {"maxMessages": 255, "name": "SendTransaction"},
                            {"types": ["text", "binary", "cell"], "name": "SignData"},
                        ],
                        "appName": "Tonkeeper",
                        "maxProtocolVersion": 2,
                    },
                    "transaction": 1,
                    "id": req_id,
                    "show_sender": 1,
                    "ref": ref,
                    "method": "getGiftPremiumLink",
                }

                tx = await self._post_api(hsh, tx_data, referer)
                if tx.get("need_verify"):
                    ok = await self._link_wallet_if_needed(hsh, account, referer)
                    if not ok:
                        return False, None, "wallet_link_failed"
                    tx = await self._post_api(hsh, tx_data, referer)

                ok, tx_hash, err = await self._process_tx(tx)
                if ok:
                    return True, tx_hash, None
                return False, None, err or "tx_failed"
            except Exception as e:
                return False, None, str(e)


# ===================== UI: Keyboards =====================# ===================== UI: Keyboards =====================
def kb_main(is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐️ Stars", callback_data="m:stars")
    kb.button(text="🎁 Premium", callback_data="m:premium")
    kb.button(text="🧾 Buyurtmalarim", callback_data="m:orders")
    kb.button(text="ℹ️ Yordam", callback_data="m:help")
    if is_admin:
        kb.button(text="🛠 Admin panel", callback_data="adm:home")
        kb.adjust(2, 2, 1)
    else:
        kb.adjust(2, 2)
    return kb.as_markup()

def kb_back_menu(to: str = "m:home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Ortga", callback_data=to)
    kb.adjust(1)
    return kb.as_markup()

def kb_buy_qty(packs: List[int], rate: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    show = packs[:6] if packs else [50, 100, 500, 1000]
    for p in show:
        kb.button(text=f"{p}⭐️", callback_data=f"buy:q:{p}")
    kb.button(text="✍️ Boshqa miqdor", callback_data="buy:custom")
    kb.button(text="⬅️ Menu", callback_data="m:home")
    # layout
    if len(show) >= 4:
        kb.adjust(2, 2, 2, 1, 1)
    else:
        kb.adjust(2, 1, 1)
    return kb.as_markup()

def kb_premium_months(p3: int, p6: int, p12: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=("3 oy" if p3 > 0 else "3 oy (OFF)"), callback_data="pr:m:3")
    kb.button(text=("6 oy" if p6 > 0 else "6 oy (OFF)"), callback_data="pr:m:6")
    kb.button(text=("12 oy" if p12 > 0 else "12 oy (OFF)"), callback_data="pr:m:12")
    kb.button(text="⬅️ Menu", callback_data="m:home")
    kb.adjust(3, 1)
    return kb.as_markup()

def kb_username_step(back_to: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 O'zimga", callback_data="buy:me")
    kb.button(text="⬅️ Ortga", callback_data=back_to)
    kb.adjust(1, 1)
    return kb.as_markup()

def kb_pay_type(back_to: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Karta", callback_data="pay:card")
    kb.button(text="⬅️ Ortga", callback_data=back_to)
    kb.adjust(1, 1)
    return kb.as_markup()

def kb_order_view(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Yangilash", callback_data=f"ord:refresh:{order_id}")
    kb.button(text="🧾 Buyurtmalarim", callback_data="m:orders")
    kb.button(text="⬅️ Menu", callback_data="m:home")
    kb.adjust(1, 2)
    return kb.as_markup()

def kb_orders_list(page: int, total_pages: int, orders: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        product = str(o.get("product") or "stars")
        qty = int(o.get("qty") or 0)
        title = ("⭐️" if product == "stars" else "🎁")
        kb.button(
            text=f"{title} #{o['id']} · {qty}{'⭐️' if product=='stars' else ' oy'} · {fmt_som(int(o['pay_amount']))} so'm",
            callback_data=f"ord:view:{o['id']}"
        )
    if page > 0:
        kb.button(text="⬅️", callback_data=f"ord:page:{page-1}")
    if page < total_pages - 1:
        kb.button(text="➡️", callback_data=f"ord:page:{page+1}")
    kb.button(text="⬅️ Menu", callback_data="m:home")
    kb.adjust(1, 2, 1)
    return kb.as_markup()

# Admin
def kb_admin_home() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Statistika", callback_data="adm:stats")
    kb.button(text="📦 Orderlar", callback_data="adm:orders:all:0")
    kb.button(text="💰 Narxlar", callback_data="adm:price")
    kb.button(text="💳 Karta", callback_data="adm:card")
    kb.button(text="📣 Broadcast", callback_data="adm:broadcast")
    kb.button(text="⚙️ Bot ON/OFF", callback_data="adm:toggle")
    kb.button(text="⬅️ Menu", callback_data="m:home")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()

def kb_admin_orders(filter_key: str, page: int, total_pages: int, orders: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        product = str(o.get("product") or "stars")
        qty = int(o.get("qty") or 0)
        title = ("⭐" if product == "stars" else "🎁")
        kb.button(
            text=f"{title} #{o['id']} · {qty}{'⭐' if product=='stars' else 'm'} · {o['pay_status']} · {o['delivery_status']}",
            callback_data=f"adm:order:{o['id']}"
        )
    if page > 0:
        kb.button(text="⬅️", callback_data=f"adm:orders:{filter_key}:{page-1}")
    if page < total_pages - 1:
        kb.button(text="➡️", callback_data=f"adm:orders:{filter_key}:{page+1}")
    kb.button(text="⬅️ Admin", callback_data="adm:home")
    kb.adjust(1, 2, 1)
    return kb.as_markup()

def kb_admin_order(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚚 Retry delivery", callback_data=f"adm:retry:{order_id}")
    kb.button(text="✅ Mark paid", callback_data=f"adm:markpaid:{order_id}")
    kb.button(text="✅ Mark delivered", callback_data=f"adm:markdel:{order_id}")
    kb.button(text="⬅️ Orderlar", callback_data="adm:orders:all:0")
    kb.adjust(2, 2)
    return kb.as_markup()

def kb_admin_price() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ UZS/star", callback_data="adm:set:rate")
    kb.button(text="➕ Fee", callback_data="adm:set:fee")
    kb.button(text="🎲 Random MIN", callback_data="adm:set:rmin")
    kb.button(text="🎲 Random MAX", callback_data="adm:set:rmax")
    kb.button(text="⭐ Packs", callback_data="adm:set:packs")
    kb.button(text="🎁 Premium 3m", callback_data="adm:set:prem3")
    kb.button(text="🎁 Premium 6m", callback_data="adm:set:prem6")
    kb.button(text="🎁 Premium 12m", callback_data="adm:set:prem12")
    kb.button(text="⬅️ Admin", callback_data="adm:home")
    kb.adjust(2, 2, 1, 2, 2, 1)
    return kb.as_markup()

def kb_admin_card() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Karta raqami", callback_data="adm:set:card")
    kb.button(text="👤 Karta egasi", callback_data="adm:set:name")
    kb.button(text="⬅️ Admin", callback_data="adm:home")
    kb.adjust(2, 1)
    return kb.as_markup()

def kb_admin_toggle(bot_on: int, sales_on: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=("🤖 Bot: ON" if bot_on else "🤖 Bot: OFF"), callback_data="adm:toggle:bot")
    kb.button(text=("🛒 Sotuv: ON" if sales_on else "🛒 Sotuv: OFF"), callback_data="adm:toggle:sales")
    kb.button(text="⬅️ Admin", callback_data="adm:home")
    kb.adjust(2, 1)
    return kb.as_markup()


# ===================== UI: Text renderers =====================# ===================== UI: Text renderers =====================
async def get_settings(cfg: Cfg) -> Dict[str, Any]:
    rate = safe_int(await db_get_cfg(cfg.db_path, "UZS_PER_STAR"), cfg.rate_uzs)
    fee = safe_int(await db_get_cfg(cfg.db_path, "UZS_FIXED_FEE"), cfg.fee_uzs)
    packs = parse_int_list(await db_get_cfg(cfg.db_path, "PACKS")) or cfg.packs
    rmin = safe_int(await db_get_cfg(cfg.db_path, "RAND_MIN"), cfg.rand_min)
    rmax = safe_int(await db_get_cfg(cfg.db_path, "RAND_MAX"), cfg.rand_max)
    ttl = safe_int(await db_get_cfg(cfg.db_path, "ORDER_TTL_MINUTES"), cfg.ttl_minutes)
    interval = safe_int(await db_get_cfg(cfg.db_path, "CHECK_INTERVAL_SEC"), cfg.check_interval_sec)
    bot_on = safe_int(await db_get_cfg(cfg.db_path, "BOT_ENABLED"), 1)
    sales_on = safe_int(await db_get_cfg(cfg.db_path, "SALES_ENABLED"), 1)
    card = await db_get_cfg(cfg.db_path, "PAY_CARD")
    name = await db_get_cfg(cfg.db_path, "PAY_NAME")

    prem3 = safe_int(await db_get_cfg(cfg.db_path, "UZS_PREMIUM_3M"), 0)
    prem6 = safe_int(await db_get_cfg(cfg.db_path, "UZS_PREMIUM_6M"), 0)
    prem12 = safe_int(await db_get_cfg(cfg.db_path, "UZS_PREMIUM_12M"), 0)

    return dict(
        rate=rate, fee=fee, packs=packs,
        rmin=rmin, rmax=rmax, ttl=ttl, interval=interval,
        bot_on=bot_on, sales_on=sales_on,
        card=card, name=name,
        prem3=prem3, prem6=prem6, prem12=prem12,
    )

def _product_title(product: str, qty: int) -> str:
    if product == "premium":
        return f"Telegram Premium · {qty} oy"
    return f"Telegram Stars · {qty}⭐️"

def t_stars_menu(rate: int, fee: int, packs: List[int]) -> str:
    ptxt = " · ".join(str(x) for x in packs[:6]) if packs else "50 · 100 · 500 · 1000"
    fee_txt = f" + {fmt_som(fee)} so'm" if int(fee) > 0 else ""
    return (
        "⭐️ <b>Telegram Stars</b>\n"
        "────────────────────────────\n"
        f"🚀 Kurs: 1⭐️ ≈ <b>{fmt_som(rate)}</b> so'm{fee_txt}\n"
        f"📦 Paketlar: <b>{h(ptxt)}</b>\n\n"
        "Pastdan miqdorni tanlang yoki <b>Boshqa miqdor</b>ni bosing."
    )

def t_premium_menu(prem3: int, prem6: int, prem12: int) -> str:
    def row(m: int, v: int) -> str:
        if v <= 0:
            price = "❌ sozlanmagan"
        else:
            price = f"<b>{fmt_som(v)}</b> so'm"
        return f"• <b>{m} oy</b> — {price}"
    return (
        "🎁 <b>Telegram Premium sovg'a</b>\n"
        "────────────────────────────\n"
        f"{row(3, prem3)}\n"
        f"{row(6, prem6)}\n"
        f"{row(12, prem12)}\n\n"
        "Pastdan muddatni tanlang."
    )

def t_order_details(product: str, qty: int, base_amount: int) -> str:
    return (
        "🛒 <b>Buyurtma tafsilotlari</b>\n"
        "────────────────────────────\n"
        f"📦 Mahsulot: <b>{h(_product_title(product, qty))}</b>\n"
        f"💰 To'lov: <b>{fmt_som(base_amount)}</b> so'm\n\n"
        "👇 Username kiriting (masalan: <code>@username</code>) yoki 👤 <b>O'zimga</b> tugmani bosing."
    )

def t_pay_type(product: str, qty: int, target: str, base_amount: int) -> str:
    return (
        "💳 <b>To'lov turini tanlang</b>\n"
        "────────────────────────────\n"
        f"📦 Mahsulot: <b>{h(_product_title(product, qty))}</b>\n"
        f"👤 Qabul qiluvchi: <code>@{h(target)}</code>\n"
        f"💰 Narxi: <b>{fmt_som(base_amount)}</b> so'm"
    )

def t_wait_payment(product: str, qty: int, target: str, pay_amount: int, card: str, ttl_min: int, name: str) -> str:
    return (
        "✅ <b>To'lov yaratildi!</b>\n"
        "────────────────────────────\n"
        f"📦 Mahsulot: <b>{h(_product_title(product, qty))}</b>\n"
        f"👤 Qabul qiluvchi: <code>@{h(target)}</code>\n"
        f"💳 Karta: <code>{h(card)}</code>\n"
        f"👤 Karta egasi: <b>{h(name)}</b>\n"
        f"💰 To'lanadigan summa: <b>{fmt_som(pay_amount)}</b> so'm\n"
        f"⏳ Muddat: <b>{ttl_min} daqiqa</b>\n\n"
        "❗️ Summani aynan shunday yuboring (random qo'shilgan bo'lishi mumkin).\n"
        "To'lov tushishi bilan bot avtomatik tekshiradi va yetkazadi."
    )

async def t_home(cfg: Cfg, frag: FragmentService, user: Message) -> str:
    st = await get_settings(cfg)
    bot_on = st["bot_on"]
    sales_on = st["sales_on"]
    rate = st["rate"]

    if bot_on != 1:
        return "⚠️ <b>Bot vaqtincha texnik xizmatda.</b>\nIltimos, keyinroq urinib ko'ring."

    name = h(user.from_user.first_name if user.from_user else "do'st")
    status = "✅ ON" if sales_on == 1 else "❌ OFF"

    bal_txt = "—"
    addr_txt = ""
    if frag.enabled:
        ton, addr = await frag.get_wallet_balance_ton()
        if ton is not None:
            bal_txt = f"{ton:.6f} TON"
        if addr:
            addr_txt = f"\n🏦 Wallet: <code>{h(addr)}</code>"

    return (
        f"👋 Salom, <b>{name}</b>\n"
        f"💎 Bot balansi: <b>{bal_txt}</b>{addr_txt}\n"
        f"🚀 Kurs: 1⭐️ ≈ <b>{fmt_som(rate)}</b> so'm\n"
        f"🛒 Sotuv: <b>{status}</b>\n\n"
        "Pastdan tanlang 👇"
    )

async def t_order_view(cfg: Cfg, order: Dict[str, Any]) -> str:
    st = await get_settings(cfg)
    card = st["card"]
    name = st["name"]

    pay_status = str(order.get("pay_status") or "")
    del_status = str(order.get("delivery_status") or "")
    product = str(order.get("product") or "stars")
    qty = int(order.get("qty") or 0)

    expires_at = datetime.fromisoformat(order["expires_at"])
    left = int((expires_at - now_utc()).total_seconds())
    left_txt = "0s" if left <= 0 else f"{left//60}m {left%60}s"

    note = ""
    if pay_status == "paid" and del_status == "pending":
        note = "\n⏳ To'lov tasdiqlandi. Yetkazilmoqda..."
    elif pay_status == "paid" and del_status == "failed":
        note = "\n⚠️ Yetkazish xatolik. Admin retry qilishi mumkin."
    elif pay_status == "pending":
        note = "\n⏳ To'lov hali tasdiqlanmagan. (Avto-check ishlayapti)"
    elif pay_status in ("failed", "cancelled", "expired"):
        note = "\n❌ Bu order bo'yicha to'lov yakunlanmadi."

    return (
        "✨ <b>Order holati</b>\n"
        "────────────────────────────\n"
        f"🧾 Order: <b>#{order['id']}</b>\n"
        f"📦 Mahsulot: <b>{h(_product_title(product, qty))}</b>\n"
        f"👤 Qabul qiluvchi: <code>@{h(order['target_username'])}</code>\n"
        f"💰 Summa: <b>{fmt_som(int(order['pay_amount']))}</b> so'm\n"
        f"📌 Pay: <b>{h(pay_status)}</b> · Delivery: <b>{h(del_status)}</b>\n"
        f"⏳ Qolgan vaqt: <b>{left_txt}</b>\n"
        f"💳 Karta: <code>{h(card)}</code>\n"
        f"👤 Karta egasi: <b>{h(name)}</b>\n"
        f"{note}"
    )


# ===================== States =====================# ===================== States =====================
class BuyFlow(StatesGroup):
    waiting_custom_qty = State()
    waiting_username = State()

class AdminFlow(StatesGroup):
    waiting_value = State()
    waiting_broadcast_message = State()

# ===================== App Context =====================
class App:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.http = httpx.AsyncClient(timeout=30)
        self.gold = None
        # Enable Gold API only if configured AND not forced to manual
        force_manual = os.getenv("PAYMENT_MODE", "").strip().lower() in {"manual", "card", "userbot"} or os.getenv("FORCE_MANUAL_PAYMENT", "").strip().lower() in {"1","true","yes"}
        if cfg.gold_base and (not force_manual):
            self.gold = GoldClient(cfg.gold_base, cfg.gold_api_key, self.http)
        self.frag = FragmentService(cfg, self.http)
        self.worker_task: Optional[asyncio.Task] = None
        self.broadcast_task: Optional[asyncio.Task] = None

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.cfg.admins

APP = App(build_cfg())
bot = Bot(
    APP.cfg.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# ===================== Workers =====================
async def generate_unique_amount(cfg: Cfg, base_amount: int) -> Tuple[int, int]:
    st = await get_settings(cfg)
    rmin = clamp_int(int(st["rmin"]), 0, 9999)
    rmax = clamp_int(int(st["rmax"]), 0, 9999)
    if rmin > rmax:
        rmin, rmax = rmax, rmin
    for _ in range(60):
        delta = random.randint(rmin, rmax)
        pay_amount = int(base_amount) + int(delta)
        used = await db_amount_used_pending(cfg.db_path, pay_amount)
        if not used:
            return pay_amount, delta
    delta = random.randint(rmin, rmax)
    return int(base_amount) + int(delta), delta

async def worker_loop():
    logger.info("Worker started")
    while True:
        try:
            st = await get_settings(APP.cfg)
            interval = max(3, int(st["interval"]))
        except Exception:
            interval = APP.cfg.check_interval_sec
        # expire old pending
        try:
            expired = await db_list_expired_pending(APP.cfg.db_path, limit=200)
            for oid in expired:
                await db_update_payment(APP.cfg.db_path, oid, "expired", None)
        except Exception as e:
            logger.warning("expire loop err: %s", e)
        # check pending payments (only when Gold API is enabled)
        if APP.gold is not None:
            try:
                ids = await db_list_pending_pay(APP.cfg.db_path, limit=50)
                for oid in ids:
                    o = await db_get_order(APP.cfg.db_path, oid)
                    if not o:
                        continue
                    try:
                        status, paid_at, raw = await APP.gold.check(o["payment_id"])
                        logger.info("[GOLD] check pid=%s oid=%s -> %s raw=%s", o["payment_id"], oid, status, raw)
                        if status == "paid":
                            await db_update_payment(APP.cfg.db_path, oid, "paid", paid_at or iso(now_utc()))
                        elif status in ("failed", "cancelled"):
                            await db_update_payment(APP.cfg.db_path, oid, status, None)
                    except Exception as e:
                        logger.warning("[GOLD] check err oid=%s: %s", oid, e)
            except Exception as e:
                logger.warning("pending loop err: %s", e)

        # deliver paid
        try:
            ids = await db_list_paid_need_delivery(APP.cfg.db_path, limit=25)
            for oid in ids:
                o = await db_get_order(APP.cfg.db_path, oid)
                if not o:
                    continue
                if not APP.frag.enabled:
                    continue

                product = str(o.get("product") or "stars")
                username = str(o["target_username"])
                qty = int(o["qty"])
                user_id = int(o["user_id"])

                if product == "premium":
                    ok, tx, err = await APP.frag.buy_premium(username, qty)
                else:
                    ok, tx, err = await APP.frag.buy_stars(username, qty)

                if ok:
                    logger.info("[FRAGMENT] deliver product=%s @%s qty=%s -> OK tx=%s", product, username, qty, tx)
                    await db_update_delivery(APP.cfg.db_path, oid, "success", tx, None)
                    try:
                        title = ("🎁 Premium" if product == "premium" else "⭐️ Stars")
                        tail = (f"{qty} oy" if product == "premium" else f"{qty}⭐️")
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                "✅ <b>Yetkazildi!</b>\n"
                                f"🧾 Order: <b>#{oid}</b>\n"
                                f"📦 {title}: <b>{tail}</b>\n"
                                f"👤 @{h(username)}\n"
                                f"🔗 Tx: <code>{h(tx or '')}</code>"
                            ),
                        )
                    except Exception:
                        pass
                else:
                    logger.warning("[FRAGMENT] deliver product=%s @%s qty=%s -> FAIL err=%s", product, username, qty, err)
                    await db_update_delivery(APP.cfg.db_path, oid, "failed", None, err)
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                "⚠️ <b>Yetkazishda xatolik</b>\n"
                                f"🧾 Order: <b>#{oid}</b>\n"
                                f"👤 @{h(username)}\n"
                                f"❌ Error: <code>{h(err or 'unknown')}</code>\n\n"
                                "Admin avtomatik yoki qo\'lda retry qilishi mumkin."
                            ),
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("delivery loop err: %s", e)
        await asyncio.sleep(interval)

async def broadcast_loop():
    logger.info("Broadcast worker started")
    while True:
        try:
            bc = await db_get_next_broadcast(APP.cfg.db_path)
            if not bc:
                await asyncio.sleep(2)
                continue
            bc_id = int(bc["id"])
            status = str(bc["status"])
            sent = int(bc.get("sent_count") or 0)
            fail = int(bc.get("fail_count") or 0)
            cursor = int(bc.get("cursor_user_id") or 0)
            if status == "queued":
                await db_update_broadcast(APP.cfg.db_path, bc_id, "running", sent, fail, cursor)
                status = "running"
            batch = safe_int(await db_get_cfg(APP.cfg.db_path, "BROADCAST_BATCH"), APP.cfg.broadcast_batch)
            batch = max(5, batch)
            users = await db_iter_users_from(APP.cfg.db_path, cursor, limit=batch)
            if not users:
                await db_update_broadcast(APP.cfg.db_path, bc_id, "done", sent, fail, cursor)
                await asyncio.sleep(1)
                continue
            for uid in users:
                cursor = uid
                try:
                    await bot.copy_message(
                        chat_id=uid,
                        from_chat_id=int(bc["source_chat_id"]),
                        message_id=int(bc["source_message_id"])
                    )
                    sent += 1
                except Exception as e:
                    fail += 1
                    if "bot was blocked" in str(e).lower():
                        await db_mark_user_blocked(APP.cfg.db_path, uid, 1)
                await asyncio.sleep(0.04)
            await db_update_broadcast(APP.cfg.db_path, bc_id, "running", sent, fail, cursor)
        except Exception as e:
            logger.warning("broadcast loop err: %s", e)
        await asyncio.sleep(1)

# ===================== Startup / Shutdown =====================
async def on_startup():
    logger.info("BOT START")
    logger.info("DB: %s", APP.cfg.db_path)
    logger.info("Admins: %s", APP.cfg.admins)
    await db_init(APP.cfg.db_path)
    # seed DB config from env defaults (only if empty)
    await db_set_cfg(APP.cfg.db_path, "UZS_PER_STAR", str(APP.cfg.rate_uzs))
    await db_set_cfg(APP.cfg.db_path, "UZS_FIXED_FEE", str(APP.cfg.fee_uzs))
    await db_set_cfg(APP.cfg.db_path, "PACKS", ",".join(map(str, APP.cfg.packs)))
    await db_set_cfg(APP.cfg.db_path, "RAND_MIN", str(APP.cfg.rand_min))
    await db_set_cfg(APP.cfg.db_path, "RAND_MAX", str(APP.cfg.rand_max))
    await db_set_cfg(APP.cfg.db_path, "ORDER_TTL_MINUTES", str(APP.cfg.ttl_minutes))
    await db_set_cfg(APP.cfg.db_path, "CHECK_INTERVAL_SEC", str(APP.cfg.check_interval_sec))
    await db_set_cfg(APP.cfg.db_path, "BROADCAST_BATCH", str(APP.cfg.broadcast_batch))
    if APP.cfg.pay_card:
        await db_set_cfg(APP.cfg.db_path, "PAY_CARD", APP.cfg.pay_card)
    if APP.cfg.pay_name:
        await db_set_cfg(APP.cfg.db_path, "PAY_NAME", APP.cfg.pay_name)
    await APP.frag.start()
    # background tasks
    APP.worker_task = asyncio.create_task(worker_loop())
    APP.broadcast_task = asyncio.create_task(broadcast_loop())

async def on_shutdown():
    try:
        if APP.worker_task:
            APP.worker_task.cancel()
        if APP.broadcast_task:
            APP.broadcast_task.cancel()
    except Exception:
        pass
    try:
        await APP.frag.stop()
    except Exception:
        pass
    try:
        await APP.http.aclose()
    except Exception:
        pass
    logger.info("BOT STOP")

# ===================== Handlers =====================
async def safe_edit(msg: Message, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        try:
            await msg.answer(text, reply_markup=kb)
        except Exception:
            pass

# Prevent double "Pay" taps creating 2 orders
_PAY_LOCKS: Dict[int, asyncio.Lock] = {}

def _user_lock(user_id: int) -> asyncio.Lock:
    lock = _PAY_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _PAY_LOCKS[user_id] = lock
    return lock

@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await db_upsert_user(APP.cfg.db_path, m.from_user.id, m.from_user.username or "")
    text = await t_home(APP.cfg, APP.frag, m)
    await m.answer(text, reply_markup=kb_main(APP.is_admin(m.from_user.id)))

@dp.callback_query(F.data == "m:home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await db_upsert_user(APP.cfg.db_path, c.from_user.id, c.from_user.username or "")
    text = await t_home(APP.cfg, APP.frag, c.message)  # type: ignore
    await safe_edit(c.message, text, kb_main(APP.is_admin(c.from_user.id)))

@dp.callback_query(F.data == "m:help")
async def cb_help(c: CallbackQuery):
    await c.answer()
    text = (
        "ℹ️ <b>Yordam</b>\n"
        "────────────────────────────\n"
        "⭐️ <b>Stars</b>: miqdorni tanlang → @username → to'lov → avtomatik yuboriladi.\n"
        "🎁 <b>Premium</b>: 3/6/12 oy → @username → to'lov → avtomatik gift qilinadi.\n\n"
        "✅ To'lovni bot ko'rsatgan <b>aniq summa</b> bilan yuboring.\n"
        "❗ Username xato bo'lsa, buyurtma to'xtaydi.\n"
        "🧾 Yetkazish statusini <b>Buyurtmalarim</b> bo'limida ko'rasiz."
    )
    await safe_edit(c.message, text, kb_back_menu("m:home"))

def _check_sales_or_alert(st: Dict[str, Any], c: CallbackQuery) -> Optional[bool]:
    if int(st["bot_on"]) != 1:
        asyncio.create_task(c.answer("Bot vaqtincha o'chiq.", show_alert=True))
        return None
    if int(st["sales_on"]) != 1:
        asyncio.create_task(c.answer("Sotuv vaqtincha yopiq.", show_alert=True))
        return None
    return True

@dp.callback_query(F.data == "m:stars")
async def cb_stars_menu(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    st = await get_settings(APP.cfg)
    if _check_sales_or_alert(st, c) is None:
        return
    if not APP.frag.enabled:
        return await c.answer("Delivery sozlanmagan (Fragment).", show_alert=True)
    text = t_stars_menu(int(st["rate"]), int(st["fee"]), st["packs"])
    await safe_edit(c.message, text, kb_buy_qty(st["packs"], int(st["rate"])))

@dp.callback_query(F.data == "m:premium")
async def cb_premium_menu(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    st = await get_settings(APP.cfg)
    if _check_sales_or_alert(st, c) is None:
        return
    if not APP.frag.enabled:
        return await c.answer("Delivery sozlanmagan (Fragment).", show_alert=True)
    text = t_premium_menu(int(st["prem3"]), int(st["prem6"]), int(st["prem12"]))
    await safe_edit(c.message, text, kb_premium_months(int(st["prem3"]), int(st["prem6"]), int(st["prem12"])))

@dp.callback_query(F.data.startswith("buy:q:"))
async def cb_buy_qty_pick(c: CallbackQuery, state: FSMContext):
    await c.answer()
    st = await get_settings(APP.cfg)
    qty = int(c.data.split(":")[-1])
    base = money_base(qty, int(st["rate"]), int(st["fee"]))
    await state.update_data(product="stars", qty=qty, base=base, back_to="m:stars")
    await state.set_state(BuyFlow.waiting_username)
    await safe_edit(c.message, t_order_details("stars", qty, base), kb_username_step("m:stars"))

@dp.callback_query(F.data == "buy:custom")
async def cb_buy_custom(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.update_data(product="stars", back_to="m:stars")
    await state.set_state(BuyFlow.waiting_custom_qty)
    text = (
        "✍️ <b>Boshqa miqdor</b>\n"
        "Kerakli Stars miqdorini yuboring.\n"
        "Masalan: <code>150</code>\n"
        "Chegara: 50 .. 100000"
    )
    await safe_edit(c.message, text, kb_back_menu("m:stars"))

@dp.message(BuyFlow.waiting_custom_qty)
async def msg_custom_qty(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    if not raw.isdigit():
        return await m.answer("❌ Faqat son yuboring. Masalan: <code>150</code>", reply_markup=kb_back_menu("m:stars"))
    qty = int(raw)
    if qty < 50 or qty > 100000:
        return await m.answer("❌ Chegara: 50..100000", reply_markup=kb_back_menu("m:stars"))
    st = await get_settings(APP.cfg)
    base = money_base(qty, int(st["rate"]), int(st["fee"]))
    await state.update_data(product="stars", qty=qty, base=base, back_to="m:stars")
    await state.set_state(BuyFlow.waiting_username)
    await m.answer(t_order_details("stars", qty, base), reply_markup=kb_username_step("m:stars"))

@dp.callback_query(F.data.startswith("pr:m:"))
async def cb_premium_pick(c: CallbackQuery, state: FSMContext):
    await c.answer()
    months = int(c.data.split(":")[-1])
    st = await get_settings(APP.cfg)
    price_map = {3: int(st["prem3"]), 6: int(st["prem6"]), 12: int(st["prem12"])}
    base = int(price_map.get(months) or 0)
    if base <= 0:
        return await c.answer("Bu paket hozircha sozlanmagan.", show_alert=True)

    await state.update_data(product="premium", qty=months, base=base, back_to="m:premium")
    await state.set_state(BuyFlow.waiting_username)
    await safe_edit(c.message, t_order_details("premium", months, base), kb_username_step("m:premium"))

@dp.callback_query(F.data == "buy:me")
async def cb_buy_me(c: CallbackQuery, state: FSMContext):
    await c.answer()
    u = (c.from_user.username or "").strip()
    if not u:
        return await c.answer("Sizda username yo'q. Telegram'da username qo'ying.", show_alert=True)

    data = await state.get_data()
    product = str(data.get("product") or "stars")
    qty = int(data.get("qty") or 0)
    base = int(data.get("base") or 0)
    back_to = str(data.get("back_to") or "m:home")

    if qty <= 0 or base <= 0:
        return await c.answer("Avval mahsulotni tanlang.", show_alert=True)

    if product == "premium":
        ok, dbg = await APP.frag.validate_premium_username(u, qty)
    else:
        ok, dbg = await APP.frag.validate_stars_username(u)

    logger.info("[FRAGMENT] validate product=%s @%s -> ok=%s dbg=%s", product, u, ok, dbg)
    if not ok:
        return await c.answer("Username Fragment'da topilmadi. Qayta urinib ko'ring.", show_alert=True)

    await state.update_data(target=u)
    await safe_edit(c.message, t_pay_type(product, qty, u, base), kb_pay_type(back_to))

@dp.message(BuyFlow.waiting_username)
async def msg_username(m: Message, state: FSMContext):
    data = await state.get_data()
    product = str(data.get("product") or "stars")
    qty = int(data.get("qty") or 0)
    base = int(data.get("base") or 0)
    back_to = str(data.get("back_to") or "m:home")

    if qty <= 0 or base <= 0:
        await state.clear()
        return await m.answer("❌ Avval mahsulotni tanlang.", reply_markup=kb_back_menu(back_to))

    u = normalize_username(m.text or "")
    if not u:
        return await m.answer("❌ Username noto'g'ri. Masalan: <code>@username</code>", reply_markup=kb_username_step(back_to))

    if product == "premium":
        ok, dbg = await APP.frag.validate_premium_username(u, qty)
    else:
        ok, dbg = await APP.frag.validate_stars_username(u)

    logger.info("[FRAGMENT] validate product=%s @%s -> ok=%s dbg=%s", product, u, ok, dbg)
    if not ok:
        return await m.answer("❌ Bunday @username topilmadi. Qayta tekshirib yuboring.", reply_markup=kb_username_step(back_to))

    await state.update_data(target=u)
    await m.answer(t_pay_type(product, qty, u, base), reply_markup=kb_pay_type(back_to))

@dp.callback_query(F.data == "pay:card")
async def cb_pay_card(c: CallbackQuery, state: FSMContext):
    await c.answer()
    async with _user_lock(c.from_user.id):
        st = await get_settings(APP.cfg)
        if _check_sales_or_alert(st, c) is None:
            return

        data = await state.get_data()
        product = str(data.get("product") or "stars")
        qty = int(data.get("qty") or 0)
        base = int(data.get("base") or 0)
        target = str(data.get("target") or "")
        back_to = str(data.get("back_to") or "m:home")

        if qty <= 0 or base <= 0 or not target:
            return await c.answer("Xatolik. Qaytadan urinib ko'ring.", show_alert=True)

        card = str(st["card"] or "").strip()
        name = str(st["name"] or "").strip()
        if not card or not name:
            return await c.answer("Admin karta ma'lumotlarini qo'ymagan.", show_alert=True)

        ttl_min = int(st["ttl"])
        expires = iso(now_utc() + timedelta(minutes=ttl_min))
        pay_amount, delta = await generate_unique_amount(APP.cfg, base)

        # Default: manual transfer mode (confirmed by UserBot / CardXabar tracking)
        payment_id = "manual_" + secrets.token_hex(6)

        # Optional: try Gold API if enabled and not forced to manual
        force_manual = os.getenv("PAYMENT_MODE", "").strip().lower() in {"manual", "card", "userbot"}             or os.getenv("FORCE_MANUAL_PAYMENT", "").strip().lower() in {"1", "true", "yes"}
        use_gold = (APP.gold is not None) and (not force_manual)

        if use_gold:
            try:
                pid = await APP.gold.create(pay_amount)
                if pid:
                    payment_id = pid
                else:
                    logger.warning("[GOLD] create returned empty payment_id; fallback to manual")
            except Exception as e:
                logger.warning("[GOLD] create failed; fallback to manual. err=%s", e)

        order_id = await db_create_order(
            APP.cfg.db_path,
            user_id=c.from_user.id,
            buyer_username=(c.from_user.username or ""),
            target_username=target,
            product=product,
            qty=qty,
            base_amount=base,
            pay_amount=pay_amount,
            rand_delta=delta,
            payment_id=payment_id,
            expires_at=expires
        )
        await state.clear()
        text = t_wait_payment(product, qty, target, pay_amount, card, ttl_min, name)
        await safe_edit(c.message, text, kb_order_view(order_id))

@dp.callback_query(F.data == "m:orders")
async def cb_orders(c: CallbackQuery):
    await c.answer()
    per_page = 8
    total = await db_count_orders_by_user(APP.cfg.db_path, c.from_user.id)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = 0
    orders = await db_list_orders_by_user(APP.cfg.db_path, c.from_user.id, per_page, page * per_page)
    text = "🧾 <b>Buyurtmalarim</b>\n────────────────────────────\n"
    if not orders:
        text += "Hali buyurtma yo'q."
    else:
        for o in orders:
            product = str(o.get("product") or "stars")
            qty = int(o.get("qty") or 0)
            label = ("⭐️" if product == "stars" else "🎁")
            tail = ("⭐️" if product == "stars" else " oy")
            text += f"• {label} <b>#{o['id']}</b> · {qty}{tail} · {fmt_som(int(o['pay_amount']))} so'm · pay={h(o['pay_status'])} · del={h(o['delivery_status'])}\n"
    text += "\nOrderni ochish uchun pastdan tanlang:"
    await safe_edit(c.message, text, kb_orders_list(page, total_pages, orders))

@dp.callback_query(F.data.startswith("ord:page:"))
async def cb_orders_page(c: CallbackQuery):
    await c.answer()
    per_page = 8
    page = int(c.data.split(":")[-1])
    total = await db_count_orders_by_user(APP.cfg.db_path, c.from_user.id)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = clamp_int(page, 0, total_pages - 1)
    orders = await db_list_orders_by_user(APP.cfg.db_path, c.from_user.id, per_page, page * per_page)
    text = "🧾 <b>Buyurtmalarim</b>\n────────────────────────────\n"
    if not orders:
        text += "Hali buyurtma yo'q."
    else:
        for o in orders:
            product = str(o.get("product") or "stars")
            qty = int(o.get("qty") or 0)
            label = ("⭐️" if product == "stars" else "🎁")
            tail = ("⭐️" if product == "stars" else " oy")
            text += f"• {label} <b>#{o['id']}</b> · {qty}{tail} · {fmt_som(int(o['pay_amount']))} so'm · pay={h(o['pay_status'])} · del={h(o['delivery_status'])}\n"
    text += "\nOrderni ochish uchun pastdan tanlang:"
    await safe_edit(c.message, text, kb_orders_list(page, total_pages, orders))

@dp.callback_query(F.data.startswith("ord:view:"))
async def cb_order_view(c: CallbackQuery):
    await c.answer()
    oid = int(c.data.split(":")[-1])
    o = await db_get_order(APP.cfg.db_path, oid)
    if not o or int(o["user_id"]) != c.from_user.id:
        return await c.answer("Topilmadi.", show_alert=True)
    text = await t_order_view(APP.cfg, o)
    await safe_edit(c.message, text, kb_order_view(oid))

@dp.callback_query(F.data.startswith("ord:refresh:"))
async def cb_order_refresh(c: CallbackQuery):
    await c.answer()
    oid = int(c.data.split(":")[-1])
    o = await db_get_order(APP.cfg.db_path, oid)
    if not o or int(o["user_id"]) != c.from_user.id:
        return await c.answer("Topilmadi.", show_alert=True)
    text = await t_order_view(APP.cfg, o)
    await safe_edit(c.message, text, kb_order_view(oid))


# ===================== Admin Panel (Inline) =====================# ===================== Admin Panel (Inline) =====================
def require_admin(c: CallbackQuery) -> bool:
    if not APP.is_admin(c.from_user.id):
        return False
    return True

@dp.callback_query(F.data == "adm:home")
async def cb_adm_home(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    await state.clear()
    await safe_edit(c.message, "🛠 <b>Admin panel</b>\n────────────────────────────\nTanlang:", kb_admin_home())

@dp.callback_query(F.data == "adm:stats")
async def cb_adm_stats(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    st = await db_admin_stats(APP.cfg.db_path)
    text = (
        "📊 <b>Statistika</b>\n"
        "────────────────────────────\n"
        f"👥 Users: <b>{st['users']}</b>\n"
        f"🧾 Orders: <b>{st['orders']}</b>\n"
        f"⏳ Pending: <b>{st['pending']}</b>\n"
        f"✅ Paid: <b>{st['paid']}</b>\n"
        f"🚚 Delivered: <b>{st['delivered']}</b>\n"
        f"⚠️ Failed delivery: <b>{st['failed_delivery']}</b>\n"
        f"💰 Revenue: <b>{fmt_som(st['revenue'])}</b> so'm\n"
    )
    await safe_edit(c.message, text, kb_admin_home())

def admin_filter(filter_key: str) -> Tuple[str, Tuple[Any, ...], str]:
    fk = (filter_key or "all").lower()
    if fk == "pending":
        return ("WHERE pay_status='pending'", tuple(), "pending")
    if fk == "paid":
        return ("WHERE pay_status='paid'", tuple(), "paid")
    if fk == "need_delivery":
        return ("WHERE pay_status='paid' AND delivery_status IN ('pending','failed')", tuple(), "need_delivery")
    if fk == "failed":
        return ("WHERE delivery_status='failed'", tuple(), "failed")
    if fk == "delivered":
        return ("WHERE delivery_status='success'", tuple(), "delivered")
    return ("", tuple(), "all")

@dp.callback_query(F.data.startswith("adm:orders:"))
async def cb_adm_orders(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    _, _, fk, page_str = c.data.split(":")
    page = int(page_str)
    where, params, title = admin_filter(fk)
    per_page = 8
    total = await db_admin_count_orders(APP.cfg.db_path, where, params)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = clamp_int(page, 0, total_pages - 1)
    orders = await db_admin_list_orders(APP.cfg.db_path, where, params, per_page, page * per_page)
    text = f"📦 <b>Orderlar</b> ({h(title)})\n────────────────────────────\n"
    if not orders:
        text += "Order yo'q."
    else:
        for o in orders:
            text += f"• <b>#{o['id']}</b> · {o['qty']}⭐ · {fmt_som(int(o['pay_amount']))} so'm · pay={h(o['pay_status'])} · del={h(o['delivery_status'])}\n"
    text += "\nPastdan tanlang:"
    await safe_edit(c.message, text, kb_admin_orders(fk, page, total_pages, orders))

@dp.callback_query(F.data.startswith("adm:order:"))
async def cb_adm_order(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    oid = int(c.data.split(":")[-1])
    o = await db_get_order(APP.cfg.db_path, oid)
    if not o:
        return await c.answer("Order topilmadi", show_alert=True)
    text = (
        "🛠 <b>Admin: Order detail</b>\n"
        "────────────────────────────\n"
        f"🧾 Order: <b>#{o['id']}</b>\n"
        f"👤 UserID: <code>{o['user_id']}</code>\n"
        f"👤 Buyer: @{h(o.get('buyer_username') or '-')}\n"
        f"🎯 Target: <code>@{h(o.get('target_username') or '-')}</code>\n"
        f"⭐ Qty: <b>{o['qty']}</b>\n"
        f"💰 Base: <b>{fmt_som(int(o['base_amount']))}</b> so'm\n"
        f"🎲 Delta: <b>{int(o['rand_delta'])}</b>\n"
        f"💰 Pay: <b>{fmt_som(int(o['pay_amount']))}</b> so'm\n"
        f"🏷 Pay status: <b>{h(o['pay_status'])}</b>\n"
        f"🆔 PaymentID: <code>{h(o['payment_id'])}</code>\n"
        f"🚚 Delivery: <b>{h(o['delivery_status'])}</b>\n"
        f"🔗 TX: <code>{h(o.get('delivery_tx') or '')}</code>\n"
        f"⚠️ Err: <code>{h(o.get('delivery_error') or '')}</code>\n"
        f"🕒 Created: {h(o.get('created_at'))}\n"
        f"🕒 Paid: {h(o.get('pay_paid_at') or '')}\n"
        f"🕒 Expires: {h(o.get('expires_at') or '')}\n"
        f"🕒 Updated: {h(o.get('updated_at'))}\n"
    )
    await safe_edit(c.message, text, kb_admin_order(oid))

@dp.callback_query(F.data.startswith("adm:retry:"))
async def cb_adm_retry(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    oid = int(c.data.split(":")[-1])
    o = await db_get_order(APP.cfg.db_path, oid)
    if not o:
        return await c.answer("Order topilmadi", show_alert=True)
    if o["pay_status"] != "paid":
        return await c.answer("Order paid emas", show_alert=True)
    if not APP.frag.enabled:
        return await c.answer("Fragment yoqilmagan", show_alert=True)
    ok, tx, err = await APP.frag.buy_stars(str(o["target_username"]), int(o["qty"]))
    if ok:
        await db_update_delivery(APP.cfg.db_path, oid, "success", tx, None)
        await c.answer("Delivered ✅", show_alert=True)
    else:
        await db_update_delivery(APP.cfg.db_path, oid, "failed", None, err)
        await c.answer("Failed ⚠️", show_alert=True)
    # refresh view
    o2 = await db_get_order(APP.cfg.db_path, oid)
    if o2:
        text = (
            "🛠 <b>Admin: Order detail</b>\n"
            "────────────────────────────\n"
            f"🧾 Order: <b>#{o2['id']}</b>\n"
            f"👤 UserID: <code>{o2['user_id']}</code>\n"
            f"👤 Buyer: @{h(o2.get('buyer_username') or '-')}\n"
            f"🎯 Target: <code>@{h(o2.get('target_username') or '-')}</code>\n"
            f"⭐ Qty: <b>{o2['qty']}</b>\n"
            f"💰 Pay: <b>{fmt_som(int(o2['pay_amount']))}</b> so'm\n"
            f"🏷 Pay status: <b>{h(o2['pay_status'])}</b>\n"
            f"🚚 Delivery: <b>{h(o2['delivery_status'])}</b>\n"
            f"🔗 TX: <code>{h(o2.get('delivery_tx') or '')}</code>\n"
            f"⚠️ Err: <code>{h(o2.get('delivery_error') or '')}</code>\n"
        )
        await safe_edit(c.message, text, kb_admin_order(oid))

@dp.callback_query(F.data.startswith("adm:markpaid:"))
async def cb_adm_markpaid(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    oid = int(c.data.split(":")[-1])
    await db_update_payment(APP.cfg.db_path, oid, "paid", iso(now_utc()))
    await c.answer("OK", show_alert=True)

@dp.callback_query(F.data.startswith("adm:markdel:"))
async def cb_adm_markdel(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    oid = int(c.data.split(":")[-1])
    await db_update_delivery(APP.cfg.db_path, oid, "success", "manual", None)
    await c.answer("OK", show_alert=True)

@dp.callback_query(F.data == "adm:price")
async def cb_adm_price(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    await state.clear()
    st = await get_settings(APP.cfg)
    text = (
        "💰 <b>Narx & Random</b>\n"
        "────────────────────────────\n"
        f"UZS/star: <b>{fmt_som(int(st['rate']))}</b>\n"
        f"Fee: <b>{fmt_som(int(st['fee']))}</b>\n"
        f"Random: <b>{int(st['rmin'])}..{int(st['rmax'])}</b>\n"
        f"Packs: <code>{h(','.join(map(str, st['packs'])))}</code>\n"
        f"Premium 3m: <b>{fmt_som(int(st['prem3']))}</b>\n"
        f"Premium 6m: <b>{fmt_som(int(st['prem6']))}</b>\n"
        f"Premium 12m: <b>{fmt_som(int(st['prem12']))}</b>\n"
        "Tanlang:"
    )
    await safe_edit(c.message, text, kb_admin_price())

@dp.callback_query(F.data == "adm:card")
async def cb_adm_card(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    await state.clear()
    st = await get_settings(APP.cfg)
    text = (
        "💳 <b>Karta sozlamasi</b>\n"
        "────────────────────────────\n"
        f"Karta: <code>{h(st['card'])}</code>\n"
        f"Egasi: <b>{h(st['name'])}</b>\n"
        "Tanlang:"
    )
    await safe_edit(c.message, text, kb_admin_card())

@dp.callback_query(F.data == "adm:toggle")
async def cb_adm_toggle(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    st = await get_settings(APP.cfg)
    text = (
        "⚙️ <b>Bot ON/OFF</b>\n"
        "────────────────────────────\n"
        f"Bot: <b>{'ON' if int(st['bot_on'])==1 else 'OFF'}</b>\n"
        f"Sotuv: <b>{'ON' if int(st['sales_on'])==1 else 'OFF'}</b>\n"
        "Toggle qiling:"
    )
    await safe_edit(c.message, text, kb_admin_toggle(int(st["bot_on"]), int(st["sales_on"])))

@dp.callback_query(F.data == "adm:toggle:bot")
async def cb_adm_toggle_bot(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    cur = safe_int(await db_get_cfg(APP.cfg.db_path, "BOT_ENABLED"), 1)
    newv = 0 if cur == 1 else 1
    await db_set_cfg(APP.cfg.db_path, "BOT_ENABLED", str(newv))
    st = await get_settings(APP.cfg)
    await safe_edit(c.message, "✅ Saqlandi.", kb_admin_toggle(int(st["bot_on"]), int(st["sales_on"])))

@dp.callback_query(F.data == "adm:toggle:sales")
async def cb_adm_toggle_sales(c: CallbackQuery):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    cur = safe_int(await db_get_cfg(APP.cfg.db_path, "SALES_ENABLED"), 1)
    newv = 0 if cur == 1 else 1
    await db_set_cfg(APP.cfg.db_path, "SALES_ENABLED", str(newv))
    st = await get_settings(APP.cfg)
    await safe_edit(c.message, "✅ Saqlandi.", kb_admin_toggle(int(st["bot_on"]), int(st["sales_on"])))

# Admin set value flow
async def admin_ask_value(c: CallbackQuery, state: FSMContext, key: str, prompt: str):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    await state.set_state(AdminFlow.waiting_value)
    await state.update_data(set_key=key)
    await safe_edit(c.message, prompt, kb_back_menu('adm:home'))

@dp.callback_query(F.data.startswith("adm:set:"))
async def cb_adm_set_router(c: CallbackQuery, state: FSMContext):
    action = c.data.split(":")[-1]
    if action == "rate":
        return await admin_ask_value(c, state, "UZS_PER_STAR", "💰 Yangi UZS/star kiriting. Masalan: <code>195</code>")
    if action == "fee":
        return await admin_ask_value(c, state, "UZS_FIXED_FEE", "➕ Yangi Fee (UZS) kiriting. Masalan: <code>0</code>")
    if action == "rmin":
        return await admin_ask_value(c, state, "RAND_MIN", "🎲 Random MIN kiriting. Masalan: <code>1</code>")
    if action == "rmax":
        return await admin_ask_value(c, state, "RAND_MAX", "🎲 Random MAX kiriting. Masalan: <code>99</code>")
    if action == "packs":
        return await admin_ask_value(c, state, "PACKS", "⭐ Packs (vergul bilan). Masalan: <code>50,100,500,1000</code>")
    if action == "prem3":
        return await admin_ask_value(c, state, "UZS_PREMIUM_3M", "🎁 Premium 3 oy narxi (so\'m). Masalan: <code>150000</code>")
    if action == "prem6":
        return await admin_ask_value(c, state, "UZS_PREMIUM_6M", "🎁 Premium 6 oy narxi (so\'m). Masalan: <code>250000</code>")
    if action == "prem12":
        return await admin_ask_value(c, state, "UZS_PREMIUM_12M", "🎁 Premium 12 oy narxi (so\'m). Masalan: <code>400000</code>")
    if action == "card":
        return await admin_ask_value(c, state, "PAY_CARD", "💳 Karta raqamini yuboring. Masalan: <code>5614....</code>")
    if action == "name":
        return await admin_ask_value(c, state, "PAY_NAME", "👤 Karta egasi ismini yuboring. Masalan: <code>ALI VALI</code>")

@dp.message(AdminFlow.waiting_value)
async def msg_adm_value(m: Message, state: FSMContext):
    if not APP.is_admin(m.from_user.id):
        return
    data = await state.get_data()
    key = str(data.get("set_key") or "")
    val = (m.text or "").strip()
    if key in ("UZS_PER_STAR", "UZS_FIXED_FEE", "RAND_MIN", "RAND_MAX", "ORDER_TTL_MINUTES", "CHECK_INTERVAL_SEC", "BROADCAST_BATCH"):
        if not re.fullmatch(r"\d+", val):
            return await m.answer("❌ Faqat son yuboring.", reply_markup=kb_back_menu('adm:home'))
    if key == "PACKS":
        packs = parse_int_list(val)
        if not packs:
            return await m.answer("❌ Noto'g'ri format.", reply_markup=kb_back_menu('adm:home'))
        val = ",".join(map(str, packs))
    if key == "PAY_CARD":
        digits = re.sub(r"\D", "", val)
        if len(digits) < 12:
            return await m.answer("❌ Karta noto'g'ri.", reply_markup=kb_back_menu('adm:home'))
        val = digits
    await db_set_cfg(APP.cfg.db_path, key, val)
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=kb_admin_home())

# Broadcast
@dp.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not require_admin(c):
        return await c.answer("No access", show_alert=True)
    await state.set_state(AdminFlow.waiting_broadcast_message)
    await safe_edit(
        c.message,
        "📣 <b>Broadcast</b>\nTarqatmoqchi bo'lgan xabaringizni yuboring.\n(Bot copy_message bilan yuboradi.)",
        kb_back_menu('adm:home')
    )

@dp.message(AdminFlow.waiting_broadcast_message)
async def msg_broadcast(m: Message, state: FSMContext):
    if not APP.is_admin(m.from_user.id):
        return
    bc_id = await db_create_broadcast(APP.cfg.db_path, m.from_user.id, m.chat.id, m.message_id)
    await state.clear()
    await m.answer(f"✅ Broadcast queued. ID: <b>{bc_id}</b>", reply_markup=kb_admin_home())

# ===================== Main =====================
async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
