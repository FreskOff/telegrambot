# background/scheduler.py
# Модуль для запуска фоновых задач с надежной отправкой уведомлений.

import logging
import os
import httpx
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Импорт модулей проекта ---
from database.engine import AsyncSessionFactory
from database import operations as db_ops
from settings.messages import get_text
from utils.api_clients import coingecko_client
from crypto.handler import COIN_ID_MAP

logger = logging.getLogger(__name__)
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def check_price_alerts():
    """
    Основная задача, которая выполняется по расписанию.
    """
    logger.info("Scheduler job: Запуск проверки ценовых алертов...")
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Scheduler job: TELEGRAM_BOT_TOKEN не найден.")
        return

    async with AsyncSessionFactory() as session:
        try:
            active_alerts = await db_ops.get_all_active_alerts(session)
            if not active_alerts:
                logger.info("Scheduler job: Активных алертов не найдено.")
                return

            symbols_to_check = {alert.coin_symbol for alert in active_alerts}
            coin_ids_to_check = [COIN_ID_MAP.get(s) for s in symbols_to_check if COIN_ID_MAP.get(s)]
            
            if not coin_ids_to_check: return

            price_data = await coingecko_client.get_simple_price(coin_ids=list(set(coin_ids_to_check)))
            if not price_data:
                logger.error("Scheduler job: Не удалось получить данные о ценах от CoinGecko.")
                return
            
            for alert in active_alerts:
                coin_id = COIN_ID_MAP.get(alert.coin_symbol)
                if not coin_id or coin_id not in price_data: continue

                current_price = price_data.get(coin_id, {}).get('usd', 0)
                if not current_price: continue

                triggered = False
                if alert.direction.value == 'above' and current_price >= alert.target_price:
                    triggered = True
                elif alert.direction.value == 'below' and current_price <= alert.target_price:
                    triggered = True

                if triggered:
                    logger.info(f"Алерт {alert.id} сработал! User: {alert.user_id}, Symbol: {alert.coin_symbol}, Price: {current_price}")
                    
                    user = await db_ops.get_user(session, alert.user_id)
                    lang = user.language if user else 'ru'
                    if lang == 'ru':
                        direction_text = 'достигла или превысила' if alert.direction.value == 'above' else 'опустилась до или ниже'
                    else:
                        direction_text = 'reached or exceeded' if alert.direction.value == 'above' else 'dropped to or below'
                    message = get_text(
                        lang,
                        'alert_triggered',
                        symbol=alert.coin_symbol,
                        direction_text=direction_text,
                        target_price=f"{alert.target_price:,.2f}",
                        current_price=f"{current_price:,.2f}"
                    )
                    try:
                        # --- НОВЫЙ НАДЕЖНЫЙ МЕТОД ОТПРАВКИ ---
                        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                        params = {'chat_id': alert.user_id, 'text': message, 'parse_mode': 'Markdown'}
                        async with httpx.AsyncClient() as client:
                            await client.post(send_url, params=params)
                        
                        await db_ops.deactivate_alert(session, alert.id)
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление по алерту {alert.id}: {e}")

        except Exception as e:
            logger.error(f"Критическая ошибка в задаче check_price_alerts: {e}", exc_info=True)

# --- Управление планировщиком ---
scheduler = AsyncIOScheduler(timezone="UTC")

def start_scheduler():
    """
    Добавляет задачу в планировщик и запускает его.
    """
    scheduler.add_job(check_price_alerts, 'interval', seconds=60, id='price_check_job', replace_existing=True)
    if not scheduler.running:
        scheduler.start()
        logger.info("Планировщик успешно запущен.")
