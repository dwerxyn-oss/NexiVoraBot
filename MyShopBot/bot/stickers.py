"""Опциональные стикеры: кэш из публичного набора по имени (STICKER_PACK_NAME в .env)."""

import logging
from typing import Any, Dict, List, Optional

from telegram import Update
from telegram.ext import Application, ContextTypes

log = logging.getLogger("nexivora.stickers")

SCENE_INDEX: Dict[str, int] = {
    "welcome": 0,
    "menu": 1,
    "tasks": 2,
    "partner": 3,
    "buy": 4,
    "bs": 5,
    "roblox": 6,
    "fortnite": 7,
    "ai": 8,
    "orders": 9,
    "topup": 10,
    "support": 11,
    "pay": 12,
    "success": 13,
    "order": 14,
    "generic": 15,
}


async def warm_cache(application: Application, pack_name: str) -> None:
    application.bot_data["sticker_file_ids"] = []
    if not pack_name:
        return
    try:
        s = await application.bot.get_sticker_set(pack_name)
        ids: List[str] = [x.file_id for x in s.stickers]
        application.bot_data["sticker_file_ids"] = ids
        log.info("Загружено стикеров из набора «%s»: %s", pack_name, len(ids))
    except Exception as e:
        log.warning("Не удалось загрузить набор стикеров «%s»: %s", pack_name, e)


def _pick_file_id(bot_data: Dict[str, Any], scene: str) -> Optional[str]:
    ids: List[str] = bot_data.get("sticker_file_ids") or []
    if not ids:
        return None
    idx = SCENE_INDEX.get(scene, SCENE_INDEX["generic"]) % len(ids)
    return ids[idx]


async def send_scene(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    scene: str,
) -> None:
    fid = _pick_file_id(context.bot_data, scene)
    if not fid:
        return
    try:
        await context.bot.send_sticker(chat_id=chat_id, sticker=fid)
    except Exception as e:
        log.debug("send_sticker skip: %s", e)


async def send_scene_for_update(update: Update, context: ContextTypes.DEFAULT_TYPE, scene: str) -> None:
    msg = update.effective_message
    if not msg:
        return
    await send_scene(context, msg.chat_id, scene)
