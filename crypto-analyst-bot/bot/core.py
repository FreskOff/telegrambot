# bot/core.py
# Основной модуль логики бота с улучшенной обработкой контекста.

import logging
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import (
    Update,
    constants,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from utils.validators import is_valid_id, is_valid_symbol

# --- Импорт всех модулей проекта ---
from ai.dispatcher import classify_intent, extract_entities
from database import operations as db_ops
from crypto.handler import (
    handle_crypto_info_request,
    COIN_ID_MAP,
    get_coin_ids_from_symbols,
)
from settings.user import (
    handle_setup_alert,
    handle_manage_alerts,
    handle_change_language,
    handle_settings_command,
    handle_hints_command,
    MAX_FREE_PORTFOLIO_COINS,
    DAILY_FREE_MESSAGES,
)
from settings.messages import get_text
from ai.general import handle_general_ai_conversation
from analysis.handler import handle_token_analysis
from crypto.pre_market import get_premarket_signals
from utils.api_clients import coinmarketcap_client, binance_client, coingecko_client
from utils.charts import create_price_chart
from analysis.metrics import gather_metrics
from defi.farming import handle_defi_farming
from nft.analytics import handle_nft_analytics
from background.scheduler import schedule_subscription_reminder
from config import ADMIN_ID
from depin.projects import handle_depin_projects
from crypto.news import handle_news_command
from ai.prediction import handle_predict_command
from utils.intent_router import IntentRouter

logger = logging.getLogger(__name__)
router = IntentRouter()

# Стоимость подписки в звёздах и описание платежа
SUBSCRIPTION_PRICE = int(os.getenv("SUBSCRIPTION_PRICE", "20"))
SUBSCRIPTION_DESC = os.getenv("SUBSCRIPTION_DESC", "Channel subscription")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")
# Показывать подсказку по популярным темам не чаще, чем раз в N сообщений
TOP_TOPICS_HINT_LIMIT = 10
TOP_TOPICS_HINT_COOLDOWN = 24 * 60 * 60  # 24 часа

async def send_subscription_invoice(
    update: Update,
    context: CallbackContext,
    amount: int = SUBSCRIPTION_PRICE,
) -> None:
    """Отправляет пользователю счёт через Telegram Payments."""
    await send_payment_invoice(
        update,
        context,
        "subscription",
        amount,
        "Премиум-подписка",
    )

async def send_payment_invoice(
    update: Update,
    context: CallbackContext,
    product_type: str,
    amount: int,
    description: str,
) -> None:
    """Отправляет счёт на оплату через Telegram Payments."""
    chat_id = update.effective_message.chat_id
    payload = f"{product_type}-{chat_id}"
    if not PAYMENT_PROVIDER_TOKEN:
        logger.error("PAYMENT_PROVIDER_TOKEN not set")
        lang = context.user_data.get('lang', 'ru')
        msg_key = 'subscription_link_missing' if product_type == 'subscription' else 'purchase_error'
        await update.effective_message.reply_text(get_text(lang, msg_key))
        return
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=description,
        description=description,
        payload=payload,
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(description, amount)],
    )

# Main menu keyboard
def build_main_menu(lang: str) -> ReplyKeyboardMarkup:
    buttons = [
        [get_text(lang, "menu_prices"), get_text(lang, "menu_analysis")],
        [get_text(lang, "menu_premarket"), get_text(lang, "menu_education")],
        [get_text(lang, "menu_portfolio"), get_text(lang, "menu_shop")],
        [get_text(lang, "menu_subscribe"), get_text(lang, "menu_settings")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


# --- Обработчики и заглушки ---
async def handle_unsupported_request(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    lang = context.user_data.get('lang', 'ru')
    error_map = {
        "AI_RATE_LIMIT": get_text(lang, 'ai_rate_limit'),
        "AI_API_HTTP_ERROR": get_text(lang, 'ai_api_http_error'),
        "AI_SERVICE_UNCONFIGURED": get_text(lang, 'ai_service_unconfigured'),
    }
    response_text = error_map.get(payload, get_text(lang, 'unsupported_request'))
    await update.effective_message.reply_text(response_text)
    await db_ops.add_chat_message(session=db_session, user_id=update.effective_user.id, role='model', text=response_text)

async def handle_bot_help(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    user_id = update.effective_user.id
    lang = context.user_data.get("lang", "ru")
    help_text = get_text(lang, "bot_help")
    keyboard = build_main_menu(lang)
    await update.effective_message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=keyboard)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role="model", text=help_text)

# ... (все остальные заглушки)
async def handle_where_to_buy(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return

    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ru')
    symbol = payload.strip().upper()
    await update.effective_message.reply_text(
        get_text(lang, 'where_to_buy_search', symbol=symbol),
        parse_mode=constants.ParseMode.MARKDOWN,
    )

    try:
        pairs_task = coinmarketcap_client.get_market_pairs(symbol)
        price_task = binance_client.get_price(f"{symbol}USDT")
        pairs, binance_price = await asyncio.gather(pairs_task, price_task)

        lines = [get_text(lang, 'where_to_buy_header', symbol=symbol)]
        if pairs:
            for p in pairs:
                price = p.get("price")
                price_text = f"${price:,.2f}" if price else "N/A"
                fee = "0.1%" if (p.get("exchange") or "").lower() == "binance" else "—"
                link = f"[ссылка]({p['url']})" if p.get("url") else ""
                lines.append(
                    get_text(lang, 'where_to_buy_exchange_line', exchange=p.get('exchange'), price=price_text, fee=fee, link=link)
                )
        if binance_price and not any((p.get("exchange") or "").lower() == "binance" for p in (pairs or [])):
            binance_link = f"https://www.binance.com/en/trade/{symbol}_USDT"
            lines.append(
                get_text(lang, 'where_to_buy_binance_line', price=f"{binance_price:,.2f}", link=binance_link)
            )

        response = "\n".join(lines)
        await update.effective_message.reply_text(
            response,
            parse_mode=constants.ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response)

    except Exception as e:
        logger.error(
            f"Ошибка в handle_where_to_buy для {user_id} и символа {symbol}: {e}",
            exc_info=True,
        )
        error_text = get_text(lang, 'where_to_buy_error')
        await update.effective_message.reply_text(error_text)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=error_text)
async def handle_premarket_scan(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    lang = context.user_data.get('lang', 'ru')
    await update.effective_message.reply_text(
        get_text(lang, 'premarket_scanning'),
        parse_mode=constants.ParseMode.MARKDOWN,
    )

    # --- Проверяем подписку пользователя ---
    subscription = await db_ops.get_subscription(db_session, update.effective_user.id)
    if not subscription or not subscription.is_active:
        reminder = get_text(lang, 'subscription_reminder')
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(get_text(lang, 'subscribe_button'), callback_data='/subscribe')]]
        )
        await update.effective_message.reply_text(reminder, reply_markup=kb)
        return

    params = {}
    for part in payload.split():
        if '=' in part:
            key, value = part.split('=', 1)
            params[key.lower()] = value

    event_type = params.get('type')
    min_cap = float(params.get('mincap', 0) or 0)
    max_cap = float(params['maxcap']) if 'maxcap' in params else None

    events = await get_premarket_signals(
        vip=bool(subscription and subscription.is_active and subscription.level == 'premium'),
        event_type=event_type,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
    )
    if not events:
        response = get_text(lang, 'premarket_no_data')
    else:
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
        response = get_text(lang, 'premarket_header') + "\n" + "\n".join(lines)

    await update.effective_message.reply_text(
        response,
        parse_mode=constants.ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    await db_ops.add_chat_message(
        session=db_session,
        user_id=update.effective_user.id,
        role='model',
        text=response,
    )
async def handle_edu_lesson(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Отправляет краткое определение крипто-термина и предлагает мини‑курсы."""
    if not update.effective_message:
        return

    from education import get_definition, list_courses

    await db_ops.increment_request_counter(db_session, update.effective_user.id, "lesson_requests")

    lang = context.user_data.get('lang', 'ru')
    term_definition = get_definition(payload)

    if term_definition:
        response = f"📚 *{payload.upper()}* — {term_definition}"
    else:
        response = get_text(lang, 'edu_unknown', topic=payload)

    await update.effective_message.reply_text(
        response, parse_mode=constants.ParseMode.MARKDOWN
    )

    # Небольшое предложение о дополнительных курсах
    courses = list_courses()
    if courses:
        course_lines = [f"• {c.title} — {c.stars_price}⭐" for c in courses]
        offer = get_text(lang, 'course_offer', courses="\n".join(course_lines))
        await update.effective_message.reply_text(
            offer, parse_mode=constants.ParseMode.MARKDOWN
        )

async def handle_shop(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Показывает пользователю каталог цифровых товаров."""
    lang = context.user_data.get('lang', 'ru')
    products = await db_ops.list_products(db_session)
    if not products:
        await update.effective_message.reply_text(get_text(lang, 'shop_empty'))
        return
    lines = [get_text(lang, 'shop_header')]
    for p in products:
        short_desc = p.description.splitlines()[0]
        if len(short_desc) > 80:
            short_desc = short_desc[:77] + '...'
        info = f"{p.id}. *{p.name}* — {p.stars_price}⭐"
        extra = f"({p.item_type}, {p.rating}⭐)"
        lines.append(f"{info} {extra}\n_{short_desc}_")
    lines.append(get_text(lang, 'shop_hint'))
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN
    )

async def handle_buy_product(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Покупает товар по его ID через stars_form."""
    lang = context.user_data.get('lang', 'ru')
    if not is_valid_id(payload):
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))
        return
    product_id = int(payload)
    product = await db_ops.get_product(db_session, product_id)
    if not product:
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))
        return
    if await db_ops.has_purchased(db_session, update.effective_user.id, product_id):
        await update.effective_message.reply_text(get_text(lang, 'product_already_owned'))
        return
    try:
        await send_payment_invoice(update, context, f"product-{product_id}", product.stars_price, product.name)
        context.user_data['pending_product_purchase'] = product_id
        await update.effective_message.reply_text(get_text(lang, "purchase_open_form"))
    except Exception as e:
        logger.error(f"Payment failed for {update.effective_user.id}: {e}")
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))
        return

    # дальнейшая обработка после успешной оплаты происходит в handle_stars_payment


async def handle_buy_report(update: Update, context: CallbackContext, db_session: AsyncSession):
    """Initiate purchase of an extended report via Telegram Stars."""
    lang = context.user_data.get('lang', 'ru')
    try:
        await send_payment_invoice(update, context, 'report', 100, 'Расширенный отчет')
        await update.effective_message.reply_text(
            get_text(lang, 'purchase_open_form')
        )
    except Exception as e:
        logger.error(f"Report payment failed for {update.effective_user.id}: {e}")
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))


async def handle_course_command(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Команды управления курсами."""
    lang = context.user_data.get('lang', 'ru')
    parts = payload.split()
    subcmd = parts[0].lower() if parts else 'list'

    if subcmd == 'list':
        courses = await db_ops.list_courses(db_session)
        if not courses:
            await update.effective_message.reply_text(get_text(lang, 'course_empty'))
            return
        lines = [get_text(lang, 'course_list_header')]
        for c in courses:
            price = f"{c.stars_price}⭐" if c.stars_price > 0 else get_text(lang, 'course_free')
            lines.append(f"{c.id}. *{c.title}* — {price}")
        lines.append(get_text(lang, 'course_list_hint'))
        await update.effective_message.reply_text('\n'.join(lines), parse_mode=constants.ParseMode.MARKDOWN)
        return

    if subcmd == 'info' and len(parts) >= 2:
        course_id = int(parts[1]) if parts[1].isdigit() else None
        if not course_id:
            await update.effective_message.reply_text(get_text(lang, 'course_not_found'))
            return
        course = await db_ops.get_course(db_session, course_id)
        if not course:
            await update.effective_message.reply_text(get_text(lang, 'course_not_found'))
            return
        price = f"{course.stars_price}⭐" if course.stars_price > 0 else get_text(lang, 'course_free')
        text = f"*{course.title}* — {price}\n{course.description}"
        await update.effective_message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)
        return

    if subcmd == 'buy' and len(parts) >= 2:
        course_id = int(parts[1]) if parts[1].isdigit() else None
        if not course_id:
            await update.effective_message.reply_text(get_text(lang, 'course_not_found'))
            return
        course = await db_ops.get_course(db_session, course_id)
        if not course:
            await update.effective_message.reply_text(get_text(lang, 'course_not_found'))
            return
        if await db_ops.has_purchased_course(db_session, update.effective_user.id, course_id):
            await update.effective_message.reply_text(get_text(lang, 'course_already_owned'))
        else:
            if course.stars_price > 0:
                await send_payment_invoice(
                    update,
                    context,
                    f"course-{course_id}",
                    course.stars_price,
                    course.title,
                )
            await db_ops.add_course_purchase(db_session, update.effective_user.id, course_id)
            await db_ops.add_chat_message(
                session=db_session,
                user_id=update.effective_user.id,
                role='system',
                text=f'course purchase {course.title}',
                event='purchase'
            )
            await update.effective_message.reply_text(get_text(lang, 'course_purchased', title=course.title), parse_mode=constants.ParseMode.MARKDOWN)

        if course.content_type == 'text' and course.file_id:
            await update.effective_message.reply_text(course.file_id)
        elif course.content_type == 'text':
            await update.effective_message.reply_text(course.description)
        elif course.file_id:
            try:
                with open(course.file_id, 'rb') as f:
                    await update.effective_message.reply_document(f)
            except Exception:
                await update.effective_message.reply_text(get_text(lang, 'course_send_error'))
        return


async def handle_feedback(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Сохраняет отзыв пользователя."""
    lang = context.user_data.get('lang', 'ru')
    text = payload.strip()
    if not text:
        await update.effective_message.reply_text(get_text(lang, 'feedback_prompt'))
        return
    await db_ops.add_feedback(db_session, update.effective_user.id, text)
    await update.effective_message.reply_text(get_text(lang, 'feedback_thanks'))


async def handle_recommend(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Отправляет персональные рекомендации пользователю."""
    if not update.effective_message:
        return

    from ai.recommender import generate_recommendations

    lang = context.user_data.get('lang', 'ru')
    recs = await generate_recommendations(db_session, update.effective_user.id)

    if not recs:
        await update.effective_message.reply_text(get_text(lang, 'recommend_none'))
        return

    lines = [get_text(lang, 'recommend_header')]
    for r in recs:
        if r[0] == 'subscribe':
            lines.append(get_text(lang, 'recommend_subscription'))
        elif r[0] == 'renew':
            lines.append(get_text(lang, 'recommend_renew', date=r[1]))
        elif r[0] == 'course':
            price = f"{r[3]}⭐" if r[3] > 0 else get_text(lang, 'course_free')
            lines.append(get_text(lang, 'recommend_course', id=r[1], title=r[2], price=price))
        elif r[0] == 'product':
            lines.append(get_text(lang, 'recommend_product', id=r[1], name=r[2], price=f"{r[3]}⭐"))

    await update.effective_message.reply_text('\n'.join(lines), parse_mode=constants.ParseMode.MARKDOWN)


async def handle_admin_command(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Простейшая административная панель в чате."""
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if not admin_id or str(update.effective_user.id) != str(admin_id):
        await update.effective_message.reply_text("Access denied")
        return

    parts = payload.split()
    if not parts:
        await update.effective_message.reply_text(
            "Commands: users, stats <id>, products, courses, feedback, analytics"
        )
        return

    cmd = parts[0]
    if cmd == "users":
        users = await db_ops.list_recent_users(db_session, 10)
        lines = [f"{u.id} | {u.username}" for u in users]
        await update.effective_message.reply_text("Users:\n" + "\n".join(lines))
    elif cmd == "stats" and len(parts) > 1:
        uid = int(parts[1])
        user = await db_ops.get_user(db_session, uid)
        if not user:
            await update.effective_message.reply_text("User not found")
            return
        stats = await db_ops.get_user_stats(db_session, uid)
        purchases = await db_ops.list_user_purchases(db_session, uid)
        lines = [
            f"User: {user.id} {user.username}",
            f"Stats: {stats}",
            "Purchases: " + ", ".join(str(p.product_id) for p in purchases) or "none",
        ]
        await update.effective_message.reply_text("\n".join(lines))
    elif cmd == "products":
        products = await db_ops.list_products(db_session)
        lines = [f"{p.id}. {p.name} ({p.stars_price}⭐)" for p in products]
        await update.effective_message.reply_text("Products:\n" + "\n".join(lines))
    elif cmd == "courses":
        courses = await db_ops.list_courses(db_session)
        lines = [f"{c.id}. {c.title} ({c.stars_price}⭐)" for c in courses]
        await update.effective_message.reply_text("Courses:\n" + "\n".join(lines))
    elif cmd == "feedback":
        msgs = await db_ops.get_feedback_messages(db_session, 10)
        lines = [f"{m.user_id}: {m.message_text}" for m in msgs]
        await update.effective_message.reply_text("Feedback:\n" + "\n".join(lines))
    elif cmd == "analytics":
        metrics = await gather_metrics(db_session)
        top_products = await db_ops.get_most_purchased_products(db_session, 3)
        top_requests = await db_ops.get_top_request_types(db_session, 3)
        new_subs = await db_ops.new_subscriptions_count(db_session)
        lost = await db_ops.inactive_users_count(db_session)
        lines = [
            f"Active users: {metrics['active_users']}",
            f"Purchase freq: {metrics['purchase_frequency']:.2f}",
            f"Subscriptions active: {metrics['subscriptions']['active']}/{metrics['subscriptions']['total']}",
            f"New subs today: {new_subs}",
            f"Inactive users: {lost}",
            "Popular products:" + ", ".join(f"{n} ({c})" for n, c in top_products),
            "Top requests:" + ", ".join(f"{n} ({c})" for n, c in top_requests),
        ]
        await update.effective_message.reply_text("\n".join(lines))
    else:
        await update.effective_message.reply_text("Unknown admin command")


async def handle_my_subscription(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Inform user about subscription end date."""
    lang = context.user_data.get('lang', 'ru')
    date_str = await db_ops.get_subscription_end_date(db_session, update.effective_user.id)
    if date_str:
        await update.effective_message.reply_text(get_text(lang, 'subscription_until', date=date_str))
    else:
        await update.effective_message.reply_text(get_text(lang, 'subscription_none'))


async def admin_stats(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    user_id = update.effective_user.id
    if ADMIN_ID and user_id != ADMIN_ID:
        return
    total_users = await db_ops.total_users(db_session)
    active_subs = len(await db_ops.get_active_subscriptions(db_session))
    await update.effective_message.reply_text(
        f"\uD83D\uDCCA Stats:\nUsers: {total_users}\nActive subs: {active_subs}"
    )


async def broadcast_command(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    user_id = update.effective_user.id
    if ADMIN_ID and user_id != ADMIN_ID:
        return
    text_to_send = payload.strip()
    if not text_to_send:
        await update.effective_message.reply_text("Usage: /broadcast <message>")
        return
    users = await db_ops.list_recent_users(db_session, 1000000)
    for u in users:
        try:
            await context.bot.send_message(u.id, text_to_send)
        except Exception:
            pass
    await update.effective_message.reply_text("Broadcast started.")


async def handle_subscribe(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Открывает форму оплаты подписки через Telegram Payments."""
    lang = context.user_data.get('lang', 'ru')
    level = 'premium' if 'premium' in payload.lower() else 'basic'
    await db_ops.create_or_update_subscription(db_session, update.effective_user.id, is_active=False, level=level)

    try:
        await send_subscription_invoice(update, context, SUBSCRIPTION_PRICE)
        await update.effective_message.reply_text(
            get_text(lang, 'subscribe_info'),
            parse_mode=constants.ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Subscription payment failed for {update.effective_user.id}: {e}")
        await update.effective_message.reply_text(get_text(lang, 'subscription_link_missing'))

async def handle_stars_payment(update: Update, context: CallbackContext, db_session: AsyncSession):
    """Обновляет статус подписки после оплаты звёздами."""
    user_id = update.effective_user.id
    try:
        status = await context.bot._post(
            'payments.getStarsStatus',
            data={'user_id': user_id},
        )
        active = bool(status.get('active')) if isinstance(status, dict) else False
        next_ts = status.get('next_payment_date') if isinstance(status, dict) else None
        next_payment = datetime.fromtimestamp(next_ts) if next_ts else None
        sub = await db_ops.get_subscription(db_session, user_id)
        level = sub.level if sub else 'basic'
        await db_ops.create_or_update_subscription(
            db_session,
            user_id,
            is_active=active,
            next_payment=next_payment,
            level=level,
        )
        if active and next_payment:
            schedule_subscription_reminder(user_id, next_payment)

        stars_info = getattr(update.effective_message, 'stars', None)
        if stars_info:
            amount = getattr(stars_info, 'total_amount', None) or getattr(stars_info, 'amount', 0)
            if isinstance(amount, (int, float)) and amount:
                await db_ops.add_stars(db_session, user_id, int(amount))
        await db_ops.add_chat_message(
            session=db_session,
            user_id=user_id,
            role='system',
            text='subscription update',
            event='subscription'
        )
        channel_id = os.getenv('PRIVATE_CHANNEL_ID')
        if active and channel_id:
            try:
                await context.bot.unban_chat_member(channel_id, user_id)
                invite = await context.bot.export_chat_invite_link(channel_id)
                lang = context.user_data.get('lang', 'ru')
                msg = get_text(lang, 'subscription_access_granted', link=invite)
                await context.bot.send_message(user_id, msg, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f'Failed to grant channel access for {user_id}: {e}')

        pending_product = context.user_data.pop('pending_product_purchase', None)
        if pending_product:
            product = await db_ops.get_product(db_session, pending_product)
            if product and not await db_ops.has_purchased(db_session, user_id, pending_product):
                await db_ops.add_purchase(db_session, user_id, pending_product)
                await db_ops.add_chat_message(
                    session=db_session,
                    user_id=user_id,
                    role='system',
                    text=f'purchased {product.name}',
                    event='purchase'
                )
                await context.bot.send_message(
                    user_id,
                    get_text(context.user_data.get('lang', 'ru'), 'purchase_success', product=product.name),
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
                try:
                    if product.content_type == 'text':
                        await context.bot.send_message(user_id, product.content_value)
                    elif product.content_type == 'file':
                        with open(product.content_value, 'rb') as f:
                            await context.bot.send_document(user_id, f)
                except Exception as e:
                    logger.error(f'Delivery failed for {user_id}: {e}')
    except Exception as e:
        logger.error(f'Failed to update subscription for {user_id}: {e}')

async def handle_invoice_payment(update: Update, context: CallbackContext, db_session: AsyncSession):
    """Обрабатывает успешную оплату через Telegram Payments."""
    user_id = update.effective_user.id
    try:
        payload = ''
        if update.effective_message.successful_payment:
            payload = update.effective_message.successful_payment.invoice_payload or ''

        if 'subscription' in payload:
            next_payment = datetime.now(timezone.utc) + timedelta(days=30)
            level = 'premium' if 'premium' in payload else 'basic'
            await db_ops.create_or_update_subscription(
                db_session,
                user_id,
                is_active=True,
                next_payment=next_payment,
                level=level,
            )
            schedule_subscription_reminder(user_id, next_payment)
            await db_ops.add_chat_message(
                session=db_session,
                user_id=user_id,
                role='system',
                text='subscription update',
                event='subscription',
            )
            channel_id = os.getenv('PRIVATE_CHANNEL_ID')
            if channel_id:
                try:
                    await context.bot.unban_chat_member(channel_id, user_id)
                    invite = await context.bot.export_chat_invite_link(channel_id)
                    lang = context.user_data.get('lang', 'ru')
                    msg = get_text(lang, 'subscription_access_granted', link=invite)
                    await context.bot.send_message(
                        user_id,
                        msg,
                        parse_mode=constants.ParseMode.MARKDOWN,
                    )
                except Exception as e:
                    logger.error(f'Failed to grant channel access for {user_id}: {e}')

        pending_product = context.user_data.pop('pending_product_purchase', None)
        if pending_product:
            product = await db_ops.get_product(db_session, pending_product)
            if product and not await db_ops.has_purchased(db_session, user_id, pending_product):
                await db_ops.add_purchase(db_session, user_id, pending_product)
                await db_ops.add_chat_message(
                    session=db_session,
                    user_id=user_id,
                    role='system',
                    text=f'purchased {product.name}',
                    event='purchase',
                )
                await context.bot.send_message(
                    user_id,
                    get_text(context.user_data.get('lang', 'ru'), 'purchase_success', product=product.name),
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
                try:
                    if product.content_type == 'text':
                        await context.bot.send_message(user_id, product.content_value)
                    elif product.content_type == 'file':
                        with open(product.content_value, 'rb') as f:
                            await context.bot.send_document(user_id, f)
                except Exception as e:
                    logger.error(f'Delivery failed for {user_id}: {e}')
    except Exception as e:
        logger.error(f'Failed to process payment for {user_id}: {e}')
async def handle_track_coin(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    lang = context.user_data.get('lang', 'ru')
    if not payload or not is_valid_symbol(payload):
        await update.effective_message.reply_text(get_text(lang, 'track_missing_symbol'))
        return
    await handle_portfolio_summary(update, context, f"add {payload}", db_session)
async def handle_untrack_coin(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    lang = context.user_data.get('lang', 'ru')
    if not payload or not is_valid_symbol(payload):
        await update.effective_message.reply_text(get_text(lang, 'track_missing_symbol'))
        return
    await handle_portfolio_summary(update, context, f"remove {payload}", db_session)
async def handle_portfolio_summary(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return

    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ru')
    parts = payload.split()
    action = parts[0].lower() if parts else "list"

    if action == "add" and len(parts) >= 2:
        symbol = parts[1]
        if not is_valid_symbol(symbol):
            await update.effective_message.reply_text(get_text(lang, 'track_missing_symbol'))
            return
        # Enforce free portfolio limit for non-subscribers
        portfolio = await db_ops.get_user_portfolio(db_session, user_id)
        subscription = await db_ops.get_subscription(db_session, user_id)
        if len(portfolio) >= MAX_FREE_PORTFOLIO_COINS and not (subscription and subscription.is_active):
            await update.effective_message.reply_text(
                get_text(lang, 'portfolio_limit', limit=MAX_FREE_PORTFOLIO_COINS)
            )
            return
        quantity = float(parts[2]) if len(parts) >= 3 else 0.0
        price = float(parts[3]) if len(parts) >= 4 else 0.0
        buy_date = None
        if len(parts) >= 5:
            try:
                buy_date = datetime.fromisoformat(parts[4])
            except Exception:
                buy_date = None
        await db_ops.add_coin_to_portfolio(db_session, user_id, symbol, quantity, price, buy_date)
        response = get_text(lang, 'portfolio_add', symbol=symbol.upper())

    elif action == "remove" and len(parts) >= 2:
        symbol = parts[1]
        if not is_valid_symbol(symbol):
            await update.effective_message.reply_text(get_text(lang, 'track_missing_symbol'))
            return
        removed = await db_ops.remove_coin_from_portfolio(db_session, user_id, symbol)
        response = get_text(lang, 'coin_removed') if removed else get_text(lang, "portfolio_coin_missing")

    elif action in ("chart", "charts", "graph"):
        portfolio = await db_ops.get_user_portfolio(db_session, user_id)
        if not portfolio:
            response = get_text(lang, 'portfolio_empty')
        else:
            await update.effective_message.reply_text(get_text(lang, 'portfolio_chart_start'))
            for coin in portfolio:
                chart_path = await create_price_chart(coin.coin_symbol)
                if chart_path:
                    with open(chart_path, "rb") as img:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id, photo=img
                        )
                    try:
                        os.remove(chart_path)
                    except OSError:
                        pass
            response = get_text(lang, 'portfolio_chart_sent')

    else:
        portfolio = await db_ops.get_user_portfolio(db_session, user_id)
        if not portfolio:
            response = get_text(lang, 'portfolio_empty')
        else:
            symbols = [c.coin_symbol for c in portfolio]
            coin_ids, _ = await get_coin_ids_from_symbols(symbols)
            price_data = await coingecko_client.get_simple_price(coin_ids)
            lines = [get_text(lang, 'portfolio_header')]
            total_value = 0.0
            data = []
            for coin in portfolio:
                coin_id = COIN_ID_MAP.get(coin.coin_symbol)
                price = price_data.get(coin_id, {}).get("usd", 0)
                value = (coin.quantity or 0) * price
                total_value += value
                profit = value - (coin.quantity or 0) * (coin.buy_price or 0)
                data.append((profit, coin, price))

            data.sort(key=lambda x: x[0], reverse=True)
            for profit, coin, price in data:
                pct = ((price - (coin.buy_price or 0)) / (coin.buy_price or 1)) * 100 if coin.buy_price else 0
                days = (
                    f" | { (datetime.now(timezone.utc) - coin.purchase_date).days }d" if coin.purchase_date else ""
                )
                lines.append(
                    f"• *{coin.coin_symbol}*: {coin.quantity:g} шт. | текущая цена ${price:,.2f} | P/L ${profit:,.2f} ({pct:+.2f}%)" + days
                )

            lines.append(f"\nВсего: ${total_value:,.2f}")
            response = "\n".join(lines)

    await update.effective_message.reply_text(response, parse_mode=constants.ParseMode.MARKDOWN)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response)


async def get_symbol_from_context(session: AsyncSession, user_id: int) -> str | None:
    """Извлекает последний упомянутый символ из истории чата."""
    history = await db_ops.get_chat_history(session, user_id, limit=4)
    for msg in reversed(history):
        if msg.role == 'model':
            # Ищем тикеры, выделенные жирным шрифтом в сообщениях бота
            found = re.findall(r'\*([A-Z]{2,5})\*', msg.message_text)
            if found:
                logger.info(f"Найден символ в контексте: {found[0]}")
                return found[0]
    return None

async def handle_update(update: Update, context: CallbackContext, db_session: AsyncSession):
    if update.callback_query:
        if update.callback_query.data == 'buy_report':
            await handle_buy_report(update, context, db_session)
        else:
            await update.callback_query.answer()
        return
    if update.pre_checkout_query:
        await context.bot.answer_pre_checkout_query(update.pre_checkout_query.id, ok=True)
        return

    message = update.effective_message
    user = update.effective_user
    if not user or not message or user.is_bot or user.id == getattr(context.bot, 'id', None):
        return

    if getattr(message, 'successful_payment', None):
        await handle_invoice_payment(update, context, db_session)
        return
    if getattr(message, 'stars', None):
        await handle_stars_payment(update, context, db_session)
        return

    if not message.text:
        return

    user_input = message.text.strip()
    if not user_input:
        return

    db_user = await db_ops.get_or_create_user(session=db_session, tg_user=user)
    logger.info(f"Обработка сообщения от {db_user.id}: '{user_input}'")
    context.user_data['lang'] = db_user.language
    context.user_data['recommendations_enabled'] = getattr(db_user, 'show_recommendations', True)
    lang = context.user_data.get('lang', 'ru')

    # Check daily free message limit
    subscription = await db_ops.get_subscription(db_session, user.id)
    msg_count = await db_ops.count_user_messages_today(db_session, user.id)
    if msg_count >= DAILY_FREE_MESSAGES and not (subscription and subscription.is_active):
        limit_text = get_text(lang, 'free_daily_limit', limit=DAILY_FREE_MESSAGES)
        await message.reply_text(limit_text)
        await db_ops.add_chat_message(session=db_session, user_id=user.id, role='model', text=limit_text)
        return

    dialog = await db_ops.start_dialog(db_session, user.id)
    user_msg = await db_ops.add_chat_message(
        session=db_session,
        user_id=user.id,
        role='user',
        text=user_input,
        dialog_id=dialog.id,
    )

    # Считаем сообщения для подсказки по популярным темам
    hint_state = context.user_data.get('top_topics_hint', {})
    if hint_state.get('dialog_id') != dialog.id:
        hint_state = {'dialog_id': dialog.id, 'counter': 0, 'last_shown': None}
    else:
        hint_state['counter'] = hint_state.get('counter', 0) + 1
    context.user_data['top_topics_hint'] = hint_state

    # --- Обработка встроенных команд БЕЗ AI ---
    hardcoded_commands = {
        '/start': handle_bot_help,
        '/help': handle_bot_help,
        '/portfolio': handle_portfolio_summary,
        '/alerts': handle_manage_alerts,
        '/lang': handle_change_language,
        '/settings': handle_settings_command,
        '/shop': handle_shop,
        '/buy': handle_buy_product,
        '/subscribe': handle_subscribe,
        '/course': handle_course_command,
        '/feedback': handle_feedback,
        '/hints': handle_hints_command,
        '/recommend': handle_recommend,
        '/admin': handle_admin_command,
        '/my_subscription': handle_my_subscription,
        '/stats': admin_stats,
        '/broadcast': broadcast_command,
        '/defi': handle_defi_farming,
        '/nft': handle_nft_analytics,
        '/depin': handle_depin_projects,
        '/news': handle_news_command,
        '/predict': handle_predict_command,
    }
    for cmd, func in hardcoded_commands.items():
        if user_input.lower().startswith(cmd):
            arg = user_input[len(cmd):].strip()
            logger.info(f"Обработка жестко заданной команды: {cmd}")
            await func(update, context, arg, db_session)
            return

    if user_input.startswith('/'):
        # Нераспознанная команда
        await handle_unsupported_request(update, context, '', db_session)
        return

    start_ts = datetime.now(timezone.utc)
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=constants.ChatAction.TYPING)
        
        # Шаг 1: Классификация
        intent = await classify_intent(user_input)
        logger.info(f"Шаг 1: Намерение определено как '{intent}'")
        if not dialog.topic:
            await db_ops.update_dialog(db_session, dialog.id, topic=intent)
        top_topics = await db_ops.get_top_user_topics(db_session, user.id)
        hint_state = context.user_data.get('top_topics_hint', {})
        now_ts = datetime.now(timezone.utc).timestamp()
        last_ts = hint_state.get('last_shown')
        allow_hint = (
            last_ts is None
            or now_ts - last_ts >= TOP_TOPICS_HINT_COOLDOWN
            or hint_state.get('counter', 0) >= TOP_TOPICS_HINT_LIMIT
        )
        if top_topics and context.user_data.get('recommendations_enabled', True) and allow_hint:
            hint = get_text(lang, 'top_topics_hint', topics=", ".join(top_topics))
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(get_text(lang, 'full_report_btn'), callback_data='buy_report')]]
            )
            await message.reply_text(hint, reply_markup=kb)
            hint_state['last_shown'] = now_ts
            hint_state['counter'] = 0
            context.user_data['top_topics_hint'] = hint_state

        # Шаг 2: Извлечение данных
        entities = await extract_entities(intent, user_input)
        await db_ops.update_chat_message(db_session, user_msg.id, request_type=intent, entities=str(entities))
        logger.info(f"Шаг 2: Извлечены данные: {entities}")

        payload = next(iter(entities.values()))

        # --- НОВАЯ ЛОГИКА: Расширенная проверка контекста ---
        intents_needing_context = ["CRYPTO_INFO", "TOKEN_ANALYSIS", "WHERE_TO_BUY"]
        pronouns = ['его', 'ее', 'их', 'него', 'о нем']
        if intent in intents_needing_context and any(p in user_input.lower() for p in pronouns):
            context_symbol = await get_symbol_from_context(db_session, user.id)
            if context_symbol:
                payload = context_symbol
                logger.info(f"Контекст применен. Новый payload: {payload}")

        handler = router.get(intent) or handle_unsupported_request
        await handler(update, context, payload, db_session)
        duration = int((datetime.now(timezone.utc) - start_ts).total_seconds() * 1000)
        await db_ops.update_chat_message(db_session, user_msg.id, duration_ms=duration)

    except Exception as e:
        logger.error(
            f"Критическая ошибка для {user.id} при запросе '{user_input}': {e}",
            exc_info=True,
        )
        lang = context.user_data.get('lang', 'ru')
        await message.reply_text(get_text(lang, 'error_generic'))
        duration = int((datetime.now(timezone.utc) - start_ts).total_seconds() * 1000)
        await db_ops.update_chat_message(db_session, user_msg.id, duration_ms=duration, error=True)

# --- Регистрация обработчиков намерений ---
router.register("GENERAL_CHAT", handle_general_ai_conversation)
router.register("CRYPTO_INFO", handle_crypto_info_request)
router.register("TOKEN_ANALYSIS", handle_token_analysis)
router.register("WHERE_TO_BUY", handle_where_to_buy)
router.register("PREMARKET_SCAN", handle_premarket_scan)
router.register("EDU_LESSON", handle_edu_lesson)
router.register("SETUP_ALERT", handle_setup_alert)
router.register("MANAGE_ALERTS", handle_manage_alerts)
router.register("TRACK_COIN", handle_track_coin)
router.register("UNTRACK_COIN", handle_untrack_coin)
router.register("PORTFOLIO_SUMMARY", handle_portfolio_summary)
router.register("BOT_HELP", handle_bot_help)
router.register("DEFI_FARM", handle_defi_farming)
router.register("NFT_ANALYTICS", handle_nft_analytics)
router.register("DEPIN_PROJECTS", handle_depin_projects)
router.register("CRYPTO_NEWS", handle_news_command)
router.register("PRICE_PREDICTION", handle_predict_command)
router.register("SHOP_BUY", handle_buy_product)
router.register("SUBSCRIPTION", handle_subscribe)
router.register("COURSE_INFO", handle_course_command)
