# main.py
# Точка входа в приложение. Инициализирует FastAPI, базу данных,
# и запускает логику Telegram-бота.

import os
import logging
import json
import re
from datetime import datetime
import uvicorn
import asyncio
from fastapi import FastAPI, Request, Response, Depends
from dotenv import load_dotenv
from starlette.requests import ClientDisconnect
from telegram import Update
from telegram.ext import Application, CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Загрузка переменных окружения ---
load_dotenv()

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден в переменных окружения!")
    raise ValueError("Необходимо указать TELEGRAM_BOT_TOKEN")
if not WEBHOOK_URL:
    logger.warning("WEBHOOK_URL не указан. Вебхук не будет установлен для продакшена.")


# --- Импорт модулей бота ---
from bot.core import handle_update
from database.engine import init_db, get_db_session, AsyncSessionFactory
from background.scheduler import start_scheduler
from analysis.metrics import gather_metrics
from admin.routes import router as admin_router
from database import operations as db_ops
from settings.messages import get_text

# --- Инициализация FastAPI ---
app = FastAPI(title="Crypto AI Analyst Bot", version="1.0.0")
app.include_router(admin_router)

# --- Инициализация Telegram Bot API ---
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = application.bot


def _load_update_data(raw_body: bytes) -> dict:
    """Parse update JSON and try to recover from malformed commas."""
    text = raw_body.decode("utf-8", "ignore").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        cleaned = text
        # Collapse duplicate commas which may appear due to bad formatting
        while True:
            new_cleaned = re.sub(r",\s*,+", ",", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        # Remove commas right before closing brackets/braces
        cleaned = re.sub(r",\s*(?=[}\]])", "", cleaned)
        # Remove any trailing comma at the very end of the string
        cleaned = re.sub(r",\s*$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise e


async def process_update(update_data: dict) -> None:
    """Handle an incoming Telegram update in the background."""
    async with AsyncSessionFactory() as session:
        async with application:
            update = Update.de_json(update_data, bot)
            context = CallbackContext.from_update(update, application)
            await handle_update(update, context, session)


# --- Обработчики событий FastAPI ---


@app.on_event("startup")
async def startup_event():
    logger.info("Приложение запускается...")
    await init_db()

    if WEBHOOK_URL:
        webhook_url_path = f"/webhook/{TELEGRAM_BOT_TOKEN}"
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_url_path}"

        masked_token = TELEGRAM_BOT_TOKEN[:4] + "..." + TELEGRAM_BOT_TOKEN[-4:]
        masked_url = f"{WEBHOOK_URL.rstrip('/')}/webhook/{masked_token}"

        logger.info(f"Установка вебхука на URL: {masked_url}")
        success = await bot.set_webhook(
            url=full_webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        if success:
            logger.info("Вебхук успешно установлен.")
        else:
            logger.error("Не удалось установить вебхук.")

    # Запускаем планировщик фоновых задач
    start_scheduler(bot)
    logger.info("Планировщик запущен.")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Приложение останавливается...")
    await bot.delete_webhook()
    logger.info("Вебхук удален.")


# --- Эндпоинты FastAPI ---


@app.get("/", summary="Статус сервера")
async def read_root():
    return {"status": "ok", "message": "Crypto AI Analyst Bot is running."}


@app.get("/metrics", summary="Базовые метрики")
async def metrics_endpoint(db_session: AsyncSession = Depends(get_db_session)):
    return await gather_metrics(db_session)


@app.post("/payments/callback", summary="Payment webhook")
async def payments_callback(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    data = await request.json()
    user_id = data.get("user_id")
    if not user_id:
        return {"ok": False}

    event_type = data.get("type")
    lang = "ru"
    user = await db_ops.get_user(db_session, user_id)
    if user:
        lang = user.language

    if event_type == "stars":
        amount = int(data.get("amount", 0))
        if amount:
            await db_ops.add_stars(db_session, user_id, amount)
            await bot.send_message(
                user_id, get_text(lang, "purchase_success", product=f"+{amount}⭐")
            )
    elif event_type == "product":
        product_id = data.get("product_id")
        product = (
            await db_ops.get_product(db_session, product_id) if product_id else None
        )
        if product and not await db_ops.has_purchased(db_session, user_id, product_id):
            await db_ops.add_purchase(db_session, user_id, product_id)
            await bot.send_message(
                user_id, get_text(lang, "purchase_success", product=product.name)
            )
            try:
                if product.content_type == "text":
                    await bot.send_message(user_id, product.content_value)
                elif product.content_type == "file":
                    with open(product.content_value, "rb") as f:
                        await bot.send_document(user_id, f)
            except Exception:
                pass
    elif event_type == "subscription":
        level = data.get("level", "basic")
        next_ts = data.get("next_payment_date")
        next_payment = datetime.fromtimestamp(next_ts) if next_ts else None
        await db_ops.create_or_update_subscription(
            db_session, user_id, is_active=True, next_payment=next_payment, level=level
        )
        await bot.send_message(user_id, get_text(lang, f"subscription_{level}"))
    return {"ok": True}


@app.post("/webhook/{token}", summary="Вебхук для Telegram")
async def telegram_webhook(
    request: Request, token: str, db_session: AsyncSession = Depends(get_db_session)
):
    if token != TELEGRAM_BOT_TOKEN:
        return Response(status_code=403)

    try:
        raw_body = None
        if hasattr(request, "json"):
            try:
                update_data = await request.json()
            except json.JSONDecodeError:
                raw_body = await request.body()
                update_data = _load_update_data(raw_body)
        else:
            raw_body = await request.body()
            update_data = _load_update_data(raw_body)

        update_preview = Update.de_json(update_data, bot)
        if (
            update_preview.callback_query is None
            and update_preview.pre_checkout_query is None
            and update_preview.effective_message
        ):
            user_id = (
                update_preview.effective_user.id
                if update_preview.effective_user
                else None
            )
            lang = "ru"
            if user_id:
                user = await db_ops.get_user(db_session, user_id)
                if user:
                    lang = user.language
            await bot.send_message(
                update_preview.effective_chat.id, get_text(lang, "generic_processing")
            )

        asyncio.create_task(process_update(update_data))

    except ClientDisconnect:
        logger.warning(
            "Клиент (Telegram) отключился до того, как мы успели прочитать запрос. Игнорируем."
        )
    except json.JSONDecodeError as e:
        if raw_body is None:
            raw_body = await request.body()
        logger.warning(
            "Получен запрос с невалидным JSON: %r, длина=%d, ошибка=%s",
            raw_body,
            len(raw_body),
            e,
        )
    except Exception as e:
        logger.error(f"Ошибка при разборе обновления: {e!r}", exc_info=True)

    return Response(status_code=200)


# --- Запуск приложения ---
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
