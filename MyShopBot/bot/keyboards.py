from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.config import GAME_KEYS, PRODUCTS

BTN_REPLY_MENU = "📋 Меню"


def kb_reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_REPLY_MENU)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="NEXIVORA",
    )


def kb_back() -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton("⬅️ Назад", callback_data="n|b")]]


def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 Купить", callback_data="g|buy")],
            [InlineKeyboardButton("📋 Задания", callback_data="g|tasks")],
            [InlineKeyboardButton("📌 Меню", callback_data="g|menu")],
        ]
    )


def kb_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 Купить", callback_data="g|buy")],
            [InlineKeyboardButton("📦 Заказы", callback_data="g|orders")],
            [InlineKeyboardButton("💰 Пополнить баланс", callback_data="g|topup")],
            [InlineKeyboardButton("📋 Задания", callback_data="g|tasks")],
            [InlineKeyboardButton("🛠 Техподдержка", callback_data="g|support")],
        ]
    )


def kb_tasks() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Подписка", callback_data="g|tsub")],
            [InlineKeyboardButton("🤝 Партнёрка", callback_data="g|tpart")],
            [InlineKeyboardButton("🎁 Промокод", callback_data="g|tpromo")],
            *kb_back(),
        ]
    )


def kb_task_subscribe(subscribe_url: str, done: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not done:
        if subscribe_url:
            rows.append([InlineKeyboardButton("📢 Подписаться", url=subscribe_url)])
        rows.append([InlineKeyboardButton("✅ Проверить подписку", callback_data="t|chk")])
    rows.extend(kb_back())
    return InlineKeyboardMarkup(rows)


def kb_partner() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Статистика", callback_data="r|stats")],
            *kb_back(),
        ]
    )


def kb_buy() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⭐ Brawl Stars", callback_data="g|bs")],
            [InlineKeyboardButton("🧱 Roblox", callback_data="g|roblox")],
            [InlineKeyboardButton("🎯 Fortnite", callback_data="g|fortnite")],
            [InlineKeyboardButton("🤖 Нейросети", callback_data="g|ai")],
            *kb_back(),
        ]
    )


def kb_game_products(game: str) -> InlineKeyboardMarkup:
    rows = []
    for key in GAME_KEYS.get(game, ()):
        p = PRODUCTS[key]
        if p.price_usd > 0:
            label = f"🛍 {p.title} — {p.price_usd:g}$"
        else:
            label = f"🛍 {p.title}"
        rows.append([InlineKeyboardButton(label, callback_data=f"c|{key}")])
    rows.extend(kb_back())
    return InlineKeyboardMarkup(rows)


def kb_pay_balance() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💵 Оплатить балансом", callback_data="y|u")],
            *kb_back(),
        ]
    )


def kb_simple_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(kb_back())


def kb_topup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Crypto Bot", callback_data="p|go")],
            [InlineKeyboardButton("⭐ Telegram Stars", callback_data="p|stars")],
            *kb_back(),
        ]
    )


def kb_topup_invoice(pay_url: str, internal_topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Оплатить в Crypto Bot", url=pay_url)],
            [InlineKeyboardButton("✅ Я оплатил — проверить", callback_data=f"p|chk|{internal_topup_id}")],
            *kb_back(),
        ]
    )


def kb_topup_check_only(internal_topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Я оплатил — проверить", callback_data=f"p|chk|{internal_topup_id}")],
            *kb_back(),
        ]
    )


def kb_admin_order(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Отметить выполненным", callback_data=f"a|ok|{order_id}")]]
    )
