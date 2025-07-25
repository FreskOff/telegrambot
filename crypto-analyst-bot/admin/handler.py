"""admin/handler.py
Заготовка для обработки админских команд и запросов.
"""

import logging
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops
from settings.messages import get_text

logger = logging.getLogger(__name__)

async def handle_admin_request(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Обрабатывает запросы администратора. Пока лишь демонстрация."""
    if not update.effective_message:
        return

    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ru')

    command = (payload or '').strip().lower()
    if command == 'stats':
        total_users = await db_ops.count_users(db_session)
        response = f"👥 Всего пользователей: {total_users}"
    else:
        response = "⚙️ Админ-команда принята. Функционал в разработке."

    await update.effective_message.reply_text(response, parse_mode=constants.ParseMode.MARKDOWN)
    await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=response)
