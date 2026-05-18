import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import texts as tx
from bot.config import ADMIN_IDS
from bot.db import add_balance, fetch_user_by_public_id, list_all_user_ids

log = logging.getLogger("nexivora.admin")


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пополнение баланса пользователю по публичному ID: /grant 100042 5"""
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text(tx.ADMIN_GRANT_HELP, reply_markup=kb.kb_reply_menu())
        return
    try:
        public_id = int(context.args[0])
        amount = float(context.args[1].replace("$", "").replace(",", ".").strip())
    except ValueError:
        await update.message.reply_text(tx.ADMIN_GRANT_BAD_ARGS, reply_markup=kb.kb_reply_menu())
        return
    if amount <= 0:
        await update.message.reply_text("⚠️ Сумма должна быть больше нуля.", reply_markup=kb.kb_reply_menu())
        return
    row = await fetch_user_by_public_id(public_id)
    if not row:
        await update.message.reply_text(
            tx.ADMIN_GRANT_NOT_FOUND.format(public_id=public_id),
            reply_markup=kb.kb_reply_menu(),
        )
        return
    await add_balance(int(row["user_id"]), amount)
    new_bal = float(row.get("balance_usd") or 0) + amount
    await update.message.reply_text(
        tx.ADMIN_GRANT_OK.format(public_id=public_id, amount=amount, balance=new_bal),
        reply_markup=kb.kb_reply_menu(),
    )
    try:
        await context.bot.send_message(
            chat_id=int(row["user_id"]),
            text=tx.ADMIN_GRANT_USER_NOTIFY.format(amount=amount),
            reply_markup=kb.kb_reply_menu(),
        )
    except Exception:
        pass


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Рассылка всем пользователям: /broadcast текст сообщения"""
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    msg = update.message
    if not msg or not msg.text:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.reply_text(tx.ADMIN_BROADCAST_HELP, reply_markup=kb.kb_reply_menu())
        return
    text = parts[1].strip()
    user_ids = await list_all_user_ids()
    if not user_ids:
        await msg.reply_text("В базе пока нет пользователей.", reply_markup=kb.kb_reply_menu())
        return
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception as e:
            failed += 1
            log.debug("broadcast skip %s: %s", uid, e)
    await msg.reply_text(
        tx.ADMIN_BROADCAST_DONE.format(sent=sent, failed=failed, total=len(user_ids)),
        reply_markup=kb.kb_reply_menu(),
    )
