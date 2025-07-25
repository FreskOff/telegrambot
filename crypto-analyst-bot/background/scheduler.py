# background/scheduler.py
# Модуль для запуска фоновых задач с надежной отправкой уведомлений.

import logging
import os
import httpx
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

# --- Импорт модулей проекта ---
from database.engine import AsyncSessionFactory
from database import operations as db_ops
from settings.messages import get_text
from utils.api_clients import coingecko_client
from crypto.handler import COIN_ID_MAP
from crypto.pre_market import get_premarket_signals
from datetime import datetime, timedelta, timezone
from analysis.metrics import gather_metrics
from ai.prediction import update_prediction_cache

logger = logging.getLogger(__name__)
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PRIVATE_CHANNEL_ID = os.getenv("PRIVATE_CHANNEL_ID")

# Telegram Bot instance used by scheduler tasks
tg_bot: Bot | None = None

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
                            response = await client.post(send_url, params=params)
                            if response.status_code != 200:
                                logger.error(
                                    f"Telegram API error {response.status_code} when sending alert {alert.id}: {response.text}"
                                )
                                response.raise_for_status()
                        
                        await db_ops.deactivate_alert(session, alert.id)
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление по алерту {alert.id}: {e}")

        except Exception as e:
            logger.error(f"Критическая ошибка в задаче check_price_alerts: {e}", exc_info=True)


async def check_subscriptions():
    """Проверяет статус активных подписок."""
    logger.info("Scheduler job: Проверка статуса подписок...")

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Scheduler job: TELEGRAM_BOT_TOKEN не найден.")
        return

    async with AsyncSessionFactory() as session:
        try:
            subs = await db_ops.get_active_subscriptions(session)
            if not subs:
                return

            for sub in subs:
                try:
                    status = await tg_bot._post(
                        "payments.getStarsStatus",
                        data={"user_id": sub.user_id},
                    )
                    active = bool(status.get("active")) if isinstance(status, dict) else False
                    next_ts = status.get("next_payment_date") if isinstance(status, dict) else None
                    next_payment = datetime.fromtimestamp(next_ts) if next_ts else None
                    await db_ops.create_or_update_subscription(
                        session,
                        sub.user_id,
                        is_active=active,
                        next_payment=next_payment,
                        level=sub.level,
                    )

                    if PRIVATE_CHANNEL_ID:
                        if active:
                            try:
                                await tg_bot.unban_chat_member(PRIVATE_CHANNEL_ID, sub.user_id)
                                invite = await tg_bot.export_chat_invite_link(PRIVATE_CHANNEL_ID)
                                user = await db_ops.get_user(session, sub.user_id)
                                lang = user.language if user else "ru"
                                msg = get_text(lang, "subscription_access_granted", link=invite)
                                send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                                params = {"chat_id": sub.user_id, "text": msg, "parse_mode": "Markdown"}
                                async with httpx.AsyncClient() as client:
                                    response = await client.post(send_url, params=params)
                                    if response.status_code != 200:
                                        logger.error(
                                            f"Telegram API error {response.status_code} when granting access to {sub.user_id}: {response.text}"
                                        )
                                        response.raise_for_status()
                            except Exception as e:
                                logger.error(f"Error granting channel access for {sub.user_id}: {e}")
                        else:
                            try:
                                await tg_bot.ban_chat_member(PRIVATE_CHANNEL_ID, sub.user_id)
                            except Exception:
                                pass
                            user = await db_ops.get_user(session, sub.user_id)
                            lang = user.language if user else "ru"
                            msg = get_text(lang, "subscription_reminder")
                            send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                            params = {"chat_id": sub.user_id, "text": msg}
                            async with httpx.AsyncClient() as client:
                                response = await client.post(send_url, params=params)
                                if response.status_code != 200:
                                    logger.error(
                                        f"Telegram API error {response.status_code} when sending reminder to {sub.user_id}: {response.text}"
                                    )
                                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"Ошибка проверки подписки для {sub.user_id}: {e}")
        except Exception as e:
            logger.error(f"Критическая ошибка в задаче check_subscriptions: {e}", exc_info=True)


async def send_premarket_digest():
    """Отправляет ежедневный дайджест предстоящих событий VIP-подписчикам."""
    logger.info("Scheduler job: Отправка ежедневного премаркет-дайджеста...")

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Scheduler job: TELEGRAM_BOT_TOKEN не найден.")
        return

    async with AsyncSessionFactory() as session:
        try:
            subs = await db_ops.get_active_subscriptions(session)
            if not subs:
                return

            events = await get_premarket_signals(vip=True)
            if not events:
                return

            lines = []
            for e in events:
                name = e.get("token_name")
                symbol = f"({e['symbol']})" if e.get("symbol") else ""
                date = f" - {e['event_date']}" if e.get("event_date") else ""
                platform = f" [{e['platform']}]" if e.get("platform") else ""
                importance = f" ({e['importance']})" if e.get("importance") else ""
                lines.append(
                    f"• *{name}* {symbol} — {e['event_type']}{date}{importance}{platform}"
                )

            for sub in subs:
                user = await db_ops.get_user(session, sub.user_id)
                lang = user.language if user else 'ru'
                msg = get_text(lang, 'premarket_digest_header') + "\n" + "\n".join(lines)
                send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                params = {"chat_id": sub.user_id, "text": msg, "parse_mode": "Markdown"}
                async with httpx.AsyncClient() as client:
                    response = await client.post(send_url, params=params)
                    if response.status_code != 200:
                        logger.error(
                            f"Telegram API error {response.status_code} when sending premarket digest to {sub.user_id}: {response.text}"
                        )
                        response.raise_for_status()
        except Exception as e:
            logger.error(f"Критическая ошибка в задаче send_premarket_digest: {e}", exc_info=True)


async def send_admin_report():
    """Ежедневный отчёт администратору о ключевых метриках."""
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if not admin_id or not TELEGRAM_BOT_TOKEN:
        return
    async with AsyncSessionFactory() as session:
        try:
            metrics = await gather_metrics(session)
            top_products = await db_ops.get_most_purchased_products(session, 3)
            top_requests = await db_ops.get_top_request_types(session, 3)
            new_subs = await db_ops.new_subscriptions_count(session)
            lost = await db_ops.inactive_users_count(session)
            lines = [
                "\uD83D\uDCCA Daily report:",
                f"Active users: {metrics['active_users']}",
                f"Purchase freq: {metrics['purchase_frequency']:.2f}",
                f"Subscriptions active: {metrics['subscriptions']['active']}/{metrics['subscriptions']['total']}",
                f"New subs today: {new_subs}",
                f"Inactive users: {lost}",
                "Popular products: " + ", ".join(f"{n} ({c})" for n, c in top_products),
                "Top requests: " + ", ".join(f"{n} ({c})" for n, c in top_requests),
            ]
            msg = "\n".join(lines)
            send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            params = {"chat_id": admin_id, "text": msg}
            async with httpx.AsyncClient() as client:
                response = await client.post(send_url, params=params)
                if response.status_code != 200:
                    logger.error(
                        f"Telegram API error {response.status_code} when sending admin report: {response.text}"
                    )
                    response.raise_for_status()
        except Exception as e:
            logger.error(f"Ошибка в задаче send_admin_report: {e}")


async def send_subscription_reminder(user_id: int):
    """Send reminder message about expiring subscription."""
    if not TELEGRAM_BOT_TOKEN:
        return
    async with AsyncSessionFactory() as session:
        user = await db_ops.get_user(session, user_id)
        if not user:
            return
        lang = user.language
        msg = get_text(lang, "subscription_expiring")
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        params = {"chat_id": user_id, "text": msg}
        async with httpx.AsyncClient() as client:
            response = await client.post(send_url, params=params)
            if response.status_code != 200:
                logger.error(
                    f"Telegram API error {response.status_code} when sending subscription reminder to {user_id}: {response.text}"
                )
                response.raise_for_status()


def schedule_subscription_reminder(user_id: int, next_payment: datetime):
    """Schedule reminder 3 days before subscription end."""
    if not next_payment:
        return
    remind_at = next_payment - timedelta(days=3)
    if remind_at <= datetime.now(timezone.utc):
        return
    job_id = f"reminder_{user_id}"
    scheduler.add_job(
        send_subscription_reminder,
        'date',
        run_date=remind_at,
        args=[user_id],
        id=job_id,
        replace_existing=True,
    )

# --- Управление планировщиком ---
scheduler = AsyncIOScheduler(timezone="UTC")

def start_scheduler(bot: Bot):
    """Запускает планировщик фоновых задач."""
    global tg_bot
    tg_bot = bot
    scheduler.add_job(check_price_alerts, 'interval', seconds=60, id='price_check_job', replace_existing=True)
    scheduler.add_job(
        check_subscriptions,
        'cron',
        hour=0,
        id='subscription_check_job',
        replace_existing=True,
    )
    scheduler.add_job(
        send_premarket_digest,
        'cron',
        hour=8,
        id='premarket_digest_job',
        replace_existing=True,
    )
    scheduler.add_job(
        send_admin_report,
        'cron',
        hour=9,
        id='admin_report_job',
        replace_existing=True,
    )
    scheduler.add_job(
        update_prediction_cache,
        'cron',
        hour='*/6',
        id='prediction_update_job',
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
        logger.info("Планировщик успешно запущен.")
