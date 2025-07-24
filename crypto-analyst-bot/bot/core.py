# bot/core.py
# Основной модуль логики бота с улучшенной обработкой контекста.

import logging
import re
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

# --- Импорт всех модулей проекта ---
from ai.dispatcher import classify_intent, extract_entities
from database import operations as db_ops
from crypto.handler import handle_crypto_info_request
from settings.user import handle_setup_alert, handle_manage_alerts
from ai.general import handle_general_ai_conversation
from analysis.handler import handle_token_analysis

logger = logging.getLogger(__name__)

# --- Обработчики и заглушки ---
async def handle_unsupported_request(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    error_map = {
        "AI_RATE_LIMIT": "⏳ Кажется, я сейчас очень популярен и достиг лимита запросов к своему AI-мозгу. Пожалуйста, попробуйте снова через минуту.",
        "AI_API_HTTP_ERROR": "🔧 Возникла временная проблема с подключением к AI. Попробуйте еще раз.",
        "AI_SERVICE_UNCONFIGURED": "🔧 Мой AI-модуль не настроен. Пожалуйста, сообщите моему администратору."
    }
    response_text = error_map.get(payload, f"😕 Извините, я не совсем понял ваш запрос.")
    await update.effective_message.reply_text(response_text)
    await db_ops.add_chat_message(session=db_session, user_id=update.effective_user.id, role='model', text=response_text)

async def handle_bot_help(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    user_id = update.effective_user.id
    help_text = (
        "🤖 *Я - ваш Интеллектуальный Крипто-Аналитик!*\n\n"
        "Примеры моих возможностей:\n"
        "▫️ *'какая цена у биткоина?'* - узнать цену\n"
        "▫️ *'расскажи про solana'* - глубокий анализ токена\n"
        "▫️ *'где купить btc?'* - места покупки\n"
        "▫️ *'какие ico скоро?'* - сканирование премаркета\n"
        "▫️ *'что такое DeFi?'* - обучающие уроки\n"
        "▫️ *'сообщи когда eth будет 4000'* - установка алертов\n"
        "▫️ *'мой портфель'* - управление портфолио\n\n"
        "Просто напишите мне свой вопрос!"
    )
    await update.effective_message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=help_text)

# ... (все остальные заглушки)
async def handle_where_to_buy(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    await update.effective_message.reply_text(f"⏳ Ищу, где купить *{payload}*...", parse_mode=constants.ParseMode.MARKDOWN)
async def handle_premarket_scan(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    await update.effective_message.reply_text("⏳ Сканирую премаркет...", parse_mode=constants.ParseMode.MARKDOWN)
async def handle_edu_lesson(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    await update.effective_message.reply_text(f"⏳ Готовлю урок по теме *'{payload}'*...", parse_mode=constants.ParseMode.MARKDOWN)
async def handle_track_coin(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not payload:
        await update.effective_message.reply_text("Укажите символ монеты.")
        return
    await handle_portfolio_summary(update, context, f"add {payload}", db_session)
async def handle_untrack_coin(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not payload:
        await update.effective_message.reply_text("Укажите символ монеты.")
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
        response = f"✅ Монета *{symbol.upper()}* добавлена в портфель."

    elif action == "remove" and len(parts) >= 2:
        symbol = parts[1]
        removed = await db_ops.remove_coin_from_portfolio(db_session, user_id, symbol)
        response = "🚮 Монета успешно удалена." if removed else "Монета не найдена в портфеле."

    else:
        portfolio = await db_ops.get_user_portfolio(db_session, user_id)
        if not portfolio:
            response = "Ваш портфель пуст."
        else:
            symbols = [c.coin_symbol for c in portfolio]
            coin_ids, _ = await get_coin_ids_from_symbols(symbols)
            price_data = await coingecko_client.get_simple_price(coin_ids)
            lines = ["💼 *Ваш портфель:*\n"]
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
    
    await db_ops.add_chat_message(session=db_session, user_id=user.id, role='user', text=user_input)

    # --- Обработка встроенных команд БЕЗ AI ---
    hardcoded_commands = {
        '/start': handle_bot_help,
        '/help': handle_bot_help,
        '/portfolio': handle_portfolio_summary,
        '/alerts': handle_manage_alerts
    }
    if user_input.lower() in hardcoded_commands:
        logger.info(f"Обработка жестко заданной команды: {user_input.lower()}")
        await hardcoded_commands[user_input.lower()](update, context, "list", db_session)
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
        await message.reply_text("💥 Ой, что-то пошло не так.")