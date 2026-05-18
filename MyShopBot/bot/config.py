import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
if not (os.getenv("BOT_TOKEN") or "").strip():
    load_dotenv(BASE_DIR / ".env.txt", override=True)
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"
DB_PATH = DATA_DIR / "nexivora.db"
WELCOME_IMAGE = ASSETS_DIR / "welcome.jpg"
MENU_IMAGE = ASSETS_DIR / "menu.jpg"
PUBLIC_ID_START = 100001


def _parse_admin_ids(raw: str | None) -> List[int]:
    if not raw:
        return []
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS"))
CHANNEL_USERNAME = (os.getenv("CHANNEL_USERNAME") or "").strip() or None
SUPPORT_CONTACT = (os.getenv("SUPPORT_CONTACT") or "@your_contact").strip()
CHANNEL_URL = (os.getenv("CHANNEL_URL") or "").strip() or (
    f"https://t.me/{CHANNEL_USERNAME[1:]}" if CHANNEL_USERNAME and CHANNEL_USERNAME.startswith("@") else ""
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


TG_CONNECT_TIMEOUT = _env_float("TG_CONNECT_TIMEOUT", 45.0)
TG_READ_TIMEOUT = _env_float("TG_READ_TIMEOUT", 45.0)
TG_WRITE_TIMEOUT = _env_float("TG_WRITE_TIMEOUT", 45.0)
TG_POOL_TIMEOUT = _env_float("TG_POOL_TIMEOUT", 15.0)
STICKER_PACK_NAME = (os.getenv("STICKER_PACK_NAME") or "").strip()
CRYPTO_PAY_API_TOKEN = (os.getenv("CRYPTO_PAY_API_TOKEN") or "").strip()
CRYPTO_PAY_TESTNET = os.getenv("CRYPTO_PAY_TESTNET", "0").strip().lower() in ("1", "true", "yes")
CRYPTO_PAY_ASSET = (os.getenv("CRYPTO_PAY_ASSET") or "USDT").strip().upper()
TOPUP_MIN_USD = _env_float("TOPUP_MIN_USD", 1.0)
TOPUP_MAX_USD = _env_float("TOPUP_MAX_USD", 25000.0)
TELEGRAM_PROXY = (
    (os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip() or None
)

TASK_CHANNEL_REWARD_USD = 0.05
REFERRAL_FIRST_PCT = 0.10
REFERRAL_REPEAT_PCT = 0.03
STAR_USD_RATE = 0.010
STAR_MIN = 200
STAR_MAX = 1_000_000
ROBUX_RATE_USD = 0.014
ROBUX_PER_UNIT = 1.19

# Промокоды: код (lower) -> бонус в $
PROMO_CODES: Dict[str, float] = {}


@dataclass(frozen=True)
class Product:
    key: str
    title: str
    price_usd: float
    checkout: str  # brawl_email | roblox | contact_only
    description: str = ""


PRODUCTS: Dict[str, Product] = {
    "brawl_pass": Product(
        "brawl_pass",
        "Brawl Pass",
        12.19,  # тест: вернуть 12.19 в bot/config.py → PRODUCTS["brawl_pass"].price_usd
        "brawl_email",
        "🎫 Сезонный пропуск Brawl Stars на текущий сезон.",
    ),
    "brawl_pass_plus": Product(
        "brawl_pass_plus",
        "Brawl Pass Plus",
        17.59,
        "brawl_email",
        "🎫 Brawl Pass + дополнительные бонусы сезона.",
    ),
    "pro_pass": Product(
        "pro_pass",
        "Pro Pass",
        29.79,
        "brawl_email",
        "👑 Расширенный Pro Pass с максимумом наград.",
    ),
    "brawl_upgrade": Product(
        "brawl_upgrade",
        "Улучшение Pass до Pass plus",
        6.79,
        "brawl_email",
        "⬆️ Улучшение текущего пропуска.",
    ),
    "roblox_robux": Product(
        "roblox_robux",
        "Robux",
        0.0,
        "roblox",
        "💎 Покупка Robux на ваш аккаунт Roblox.",
    ),
    "fortnite_squad": Product(
        "fortnite_squad",
        "Отряд для Epic Games Store",
        5.49,
        "contact_only",
        "🎯 Доступ к отряду Fortnite через Epic Games Store.",
    ),
    "cursor_ai": Product(
        "cursor_ai",
        "Подписка Cursor AI",
        33.99,
        "contact_only",
        "🤖 Подписка Cursor AI на 1 месяц.",
    ),
    "chatgpt": Product(
        "chatgpt",
        "Подписка Chat GPT",
        24.99,
        "contact_only",
        "💬 Подписка ChatGPT на 1 месяц.",
    ),
}

GAME_KEYS = {
    "bs": ("brawl_pass", "brawl_pass_plus", "pro_pass", "brawl_upgrade"),
    "roblox": ("roblox_robux",),
    "fortnite": ("fortnite_squad",),
    "ai": ("cursor_ai", "chatgpt"),
}


def robux_price_usd(robux_amount: float) -> float:
    return round(robux_amount * ROBUX_RATE_USD / ROBUX_PER_UNIT, 2)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
