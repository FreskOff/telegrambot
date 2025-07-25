# crypto/handler.py
# Модуль для обработки запросов, связанных с криптовалютами.

import logging
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from utils.api_clients import coingecko_client
from utils.validators import is_valid_symbol
from ai.formatter import format_data_with_ai
from database import operations as db_ops
from settings.messages import get_text

logger = logging.getLogger(__name__)

# Этот словарь теперь работает как кэш/быстрый доступ для самых популярных монет
COIN_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "VRA": "verasity" 
}

async def get_coin_ids_from_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    """
    Преобразует список символов в список ID для CoinGecko, используя кэш и API.
    """
    found_ids = []
    not_found_symbols = []
    for symbol in symbols:
        if not is_valid_symbol(symbol):
            not_found_symbols.append(symbol)
            continue
        upper_symbol = symbol.strip().upper()
        # 1. Ищем в нашем кэше
        coin_id = COIN_ID_MAP.get(upper_symbol)
        
        # 2. Если не нашли, ищем через API
        if not coin_id:
            coin_id = await coingecko_client.search_coin(symbol)
        
        if coin_id:
            found_ids.append(coin_id)
            # Опционально: обновляем кэш для будущих запросов
            if upper_symbol not in COIN_ID_MAP:
                COIN_ID_MAP[upper_symbol] = coin_id
        else:
            not_found_symbols.append(symbol)
            
    return found_ids, not_found_symbols

async def handle_crypto_info_request(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """
    Обрабатывает запрос на получение информации о криптовалюте.
    """
    if not update.effective_message: return

    user_id = update.effective_user.id
    await db_ops.increment_request_counter(db_session, user_id, "price_requests")
    lang = context.user_data.get('lang', 'ru')
    symbols = payload.split(',')
    coin_ids, not_found = await get_coin_ids_from_symbols(symbols)

    if not coin_ids:
        response_text = get_text(lang, 'crypto_not_found', payload=payload)
        await update.effective_message.reply_text(response_text)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response_text)
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        price_data = await coingecko_client.get_simple_price(coin_ids=coin_ids)

        if not price_data:
            response_text = get_text(lang, 'crypto_no_data')
            await update.effective_message.reply_text(response_text)
            await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response_text)
            return

        formatted_response = await format_data_with_ai(price_data)

        if not_found:
            missing = get_text(lang, 'crypto_partial_missing', coins=', '.join(not_found))
            formatted_response += f"\n\n_{missing}_"

        await update.effective_message.reply_text(
            formatted_response,
            parse_mode=constants.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        # Сохраняем финальный ответ бота в историю
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=formatted_response)

    except Exception as e:
        logger.exception(f"Ошибка при обработке крипто-запроса: {e}")
        await update.effective_message.reply_text(
            get_text(lang, 'crypto_api_error', error=str(e))
        )