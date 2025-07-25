# main.py
# Точка входа в приложение. Инициализирует FastAPI, базу данных,
# и запускает логику Telegram-бота.

import os
import logging
import json
import uvicorn
from fastapi import FastAPI, Request, Response, Depends
from dotenv import load_dotenv
from starlette.requests import ClientDisconnect
from telegram import Update
from telegram.ext import Application, CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
from database.engine import init_db, get_db_session
from background.scheduler import start_scheduler
from analysis.metrics import gather_metrics

# --- Инициализация FastAPI ---
app = FastAPI(title="Crypto AI Analyst Bot", version="1.0.0")

# --- Инициализация Telegram Bot API ---
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = application.bot


# --- Обработчики событий FastAPI ---

@app.on_event("startup")
async def startup_event():
    logger.info("Приложение запускается...")
    await init_db()
    
    if WEBHOOK_URL:
        webhook_url_path = f"/webhook/{TELEGRAM_BOT_TOKEN}"
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_url_path}"
        
        logger.info(f"Установка вебхука на URL: {full_webhook_url}")
        success = await bot.set_webhook(
            url=full_webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        if success:
            logger.info("Вебхук успешно установлен.")
        else:
            logger.error("Не удалось установить вебхук.")
            
    # --- ИСПРАВЛЕНИЕ: Вызываем start_scheduler без аргументов ---
    start_scheduler()
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


@app.post("/webhook/{token}", summary="Вебхук для Telegram")
async def telegram_webhook(
    request: Request,
    token: str,
    db_session: AsyncSession = Depends(get_db_session)
):
    if token != TELEGRAM_BOT_TOKEN:
        return Response(status_code=403)

    try:
        update_data = await request.json()
        
        async with application:
            update = Update.de_json(update_data, bot)
            context = CallbackContext.from_update(update, application)
            await handle_update(update, context, db_session)

    except ClientDisconnect:
        logger.warning("Клиент (Telegram) отключился до того, как мы успели прочитать запрос. Игнорируем.")
    except json.JSONDecodeError:
        logger.warning("Получен запрос с невалидным JSON. Игнорируем.")
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обработке вебхука: {e}", exc_info=True)
    
    return Response(status_code=200)


# --- Запуск приложения ---
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)