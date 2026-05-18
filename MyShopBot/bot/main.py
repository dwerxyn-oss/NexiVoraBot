import logging
import sys

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)
from telegram.request import HTTPXRequest

from bot import db
from bot import stickers
from bot.admin_cmds import cmd_broadcast, cmd_grant
from bot.callbacks import (
    cmd_start,
    on_callback,
    on_pre_checkout,
    on_reply_menu,
    on_successful_payment,
    on_text,
)
from bot.config import (
    BOT_TOKEN,
    CRYPTO_PAY_API_TOKEN,
    CRYPTO_PAY_TESTNET,
    STICKER_PACK_NAME,
    TELEGRAM_PROXY,
    TG_CONNECT_TIMEOUT,
    TG_POOL_TIMEOUT,
    TG_READ_TIMEOUT,
    TG_WRITE_TIMEOUT,
    ensure_dirs,
)
from bot.cryptopay import CryptoPayClient, CryptoPayError

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("nexivora")


def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан. Создайте файл .env по образцу .env.example.")
        sys.exit(1)

    ensure_dirs()

    async def post_init(app: Application) -> None:
        await db.init_db()
        me = await app.bot.get_me()
        app.bot_data["bot_username"] = me.username or ""
        log.info("Бот: @%s", app.bot_data["bot_username"])
        await stickers.warm_cache(app, STICKER_PACK_NAME)
        if CRYPTO_PAY_API_TOKEN:
            client = CryptoPayClient(CRYPTO_PAY_API_TOKEN, testnet=CRYPTO_PAY_TESTNET)
            try:
                await client.get_me()
                app.bot_data["cryptopay"] = client
                log.info("Crypto Pay: API-токен принят, getMe успешно.")
            except CryptoPayError as e:
                log.warning("Crypto Pay getMe отклонён: %s — пополнение отключено.", e)
                app.bot_data["cryptopay"] = None
            except Exception as e:
                log.warning("Crypto Pay: %s — пополнение отключено.", e)
                app.bot_data["cryptopay"] = None
        else:
            app.bot_data["cryptopay"] = None

    req_kw: dict = {
        "connect_timeout": TG_CONNECT_TIMEOUT,
        "read_timeout": TG_READ_TIMEOUT,
        "write_timeout": TG_WRITE_TIMEOUT,
        "pool_timeout": TG_POOL_TIMEOUT,
    }
    if TELEGRAM_PROXY:
        req_kw["proxy_url"] = TELEGRAM_PROXY
        log.info("Используется прокси для запросов к Telegram (TELEGRAM_PROXY / HTTPS_PROXY).")
    request = HTTPXRequest(**req_kw)

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("grant", cmd_grant))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"^(📋\s*)?Меню$"), on_reply_menu),
    )
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(PreCheckoutQueryHandler(on_pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("NEXIVORA запущен.")
    application.run_polling()


if __name__ == "__main__":
    main()
