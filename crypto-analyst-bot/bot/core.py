# bot/core.py
# Основной модуль логики бота с улучшенной обработкой контекста.

import logging
import os
import re
from datetime import datetime
from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from utils.validators import is_valid_id, is_valid_symbol

# --- Импорт всех модулей проекта ---
from ai.dispatcher import classify_intent, extract_entities
from database import operations as db_ops
from crypto.handler import handle_crypto_info_request
from settings.user import (
    handle_setup_alert,
    handle_manage_alerts,
    handle_change_language,
    handle_settings_command,
    MAX_FREE_PORTFOLIO_COINS,
)
from settings.messages import get_text
from ai.general import handle_general_ai_conversation
from analysis.handler import handle_token_analysis
from crypto.pre_market import get_premarket_signals
from utils.api_clients import coinmarketcap_client, binance_client
from utils.charts import create_price_chart

logger = logging.getLogger(__name__)
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
        pairs = await coinmarketcap_client.get_market_pairs(symbol)
        binance_price = await binance_client.get_price(f"{symbol}USDT")

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
        logger.error(f"Ошибка в handle_where_to_buy: {e}", exc_info=True)
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
        pay_link = os.getenv('SUBSCRIPTION_LINK')
        reminder = get_text(lang, 'subscription_reminder')
        if pay_link:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, 'subscribe_button'), url=pay_link)]])
            await update.effective_message.reply_text(reminder, reply_markup=kb)
        else:
            await update.effective_message.reply_text(reminder)
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
        await context.bot._post(
            "payments.sendStarsForm",
            data={"user_id": update.effective_user.id, "amount": product.stars_price, "description": product.name},
        )
        context.user_data['pending_product_purchase'] = product_id
        await update.effective_message.reply_text(get_text(lang, "purchase_open_form"))
    except Exception as e:
        logger.error(f"Payment failed for {update.effective_user.id}: {e}")
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))
        try:
            await context.bot._post(
                "payments.refund",
                data={"user_id": update.effective_user.id, "amount": product.stars_price},
            )
            await update.effective_message.reply_text(get_text(lang, 'purchase_refund'))
        except Exception as r_err:
            logger.error(f"Refund failed for {update.effective_user.id}: {r_err}")
        return

    # дальнейшая обработка после успешной оплаты происходит в handle_stars_payment


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
                await context.bot._post(
                    'payments.sendStarsForm',
                    data={"user_id": update.effective_user.id, "amount": course.stars_price, "description": course.title},
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


async def handle_subscribe(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Отправляет ссылку на оплату подписки через звёзды."""
    lang = context.user_data.get('lang', 'ru')
    pay_link = os.getenv('SUBSCRIPTION_LINK')
    if not pay_link:
        await update.effective_message.reply_text(get_text(lang, 'subscription_link_missing'))
        return

    level = 'premium' if 'premium' in payload.lower() else 'basic'
    await db_ops.create_or_update_subscription(db_session, update.effective_user.id, is_active=False, level=level)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(get_text(lang, 'subscribe_button'), url=pay_link)]]
    )
    await update.effective_message.reply_text(
        get_text(lang, 'subscribe_info'),
        reply_markup=keyboard,
        parse_mode=constants.ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )

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
                        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img)
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
                    f" | { (datetime.utcnow() - coin.purchase_date).days }d" if coin.purchase_date else ""
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
    message = update.effective_message
    user = update.effective_user
    if not user or not message:
        return

    if getattr(message, 'successful_payment', None) or getattr(message, 'stars', None):
        await handle_stars_payment(update, context, db_session)
        return

    if not message.text:
        return

    user_input = message.text.strip()
    db_user = await db_ops.get_or_create_user(session=db_session, tg_user=user)
    logger.info(f"Обработка сообщения от {db_user.id}: '{user_input}'")
    context.user_data['lang'] = db_user.language
    lang = context.user_data.get('lang', 'ru')

    dialog = await db_ops.start_dialog(db_session, user.id)
    user_msg = await db_ops.add_chat_message(
        session=db_session,
        user_id=user.id,
        role='user',
        text=user_input,
        dialog_id=dialog.id,
    )

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
        '/recommend': handle_recommend,
    }
    for cmd, func in hardcoded_commands.items():
        if user_input.lower().startswith(cmd):
            arg = user_input[len(cmd):].strip()
            logger.info(f"Обработка жестко заданной команды: {cmd}")
            await func(update, context, arg, db_session)
            return

    start_ts = datetime.utcnow()
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=constants.ChatAction.TYPING)
        
        # Шаг 1: Классификация
        intent = await classify_intent(user_input)
        logger.info(f"Шаг 1: Намерение определено как '{intent}'")
        if not dialog.topic:
            await db_ops.update_dialog(db_session, dialog.id, topic=intent)
        top_topics = await db_ops.get_top_user_topics(db_session, user.id)
        if top_topics:
            hint = get_text(lang, 'top_topics_hint', topics=", ".join(top_topics))
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(get_text(lang, 'full_report_btn'), callback_data='buy_report')]]
            )
            await message.reply_text(hint, reply_markup=kb)

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

        handlers = {
            "GENERAL_CHAT": handle_general_ai_conversation,
            "CRYPTO_INFO": handle_crypto_info_request,
            "TOKEN_ANALYSIS": handle_token_analysis,
            "WHERE_TO_BUY": handle_where_to_buy,
            "PREMARKET_SCAN": handle_premarket_scan,
            "EDU_LESSON": handle_edu_lesson,
            "SETUP_ALERT": handle_setup_alert,
            "MANAGE_ALERTS": handle_manage_alerts,
            "TRACK_COIN": handle_track_coin,
            "UNTRACK_COIN": handle_untrack_coin,
            "PORTFOLIO_SUMMARY": handle_portfolio_summary,
            "BOT_HELP": handle_bot_help,
        }
        
        handler = handlers.get(intent, handle_unsupported_request)
        await handler(update, context, payload, db_session)
        duration = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
        await db_ops.update_chat_message(db_session, user_msg.id, duration_ms=duration)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        lang = context.user_data.get('lang', 'ru')
        await message.reply_text(get_text(lang, 'error_generic'))
        duration = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
        await db_ops.update_chat_message(db_session, user_msg.id, duration_ms=duration, error=True)