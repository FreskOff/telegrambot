# bot/core.py
# Основной модуль логики бота с улучшенной обработкой контекста.

import logging
import os
import re
from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

# --- Импорт всех модулей проекта ---
from ai.dispatcher import classify_intent, extract_entities
from database import operations as db_ops
from crypto.handler import handle_crypto_info_request
from settings.user import (
    handle_setup_alert,
    handle_manage_alerts,
    handle_change_language,
    handle_settings_command,
)
from settings.messages import get_text
from ai.general import handle_general_ai_conversation
from analysis.handler import handle_token_analysis
from crypto.pre_market import get_premarket_signals
from utils.api_clients import coinmarketcap_client, binance_client

logger = logging.getLogger(__name__)

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
    lang = context.user_data.get('lang', 'ru')
    lang = context.user_data.get('lang', 'ru')
    help_text = get_text(lang, 'bot_help')
    await update.effective_message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=help_text)

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

    events = await get_premarket_signals()
    if not events:
        response = get_text(lang, 'premarket_no_data')
    else:
        lines = []
        for e in events:
            name = e.get("token_name")
            symbol = f"({e['symbol']})" if e.get("symbol") else ""
            date = f" - {e['event_date']}" if e.get("event_date") else ""
            lines.append(f"• *{name}* {symbol} — {e['event_type']}{date}")
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
        lines.append(f"{p.id}. *{p.name}* — {p.stars_price}⭐")
    lines.append(get_text(lang, 'shop_hint'))
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN
    )

async def handle_buy_product(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Покупает товар по его ID через stars_form."""
    lang = context.user_data.get('lang', 'ru')
    if not payload.isdigit():
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))
        return
    product_id = int(payload)
    product = await db_ops.get_product(db_session, product_id)
    if not product:
        await update.effective_message.reply_text(get_text(lang, 'purchase_error'))
        return
    await context.bot._post(
        "payments.sendStarsForm",
        data={"user_id": update.effective_user.id, "amount": product.stars_price, "description": product.name},
    )
    await db_ops.add_purchase(db_session, update.effective_user.id, product_id)
    await update.effective_message.reply_text(
        get_text(lang, 'purchase_success', product=product.name),
        parse_mode=constants.ParseMode.MARKDOWN,
    )
    if product.content_type == "text":
        await update.effective_message.reply_text(product.content_value)
    elif product.content_type == "file":
        with open(product.content_value, "rb") as f:
            await update.effective_message.reply_document(f)


async def handle_subscribe(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Отправляет ссылку на оплату подписки через звёзды."""
    lang = context.user_data.get('lang', 'ru')
    pay_link = os.getenv('SUBSCRIPTION_LINK')
    if not pay_link:
        await update.effective_message.reply_text('Subscription link not configured.')
        return

    await db_ops.create_or_update_subscription(db_session, update.effective_user.id, is_active=False)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(get_text(lang, 'subscribe_button'), url=pay_link)]]
    )
    await update.effective_message.reply_text(
        get_text(lang, 'subscribe_info'),
        reply_markup=keyboard,
        parse_mode=constants.ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
async def handle_track_coin(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    lang = context.user_data.get('lang', 'ru')
    if not payload:
        await update.effective_message.reply_text(get_text(lang, 'track_missing_symbol'))
        return
    await handle_portfolio_summary(update, context, f"add {payload}", db_session)
async def handle_untrack_coin(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    lang = context.user_data.get('lang', 'ru')
    if not payload:
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
        quantity = float(parts[2]) if len(parts) >= 3 else 0.0
        price = float(parts[3]) if len(parts) >= 4 else 0.0
        await db_ops.add_coin_to_portfolio(db_session, user_id, symbol, quantity, price)
        response = get_text(lang, 'portfolio_add', symbol=symbol.upper())

    elif action == "remove" and len(parts) >= 2:
        symbol = parts[1]
        removed = await db_ops.remove_coin_from_portfolio(db_session, user_id, symbol)
        response = get_text(lang, 'coin_removed') if removed else "Монета не найдена в портфеле."

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
            for coin in portfolio:
                coin_id = COIN_ID_MAP.get(coin.coin_symbol)
                price = price_data.get(coin_id, {}).get("usd", 0)
                value = (coin.quantity or 0) * price
                total_value += value
                profit = value - (coin.quantity or 0) * (coin.buy_price or 0)
                lines.append(
                    f"• *{coin.coin_symbol}*: {coin.quantity:g} шт. | текущая цена ${price:,.2f} | P/L ${profit:,.2f}"
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
    if not user or not message or not message.text: return

    user_input = message.text.strip()
    db_user = await db_ops.get_or_create_user(session=db_session, tg_user=user)
    logger.info(f"Обработка сообщения от {db_user.id}: '{user_input}'")
    context.user_data['lang'] = db_user.language
    
    await db_ops.add_chat_message(session=db_session, user_id=user.id, role='user', text=user_input)

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
    }
    for cmd, func in hardcoded_commands.items():
        if user_input.lower().startswith(cmd):
            arg = user_input[len(cmd):].strip()
            logger.info(f"Обработка жестко заданной команды: {cmd}")
            await func(update, context, arg, db_session)
            return

    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=constants.ChatAction.TYPING)
        
        # Шаг 1: Классификация
        intent = await classify_intent(user_input)
        logger.info(f"Шаг 1: Намерение определено как '{intent}'")

        # Шаг 2: Извлечение данных
        entities = await extract_entities(intent, user_input)
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

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        lang = context.user_data.get('lang', 'ru')
        await message.reply_text(get_text(lang, 'error_generic'))