# settings/user.py
# Модуль для управления настройками пользователя, такими как алерты и портфолио.

import logging
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops
from crypto.handler import COIN_ID_MAP
from settings.messages import get_text

logger = logging.getLogger(__name__)

async def handle_setup_alert(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """
    Обрабатывает установку нового ценового алерта.
    """
    if not update.effective_message:
        return
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ru')
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
            await update.effective_message.reply_text(get_text(lang, 'unknown_symbol_alert', symbol=symbol))
            return

        price = float(price_str)
        if direction not in ['above', 'below']:
            raise ValueError(f"Некорректное направление: {direction}")

        alert = await db_ops.add_price_alert(
            session=db_session, user_id=user_id, symbol=symbol, price=price, direction=direction
        )

        confirmation_message = get_text(
            lang,
            'alert_set_success',
            symbol=alert.coin_symbol,
            direction=("выше" if direction == 'above' and lang == 'ru' else ("ниже" if direction == 'below' and lang == 'ru' else direction)),
            price=f"{alert.target_price:,.2f}"
        )
        await update.effective_message.reply_text(confirmation_message, parse_mode=constants.ParseMode.MARKDOWN)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=confirmation_message)

    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка парсинга payload для алерта: {e}")
        error_text = get_text(lang, 'alert_set_error')
        await update.effective_message.reply_text(error_text)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=error_text)

async def handle_manage_alerts(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """
    Обрабатывает управление существующими алертами, включая удаление.
    """
    if not update.effective_message: return
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ru')
    
    action_parts = payload.split(':')
    action = action_parts[0].strip().lower() if action_parts else "list"
    
    response_message = ""

    if action == 'list':
        active_alerts = await db_ops.get_user_alerts(session=db_session, user_id=user_id)
        if not active_alerts:
            response_message = get_text(lang, 'alerts_empty')
        else:
            message_lines = [get_text(lang, 'alerts_header')]
            for alert in active_alerts:
                direction_text = "📈 >" if alert.direction.value == 'above' else "📉 <"
                line = f"• *{alert.coin_symbol}*: {direction_text} ${alert.target_price:,.2f}"
                message_lines.append(line)
            response_message = "\n".join(message_lines)
            
    elif action == 'delete' and len(action_parts) > 1:
        symbol_to_delete = action_parts[1].strip().upper()
        deleted_count = await db_ops.delete_user_alerts_by_symbol(session=db_session, user_id=user_id, symbol=symbol_to_delete)
        if deleted_count > 0:
            response_message = get_text(lang, 'alert_delete_success', count=deleted_count, symbol=symbol_to_delete)
        else:
            response_message = get_text(lang, 'alert_delete_none', symbol=symbol_to_delete)
    else:
        response_message = get_text(lang, 'alerts_unknown_action')

    await update.effective_message.reply_text(response_message, parse_mode=constants.ParseMode.MARKDOWN)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response_message)


async def handle_change_language(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return
    user_id = update.effective_user.id
    lang = payload.strip().lower() or 'ru'
    if lang not in ('ru', 'en'):
        lang = 'ru'
    await db_ops.update_user_settings(db_session, user_id, language=lang)
    context.user_data['lang'] = lang
    message = get_text(lang, 'lang_set', lang='Русский' if lang == 'ru' else 'English')
    await update.effective_message.reply_text(message)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=message)


async def handle_settings_command(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return
    user_id = update.effective_user.id
    args = payload.split()
    lang = context.user_data.get('lang', 'ru')

    if not args:
        stats = await db_ops.get_user_stats(db_session, user_id)
        lang = stats['language']
        text = get_text(lang, 'settings_overview', **stats)
        await update.effective_message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=text)
        return

    option = args[0].lower()
    value = args[1] if len(args) > 1 else ''

    if option in ('language', 'lang'):
        await handle_change_language(update, context, value, db_session)
        return
    if option in ('timezone', 'tz') and value:
        await db_ops.update_user_settings(db_session, user_id, timezone=value)
        context.user_data['timezone'] = value
        text = get_text(lang, 'timezone_set', tz=value)
    elif option in ('currency',) and value:
        await db_ops.update_user_settings(db_session, user_id, currency=value.upper())
        context.user_data['currency'] = value.upper()
        text = get_text(lang, 'currency_set', cur=value.upper())
    else:
        text = get_text(lang, 'settings_prompt')

    await update.effective_message.reply_text(text)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=text)