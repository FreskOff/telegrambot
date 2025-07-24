# settings/user.py
# Модуль для управления настройками пользователя, такими как алерты и портфолио.

import logging
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops
from crypto.handler import COIN_ID_MAP

logger = logging.getLogger(__name__)

async def handle_setup_alert(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """
    Обрабатывает установку нового ценового алерта.
    """
    if not update.effective_message: return
    user_id = update.effective_user.id
    logger.info(f"Попытка установки алерта для user_id={user_id} с payload='{payload}'")

    try:
        payload = payload.replace("=", ":")
        parts = payload.split(':')
        
        if len(parts) == 3:
            symbol, price_str, direction = parts
        elif len(parts) == 2:
            symbol, price_str = parts
            direction = 'above'
        else:
            raise ValueError("Неверный формат payload для алерта.")
        
        symbol = symbol.strip().upper()
        direction = direction.strip().lower()
        price_str = price_str.replace(" ", "")
        
        if symbol not in COIN_ID_MAP:
            await update.effective_message.reply_text(f"😕 Неизвестный символ монеты: {symbol}.")
            return

        price = float(price_str)
        if direction not in ['above', 'below']:
            raise ValueError(f"Некорректное направление: {direction}")

        alert = await db_ops.add_price_alert(
            session=db_session, user_id=user_id, symbol=symbol, price=price, direction=direction
        )

        direction_text = "выше" if direction == 'above' else "ниже"
        confirmation_message = (
            f"✅ *Алерт установлен!*\n\n"
            f"Я сообщу вам, когда цена *{alert.coin_symbol}* станет {direction_text} *${alert.target_price:,.2f}*."
        )
        await update.effective_message.reply_text(confirmation_message, parse_mode=constants.ParseMode.MARKDOWN)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=confirmation_message)

    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка парсинга payload для алерта: {e}")
        error_text = "😕 Не удалось установить алерт. Убедитесь, что запрос выглядит так:\n`сообщи когда BTC будет выше 70000`"
        await update.effective_message.reply_text(error_text)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=error_text)

async def handle_manage_alerts(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """
    Обрабатывает управление существующими алертами, включая удаление.
    """
    if not update.effective_message: return
    user_id = update.effective_user.id
    
    action_parts = payload.split(':')
    action = action_parts[0].strip().lower() if action_parts else "list"
    
    response_message = ""

    if action == 'list':
        active_alerts = await db_ops.get_user_alerts(session=db_session, user_id=user_id)
        if not active_alerts:
            response_message = "У вас пока нет активных алертов."
        else:
            message_lines = ["🔔 *Ваши активные алерты:*\n"]
            for alert in active_alerts:
                direction_text = "📈 >" if alert.direction.value == 'above' else "📉 <"
                line = f"• *{alert.coin_symbol}*: {direction_text} ${alert.target_price:,.2f}"
                message_lines.append(line)
            response_message = "\n".join(message_lines)
            
    elif action == 'delete' and len(action_parts) > 1:
        symbol_to_delete = action_parts[1].strip().upper()
        deleted_count = await db_ops.delete_user_alerts_by_symbol(session=db_session, user_id=user_id, symbol=symbol_to_delete)
        if deleted_count > 0:
            response_message = f"✅ Успешно удалено {deleted_count} алерт(ов) для *{symbol_to_delete}*."
        else:
            response_message = f"🤔 Не найдено активных алертов для *{symbol_to_delete}*, которые можно было бы удалить."
    else:
        response_message = f"Неизвестное действие. Попробуйте 'мои алерты' или 'удали алерт для BTC'."

    await update.effective_message.reply_text(response_message, parse_mode=constants.ParseMode.MARKDOWN)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response_message)