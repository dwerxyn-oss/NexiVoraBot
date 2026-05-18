import logging
import secrets

from telegram import InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

from bot import db
from bot import keyboards as kb
from bot import stickers
from bot import texts as tx
from bot import ui
from bot.config import (
    ADMIN_IDS,
    CHANNEL_USERNAME,
    CRYPTO_PAY_ASSET,
    PRODUCTS,
    PROMO_CODES,
    REFERRAL_FIRST_PCT,
    REFERRAL_REPEAT_PCT,
    STAR_MAX,
    STAR_MIN,
    STAR_USD_RATE,
    TASK_CHANNEL_REWARD_USD,
    TOPUP_MAX_USD,
    TOPUP_MIN_USD,
    robux_price_usd,
)
from bot.cryptopay import CryptoPayError
from bot.db import (
    add_balance,
    count_user_orders,
    create_order,
    credit_star_topup,
    credit_topup_if_pending,
    ensure_user,
    get_order,
    get_topup_internal,
    insert_crypto_topup,
    insert_star_topup,
    mark_promo_used,
    mark_task_done,
    product_title,
    promo_already_used,
    set_balance,
    set_order_status,
    set_referrer_if_empty,
)
from bot.nav import nav_back, push_nav, reset_nav

log = logging.getLogger("nexivora.callbacks")


def _clear_checkout(ud: dict) -> None:
    for k in (
        "await_input",
        "co_key",
        "co_price",
        "co_email",
        "co_contact",
        "co_extra",
        "co_robux",
    ):
        ud.pop(k, None)


def _user_label(user_id: int, username: str | None) -> str:
    return f"@{username}" if username else f"id:{user_id}"


async def _is_channel_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not CHANNEL_USERNAME:
        return True
    try:
        m = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return m.status in ("member", "administrator", "creator", "restricted")
    except Exception:
        return False


async def _apply_referral_bonus(
    context: ContextTypes.DEFAULT_TYPE,
    buyer_id: int,
    buyer_username: str | None,
    price_usd: float,
    prior_orders: int,
) -> None:
    buyer = await ensure_user(buyer_id, buyer_username)
    referrer_id = buyer.get("referrer_id")
    if not referrer_id:
        return
    is_first = prior_orders == 0
    pct = REFERRAL_FIRST_PCT if is_first else REFERRAL_REPEAT_PCT
    bonus = round(price_usd * pct, 2)
    if bonus <= 0:
        return
    await add_balance(int(referrer_id), bonus)
    who = _user_label(buyer_id, buyer_username)
    try:
        await context.bot.send_message(
            chat_id=int(referrer_id),
            text=tx.REFERRAL_PURCHASE.format(who=who, amount=price_usd, pct=pct * 100, bonus=bonus),
            reply_markup=kb.kb_reply_menu(),
        )
    except Exception:
        pass


async def _notify_admin(context: ContextTypes.DEFAULT_TYPE, order_id: int, row: dict) -> None:
    if not ADMIN_IDS:
        return
    key = row["product_key"]
    lines = [
        "🆕 Новый заказ\n",
        f"ID заказа: #{order_id}",
        f"Пользователь: id:{row['user_id']}",
        f"Товар: {product_title(key)}",
        f"Оплата: {tx.PAYMENT_LABEL.get(row['payment'], row['payment'])}",
        f"Сумма: {float(row['price_usd']):g}$\n",
    ]
    if row.get("email"):
        if key == "roblox_robux":
            lines.append(f"Ник Roblox:\n{row['email']}\n")
        elif key in PRODUCTS and PRODUCTS[key].checkout == "brawl_email":
            lines.append(f"Supercell ID (почта):\n{row['email']}\n")
        else:
            lines.append(f"Данные:\n{row['email']}\n")
    if row.get("tg_contact"):
        lines.append(f"Telegram:\n{row['tg_contact']}\n")
    if row.get("extra"):
        lines.append(f"Дополнительно:\n{row['extra']}\n")
    lines.append("Статус: в работе")
    text = "\n".join(lines)
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=kb.kb_admin_order(order_id),
            )
        except Exception:
            continue


async def _finalize_paid_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q
    ud = context.user_data
    key = ud.get("co_key")
    if not key or key not in PRODUCTS:
        await q.answer("Сессия оформления истекла. Выберите товар снова.", show_alert=True)
        return
    user_id = q.from_user.id
    row = await ensure_user(user_id, q.from_user.username)
    p = PRODUCTS[key]
    price = float(ud.get("co_price") or p.price_usd)
    if float(row["balance_usd"]) < price:
        await q.answer(tx.INSUFFICIENT_BALANCE, show_alert=True)
        return
    prior_orders = await count_user_orders(user_id)
    await set_balance(user_id, float(row["balance_usd"]) - price)
    email = ud.get("co_email") or ""
    contact = ud.get("co_contact") or ""
    extra = ud.get("co_extra") or ""
    oid = await create_order(
        user_id,
        key,
        "balance_usd",
        price,
        email,
        contact,
        extra=extra,
        status="performing",
    )
    _clear_checkout(ud)
    await q.answer()
    await q.message.reply_text(tx.ORDER_CREATED, reply_markup=kb.kb_reply_menu())
    await stickers.send_scene(context, q.message.chat_id, "order")
    order = await get_order(oid)
    if order:
        await _notify_admin(context, oid, order)
        await _apply_referral_bonus(context, user_id, q.from_user.username, price, prior_orders)


async def _handle_referral_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        return
    arg = context.args[0]
    if not arg.startswith("ref"):
        return
    try:
        ref_id = int(arg[3:])
    except ValueError:
        return
    user = update.effective_user
    assert user
    if ref_id == user.id:
        return
    await ensure_user(user.id, user.username or "")
    assigned = await set_referrer_if_empty(user.id, ref_id)
    if not assigned:
        return
    who = _user_label(user.id, user.username)
    try:
        await context.bot.send_message(
            chat_id=ref_id,
            text=tx.REFERRAL_JOINED.format(who=who),
            reply_markup=kb.kb_reply_menu(),
        )
    except Exception:
        pass


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reset_nav(context.user_data, "start")
    _clear_checkout(context.user_data)
    await _handle_referral_start(update, context)
    await ui.send_start_screen(update, context)


async def on_reply_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_checkout(context.user_data)
    ud = context.user_data
    old = ud.get("screen")
    if old and old != "menu":
        ud.setdefault("nav_stack", []).append(old)
    ud["screen"] = "menu"
    await ui.send_menu_from_reply(update, context)


async def topup_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q
    if not context.bot_data.get("cryptopay"):
        await q.answer("Пополнение недоступно", show_alert=True)
        await q.message.reply_text(tx.TOPUP_NO_API, reply_markup=kb.kb_reply_menu())
        return
    await q.answer()
    _clear_checkout(context.user_data)
    context.user_data["await_input"] = "topup_amt"
    await q.message.reply_text(tx.TOPUP_ENTER_AMOUNT, reply_markup=kb.kb_reply_menu())
    await stickers.send_scene(context, q.message.chat_id, "topup")


async def topup_stars_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q
    await q.answer()
    _clear_checkout(context.user_data)
    min_usd = STAR_MIN * STAR_USD_RATE
    context.user_data["await_input"] = "topup_stars"
    await q.message.reply_text(
        tx.TOPUP_STARS_INTRO.format(
            star_rate=STAR_USD_RATE,
            star_min=STAR_MIN,
            min_usd=min_usd,
        ),
        reply_markup=kb.kb_reply_menu(),
    )
    await stickers.send_scene(context, q.message.chat_id, "topup")


async def topup_check(update: Update, context: ContextTypes.DEFAULT_TYPE, internal_id: int) -> None:
    q = update.callback_query
    assert q
    client = context.bot_data.get("cryptopay")
    if not client:
        await q.answer("Нет API", show_alert=True)
        return
    row = await get_topup_internal(internal_id)
    if not row or int(row["user_id"]) != q.from_user.id:
        await q.answer("Счёт не найден.", show_alert=True)
        return
    if row["status"] == "completed":
        await q.answer(tx.TOPUP_ALREADY_DONE, show_alert=True)
        return
    inv_id = int(row["invoice_id"])
    try:
        invoices = await client.get_invoices(invoice_ids=[inv_id])
    except CryptoPayError as e:
        log.warning("getInvoices: %s", e)
        await q.answer("Ошибка Crypto Pay. Попробуйте позже.", show_alert=True)
        return
    paid = any(
        int(inv.get("invoice_id", 0)) == inv_id and str(inv.get("status", "")).lower() == "paid"
        for inv in invoices
    )
    if not paid:
        await q.answer()
        await q.message.reply_text(tx.TOPUP_PENDING, reply_markup=kb.kb_reply_menu())
        return
    credited = await credit_topup_if_pending(internal_id, q.from_user.id)
    await q.answer()
    if credited is None:
        await q.message.reply_text(tx.TOPUP_ALREADY_DONE, reply_markup=kb.kb_reply_menu())
        return
    await stickers.send_scene(context, q.message.chat_id, "success")
    await q.message.reply_text(tx.TOPUP_SUCCESS.format(amount=credited), reply_markup=kb.kb_reply_menu())


async def _send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, stars: int) -> None:
    usd = round(stars * STAR_USD_RATE, 2)
    internal = await insert_star_topup(update.effective_user.id, stars, usd)
    payload = f"stars|{internal}"
    chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="⭐ Пополнение NEXIVORA",
        description=f"{stars} звёзд → {usd:g}$ на баланс",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Telegram Stars", amount=stars)],
    )
    await update.effective_message.reply_text(
        tx.TOPUP_STARS_INVOICE.format(stars=stars, usd=usd),
        reply_markup=kb.kb_reply_menu(),
    )


async def on_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.pre_checkout_query
    if not q:
        return
    await q.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.successful_payment:
        return
    sp = msg.successful_payment
    payload = sp.invoice_payload or ""
    if not payload.startswith("stars|"):
        return
    try:
        topup_id = int(payload.split("|", 1)[1])
    except (IndexError, ValueError):
        return
    charge_id = sp.telegram_payment_charge_id
    credited = await credit_star_topup(topup_id, charge_id, update.effective_user.id)
    if credited is None:
        return
    await stickers.send_scene(context, msg.chat_id, "success")
    await msg.reply_text(tx.TOPUP_SUCCESS.format(amount=credited), reply_markup=kb.kb_reply_menu())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ud = context.user_data
    stage = ud.get("await_input")
    if not stage:
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    if stage == "topup_amt":
        client = context.bot_data.get("cryptopay")
        if not client:
            ud.pop("await_input", None)
            await update.message.reply_text(tx.TOPUP_NO_API, reply_markup=kb.kb_reply_menu())
            return
        try:
            amount = float(text.replace(",", ".").replace(" ", ""))
        except ValueError:
            await update.message.reply_text(tx.TOPUP_BAD_AMOUNT, reply_markup=kb.kb_reply_menu())
            return
        if amount < TOPUP_MIN_USD or amount > TOPUP_MAX_USD:
            await update.message.reply_text(
                f"{tx.TOPUP_BAD_AMOUNT}\nДопустимо: {TOPUP_MIN_USD:g}$ — {TOPUP_MAX_USD:g}$.",
                reply_markup=kb.kb_reply_menu(),
            )
            return
        payload = f"nx|{update.effective_user.id}|{secrets.token_hex(8)}"
        amt_str = f"{amount:.2f}".rstrip("0").rstrip(".")
        try:
            inv = await client.create_invoice(
                asset=CRYPTO_PAY_ASSET,
                amount=amt_str,
                description=f"NEXIVORA пополнение {amount:g}$",
                payload=payload,
            )
        except CryptoPayError as e:
            log.warning("createInvoice: %s", e)
            await update.message.reply_text(
                f"Не удалось создать счёт в Crypto Pay.\n{e}",
                reply_markup=kb.kb_reply_menu(),
            )
            return
        inv_id = int(inv.get("invoice_id", 0))
        if not inv_id:
            await update.message.reply_text("Crypto Pay вернул ответ без invoice_id.", reply_markup=kb.kb_reply_menu())
            return
        internal = await insert_crypto_topup(update.effective_user.id, inv_id, amount, payload)
        pay_url = inv.get("mini_app_invoice_url") or inv.get("bot_invoice_url") or inv.get("pay_url")
        ud.pop("await_input", None)
        if not pay_url:
            await update.message.reply_text(
                "Счёт создан. Открой @CryptoBot → Crypto Pay → мои счета.",
                reply_markup=kb.kb_topup_check_only(internal),
            )
        else:
            await update.message.reply_text(
                tx.TOPUP_INVOICE_CREATED,
                reply_markup=kb.kb_topup_invoice(pay_url, internal),
            )
        await stickers.send_scene(context, update.effective_chat.id, "pay")
        return

    if stage == "topup_stars":
        try:
            stars = int(text.replace(" ", ""))
        except ValueError:
            await update.message.reply_text(
                tx.TOPUP_BAD_STARS.format(min_stars=STAR_MIN),
                reply_markup=kb.kb_reply_menu(),
            )
            return
        if stars < STAR_MIN or stars > STAR_MAX:
            await update.message.reply_text(
                tx.TOPUP_BAD_STARS.format(min_stars=STAR_MIN),
                reply_markup=kb.kb_reply_menu(),
            )
            return
        ud.pop("await_input", None)
        await _send_stars_invoice(update, context, stars)
        await stickers.send_scene(context, update.effective_chat.id, "pay")
        return

    if stage == "promo_code":
        code = text.strip()
        ud.pop("await_input", None)
        bonus = PROMO_CODES.get(code.lower())
        if bonus is None:
            await update.message.reply_text(tx.TASK_PROMO_INVALID, reply_markup=kb.kb_reply_menu())
            return
        if await promo_already_used(update.effective_user.id, code):
            await update.message.reply_text(tx.TASK_PROMO_INVALID, reply_markup=kb.kb_reply_menu())
            return
        await add_balance(update.effective_user.id, bonus)
        await mark_promo_used(update.effective_user.id, code)
        await update.message.reply_text(
            tx.TASK_PROMO_OK.format(amount=bonus),
            reply_markup=kb.kb_reply_menu(),
        )
        await stickers.send_scene(context, update.effective_chat.id, "success")
        return

    if stage == "robux_amount":
        try:
            robux = float(text.replace(",", ".").replace(" ", ""))
        except ValueError:
            await update.message.reply_text("⚠️ Введите целое число Robux.", reply_markup=kb.kb_reply_menu())
            return
        if robux < 1:
            await update.message.reply_text("⚠️ Минимум 1 Robux.", reply_markup=kb.kb_reply_menu())
            return
        price = robux_price_usd(robux)
        ud["co_key"] = "roblox_robux"
        ud["co_robux"] = robux
        ud["co_price"] = price
        ud["co_extra"] = f"Robux: {robux:g}"
        ud["await_input"] = "roblox_nick"
        await update.message.reply_text(
            tx.ROBLOX_PRICE.format(robux=robux, price=price),
            reply_markup=kb.kb_reply_menu(),
        )
        return

    if stage == "roblox_nick":
        ud["co_email"] = text
        ud["await_input"] = "roblox_tg"
        await update.message.reply_text(tx.ROBLOX_CONTACT, reply_markup=kb.kb_reply_menu())
        return

    if stage == "roblox_tg":
        ud["co_contact"] = text
        ud["await_input"] = None
        p = PRODUCTS["roblox_robux"]
        price = float(ud["co_price"])
        await update.message.reply_text(
            tx.CHECKOUT_GENERIC.format(
                title=p.title,
                price=price,
                contact=ud["co_contact"],
                extra=f"\n🎮 Ник Roblox: {ud['co_email']}\n💎 {ud['co_extra']}",
            ),
            reply_markup=kb.kb_pay_balance(),
        )
        await stickers.send_scene(context, update.effective_chat.id, "pay")
        return

    if stage == "sc_email":
        if "@" not in text or "." not in text.split("@")[-1]:
            await update.message.reply_text(
                "⚠️ Похоже на неверный email. Введите почту Supercell ID ещё раз.",
                reply_markup=kb.kb_reply_menu(),
            )
            return
        ud["co_email"] = text
        ud["await_input"] = None
        key = ud.get("co_key")
        if not key or key not in PRODUCTS:
            _clear_checkout(ud)
            await update.message.reply_text("Сессия сброшена. Откройте «Купить» снова.", reply_markup=kb.kb_reply_menu())
            return
        p = PRODUCTS[key]
        await update.message.reply_text(
            tx.CHECKOUT_BRAWL.format(title=p.title, price=p.price_usd, email=ud["co_email"]),
            reply_markup=kb.kb_pay_balance(),
        )
        await stickers.send_scene(context, update.effective_chat.id, "pay")
        return

    if stage == "contact_only":
        ud["co_contact"] = text
        ud["await_input"] = None
        key = ud.get("co_key")
        if not key or key not in PRODUCTS:
            _clear_checkout(ud)
            await update.message.reply_text("Сессия сброшена.", reply_markup=kb.kb_reply_menu())
            return
        p = PRODUCTS[key]
        price = float(ud.get("co_price") or p.price_usd)
        extra = ""
        if key == "fortnite_squad":
            extra = "\n🎯 После оплаты администратор свяжется с вами в Telegram."
        elif key in ("cursor_ai", "chatgpt"):
            extra = "\n⏳ Подписка на 1 месяц. После оплаты администратор свяжется с вами."
        await update.message.reply_text(
            tx.CHECKOUT_GENERIC.format(
                title=p.title,
                price=price,
                contact=ud["co_contact"],
                extra=extra,
            ),
            reply_markup=kb.kb_pay_balance(),
        )
        await stickers.send_scene(context, update.effective_chat.id, "pay")
        return


async def dispatch_back(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_checkout(context.user_data)
    target = nav_back(context.user_data)
    if target == "start":
        img = ui._image_for("start")
        if img and query.message.photo:
            await ui.edit_to_screen(
                query,
                context,
                screen="start",
                text=tx.WELCOME,
                reply_markup=kb.kb_start(),
                sticker_scene="welcome",
            )
        elif img:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=ui._photo_input(img),
                caption=tx.WELCOME,
                reply_markup=kb.kb_start(),
            )
            try:
                await query.message.delete()
            except Exception:
                pass
            await stickers.send_scene(context, query.message.chat_id, "welcome")
        else:
            await ui.edit_to_screen(
                query,
                context,
                screen="start",
                text=tx.WELCOME,
                reply_markup=kb.kb_start(),
                sticker_scene="welcome",
            )
        return
    if target == "menu":
        await ui.render_menu(query, context)
        return
    if target == "tasks":
        await ui.render_tasks(query, context)
        return
    if target == "tsub":
        row = await ensure_user(query.from_user.id, query.from_user.username)
        await ui.render_task_subscribe(query, context, done=bool(row.get("task_channel_done")))
        return
    if target == "tpart":
        await ui.render_partner(query, context)
        return
    if target == "buy":
        await ui.render_buy(query, context)
        return
    if target == "bs":
        await ui.render_game(query, context, "bs", tx.BRAWL_HEADER, "bs")
        return
    if target == "roblox":
        await ui.render_game(query, context, "roblox", "🧱 Roblox — выберите товар:", "roblox")
        return
    if target == "fortnite":
        await ui.render_game(query, context, "fortnite", "🎯 Fortnite — выберите товар:", "fortnite")
        return
    if target == "ai":
        await ui.render_game(query, context, "ai", "🤖 Нейросети — выберите подписку:", "ai")
        return
    if target == "orders":
        await ui.render_orders(query, context)
        return
    if target == "topup":
        await ui.render_topup(query, context)
        return
    if target == "topup_crypto":
        await ui.render_topup_crypto(query, context)
        return
    if target == "support":
        await ui.render_support(query, context)
        return
    await ui.render_menu(query, context)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data:
        return
    data = q.data
    parts = data.split("|")
    kind = parts[0]

    if kind == "a" and len(parts) == 3 and parts[1] == "ok":
        await _admin_mark_done(update, context)
        return

    if kind == "t" and len(parts) == 2 and parts[1] == "chk":
        user_id = q.from_user.id
        row = await ensure_user(user_id, q.from_user.username)
        if row.get("task_channel_done"):
            await q.answer(tx.TASK_SUBSCRIBE_DONE, show_alert=True)
            return
        if not await _is_channel_member(context, user_id):
            await q.answer()
            await q.message.reply_text(tx.TASK_SUBSCRIBE_FAIL, reply_markup=kb.kb_reply_menu())
            return
        await q.answer()
        await add_balance(user_id, TASK_CHANNEL_REWARD_USD)
        await mark_task_done(user_id)
        await q.message.reply_text(tx.TASK_SUBSCRIBE_OK, reply_markup=kb.kb_reply_menu())
        await stickers.send_scene(context, q.message.chat_id, "success")
        await ui.render_task_subscribe(q, context, done=True)
        return

    if kind == "y" and len(parts) == 2 and parts[1] == "u":
        await _finalize_paid_order(update, context)
        return

    if kind == "r" and len(parts) == 2 and parts[1] == "stats":
        await q.answer()
        push_nav(context.user_data, "tstats")
        await ui.render_partner_stats(q, context)
        return

    if kind == "p" and len(parts) >= 2:
        if parts[1] == "go":
            push_nav(context.user_data, "topup_crypto")
            await topup_go(update, context)
        elif parts[1] == "stars":
            await topup_stars_start(update, context)
        elif parts[1] == "chk" and len(parts) == 3:
            await topup_check(update, context, int(parts[2]))
        return

    if kind == "n" and parts[1] == "b":
        await q.answer()
        await dispatch_back(q, context)
        return

    await q.answer()

    if kind == "g":
        _clear_checkout(context.user_data)
        screen = parts[1]
        ud = context.user_data
        if screen == "menu":
            push_nav(ud, "menu")
            await ui.render_menu(q, context)
            return
        if screen == "tasks":
            push_nav(ud, "tasks")
            await ui.render_tasks(q, context)
            return
        if screen == "tsub":
            push_nav(ud, "tsub")
            row = await ensure_user(q.from_user.id, q.from_user.username)
            await ui.render_task_subscribe(q, context, done=bool(row.get("task_channel_done")))
            return
        if screen == "tpart":
            push_nav(ud, "tpart")
            await ui.render_partner(q, context)
            return
        if screen == "tpromo":
            push_nav(ud, "tpromo")
            ud["await_input"] = "promo_code"
            await q.message.reply_text(tx.TASK_PROMO_ASK, reply_markup=kb.kb_reply_menu())
            return
        if screen == "buy":
            push_nav(ud, "buy")
            await ui.render_buy(q, context)
            return
        if screen == "bs":
            push_nav(ud, "bs")
            await ui.render_game(q, context, "bs", tx.BRAWL_HEADER, "bs")
            return
        if screen == "roblox":
            push_nav(ud, "roblox")
            await ui.render_game(q, context, "roblox", "🧱 Roblox — выберите товар:", "roblox")
            return
        if screen == "fortnite":
            push_nav(ud, "fortnite")
            await ui.render_game(q, context, "fortnite", "🎯 Fortnite — выберите товар:", "fortnite")
            return
        if screen == "ai":
            push_nav(ud, "ai")
            await ui.render_game(q, context, "ai", "🤖 Нейросети — выберите подписку:", "ai")
            return
        if screen == "orders":
            push_nav(ud, "orders")
            await ui.render_orders(q, context)
            return
        if screen == "topup":
            push_nav(ud, "topup")
            await ui.render_topup(q, context)
            return
        if screen == "topup_crypto":
            push_nav(ud, "topup_crypto")
            await ui.render_topup_crypto(q, context)
            return
        if screen == "support":
            push_nav(ud, "support")
            await ui.render_support(q, context)
            return
        return

    if kind == "c" and len(parts) == 2:
        key = parts[1]
        if key not in PRODUCTS:
            return
        ud = context.user_data
        _clear_checkout(ud)
        p = PRODUCTS[key]
        ud["co_key"] = key
        ud["co_price"] = p.price_usd
        if p.checkout == "brawl_email":
            ud["await_input"] = "sc_email"
            await q.message.reply_text(
                "📧 Введите почту Supercell ID для оформления заказа:",
                reply_markup=kb.kb_reply_menu(),
            )
            return
        if p.checkout == "roblox":
            ud["await_input"] = "robux_amount"
            await q.message.reply_text(tx.ROBLOX_INTRO, reply_markup=kb.kb_reply_menu())
            return
        if p.checkout == "contact_only":
            if key == "fortnite_squad":
                ud["await_input"] = "contact_only"
                await q.message.reply_text(
                    tx.FORTNITE_CONTACT.format(price=p.price_usd),
                    reply_markup=kb.kb_reply_menu(),
                )
            else:
                ud["await_input"] = "contact_only"
                await q.message.reply_text(
                    tx.AI_CONTACT.format(
                        title=p.title,
                        desc=p.description,
                        price=p.price_usd,
                    ),
                    reply_markup=kb.kb_reply_menu(),
                )
            return


async def _admin_mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q
    if q.from_user.id not in ADMIN_IDS:
        await q.answer("Недостаточно прав.", show_alert=True)
        return
    order_id = int(q.data.split("|")[2])
    order = await get_order(order_id)
    if not order:
        await q.answer("Заказ не найден.", show_alert=True)
        return
    await set_order_status(order_id, "completed")
    await q.answer("Статус обновлён")
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=tx.ORDER_DONE_USER,
            reply_markup=kb.kb_reply_menu(),
        )
        await stickers.send_scene(context, order["user_id"], "success")
    except Exception:
        pass
