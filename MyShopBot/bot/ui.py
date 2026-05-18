import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from telegram import InputFile, InputMediaPhoto, Message, Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import stickers
from bot import texts as tx
from bot.config import CHANNEL_URL, MENU_IMAGE, PRODUCTS, SUPPORT_CONTACT, TOPUP_MAX_USD, TOPUP_MIN_USD, WELCOME_IMAGE
from bot.db import count_orders_total, ensure_user, list_referrals, product_title

log = logging.getLogger("nexivora.ui")


def _photo_input(path: Path) -> InputFile:
    return InputFile(io.BytesIO(path.read_bytes()), filename=path.name)


def _image_for(screen: str) -> Optional[Path]:
    if screen == "start" and WELCOME_IMAGE.exists():
        return WELCOME_IMAGE
    if screen == "menu" and MENU_IMAGE.exists():
        return MENU_IMAGE
    return None


def menu_body(user, row: dict, orders_count: int) -> str:
    uname = f"@{user.username}" if user.username else "— (без username)"
    bal = float(row.get("balance_usd") or 0)
    today = datetime.now().strftime("%d.%m.%Y")
    public_id = row.get("public_id") or "—"
    return (
        f"{tx.MENU_HEADER}\n\n"
        f"🆔 ID: {public_id}\n\n"
        f"👤 Username:\n{uname}\n\n"
        f"💰 Баланс:\n{bal:.2f}$\n\n"
        f"📦 Заказов:\n{orders_count}\n\n"
        f"📅 Дата:\n{today}"
    )


def referral_link(bot_username: str, user_id: int) -> str:
    name = (bot_username or "nexivora_bot").lstrip("@")
    return f"https://t.me/{name}?start=ref{user_id}"


async def send_menu_photo(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    caption: str,
    reply_markup,
) -> Message:
    img = _image_for("menu")
    if img:
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=_photo_input(img),
            caption=caption,
            reply_markup=reply_markup,
        )
    return await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)


async def _show_menu(
    update_or_query: Union[Update, object],
    context: ContextTypes.DEFAULT_TYPE,
    *,
    from_callback: bool = False,
) -> None:
    if from_callback:
        query = update_or_query
        user = query.from_user
        chat_id = query.message.chat_id
    else:
        update = update_or_query
        user = update.effective_user
        chat_id = update.effective_chat.id

    assert user
    row = await ensure_user(user.id, user.username or "")
    orders_count = await count_orders_total(user.id)
    caption = menu_body(user, row, orders_count)
    markup = kb.kb_menu()
    img = _image_for("menu")

    if from_callback:
        query = update_or_query
        msg = query.message
        if img and msg.photo:
            media = InputMediaPhoto(media=_photo_input(img), caption=caption)
            await query.edit_message_media(media=media, reply_markup=markup)
        elif img:
            await send_menu_photo(chat_id, context, caption=caption, reply_markup=markup)
            try:
                await msg.delete()
            except Exception:
                pass
        else:
            await query.edit_message_text(text=caption, reply_markup=markup)
    else:
        await send_menu_photo(chat_id, context, caption=caption, reply_markup=markup)

    await stickers.send_scene(context, chat_id, "menu")


async def send_start_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user
    await ensure_user(user.id, user.username or "")
    markup = kb.kb_start()
    img = _image_for("start")
    chat = update.effective_chat
    assert chat
    if img:
        await update.effective_message.reply_photo(
            photo=_photo_input(img),
            caption=tx.WELCOME,
            reply_markup=markup,
        )
    else:
        await update.effective_message.reply_text(tx.WELCOME, reply_markup=markup)
    await stickers.send_scene(context, chat.id, "welcome")
    await update.effective_message.reply_text(tx.REPLY_MENU_HINT, reply_markup=kb.kb_reply_menu())


async def send_menu_from_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_menu(update, context, from_callback=False)


async def edit_to_screen(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    screen: str,
    text: str,
    reply_markup,
    sticker_scene: Optional[str] = None,
) -> None:
    msg = query.message
    image = _image_for(screen)
    if image:
        media = InputMediaPhoto(media=_photo_input(image), caption=text)
        await query.edit_message_media(media=media, reply_markup=reply_markup)
    elif msg.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    if sticker_scene:
        await stickers.send_scene(context, msg.chat_id, sticker_scene)


async def render_menu(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_menu(query, context, from_callback=True)


async def render_tasks(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await edit_to_screen(
        query, context, screen="tasks", text=tx.TASKS, reply_markup=kb.kb_tasks(), sticker_scene="tasks"
    )


async def render_task_subscribe(query, context: ContextTypes.DEFAULT_TYPE, *, done: bool) -> None:
    url = CHANNEL_URL or "https://t.me/telegram"
    await edit_to_screen(
        query,
        context,
        screen="tsub",
        text=tx.TASK_SUBSCRIBE if not done else tx.TASK_SUBSCRIBE_DONE,
        reply_markup=kb.kb_task_subscribe(url, done),
        sticker_scene="tasks",
    )


async def render_partner(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_username = context.bot_data.get("bot_username") or ""
    link = referral_link(bot_username, query.from_user.id)
    text = tx.PARTNER_HEADER.format(link=link)
    await edit_to_screen(
        query, context, screen="tpart", text=text, reply_markup=kb.kb_partner(), sticker_scene="partner"
    )


async def render_partner_stats(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    refs = await list_referrals(query.from_user.id)
    lines = [tx.PARTNER_STATS_HEADER]
    if not refs:
        lines.append("\n👥 Пока нет приглашённых рефералов.\n\nДелитесь ссылкой из раздела «Партнёрка»!")
    else:
        lines.append(f"\n👥 Всего рефералов: {len(refs)}\n")
        for i, r in enumerate(refs, 1):
            uname = f"@{r['username']}" if r.get("username") else f"id:{r['user_id']}"
            lines.append(f"{i}. {uname}\n")
    await edit_to_screen(
        query,
        context,
        screen="tstats",
        text="".join(lines),
        reply_markup=kb.kb_partner(),
        sticker_scene="partner",
    )


async def render_buy(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await edit_to_screen(
        query, context, screen="buy", text=tx.BUY_GAMES, reply_markup=kb.kb_buy(), sticker_scene="buy"
    )


async def render_game(query, context: ContextTypes.DEFAULT_TYPE, game: str, header: str, scene: str) -> None:
    await edit_to_screen(
        query,
        context,
        screen=game,
        text=header,
        reply_markup=kb.kb_game_products(game),
        sticker_scene=scene,
    )


async def render_orders(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.db import list_orders

    orders = await list_orders(query.from_user.id)
    lines = [tx.ORDERS_HEADER]
    if not orders:
        lines.append("\nПока заказов нет.")
    else:
        for i, o in enumerate(orders, 1):
            title = product_title(o["product_key"])
            st = tx.STATUS_LABEL.get(o["status"], o["status"])
            lines.append(f"\n{i}. {title}\nСтатус: {st}")
    await edit_to_screen(
        query,
        context,
        screen="orders",
        text="".join(lines),
        reply_markup=kb.kb_simple_back(),
        sticker_scene="orders",
    )


async def render_topup(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await edit_to_screen(
        query,
        context,
        screen="topup",
        text=tx.TOPUP_MENU,
        reply_markup=kb.kb_topup(),
        sticker_scene="topup",
    )


async def render_topup_crypto(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    body = tx.TOPUP_INTRO.format(min_usd=TOPUP_MIN_USD, max_usd=TOPUP_MAX_USD)
    await edit_to_screen(
        query,
        context,
        screen="topup_crypto",
        text=body,
        reply_markup=kb.kb_simple_back(),
        sticker_scene="topup",
    )


async def render_support(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = tx.SUPPORT.format(contact=SUPPORT_CONTACT)
    await edit_to_screen(
        query,
        context,
        screen="support",
        text=text,
        reply_markup=kb.kb_simple_back(),
        sticker_scene="support",
    )
