# ai/general.py
# Модуль для обработки общих вопросов с улучшенной эмпатией.

import os
import logging
import httpx
from typing import List, Dict
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update, constants
from telegram.ext import CallbackContext

from database import operations as db_ops
from settings.messages import get_text

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_GPT_MODEL", "gpt-4o")


# --- Сокращённый системный промпт ---
GENERAL_PROMPT_TEMPLATE = """
Ты — краткий и эмпатичный крипто‑бот. Отвечай 1–3 фразами. Если пользователю грустно, начни с сочувствия. Не перенаправляй на сайты.

Диалог:
{chat_history}

Запрос: '{user_input}'

Ответ:
"""

def format_history_for_prompt(history: List[Dict[str, str]]) -> str:
    if not history: return "Нет предыдущих сообщений."
    return "\n".join([f"{'Ты' if msg['role'] == 'model' else 'Пользователь'}: {msg['text']}" for msg in history])


async def handle_general_ai_conversation(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return
        
    user_id = update.effective_user.id
    user_input = payload
    lang = context.user_data.get('lang', 'ru')

    try:
        history_records = await db_ops.get_chat_history(session=db_session, user_id=user_id, limit=3)
        history_for_prompt = [{"role": record.role, "text": record.message_text} for record in history_records]

        prompt = GENERAL_PROMPT_TEMPLATE.format(
            chat_history=format_history_for_prompt(history_for_prompt),
            user_input=user_input
        )

        ai_response = ""

        if GEMINI_API_KEY:
            headers = {'Content-Type': 'application/json'}
            api_payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": { "temperature": 0.7, "maxOutputTokens": 512 }}
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(GEMINI_API_URL, json=api_payload, headers=headers)
                    response.raise_for_status()
                    api_data = response.json()
                    ai_response = api_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                logger.warning(f"Gemini chat failed: {e}")

        if not ai_response and OPENAI_API_KEY:
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload_oa = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(OPENAI_API_URL, json=payload_oa, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    ai_response = data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"OpenAI chat failed: {e}")

        if not ai_response:
            ai_response = get_text(lang, 'ai_generic_empty')

        await update.effective_message.reply_text(ai_response, parse_mode=constants.ParseMode.MARKDOWN)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=ai_response)

    except Exception as e:
        logger.error(f"Ошибка в обработчике общего диалога: {e}", exc_info=True)
        await update.effective_message.reply_text(get_text(lang, 'ai_generic_error'))