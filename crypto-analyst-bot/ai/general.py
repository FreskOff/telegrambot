# ai/general.py
# Модуль для обработки общих вопросов с улучшенной эмпатией.

import os
import logging
import httpx
import asyncio
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
OPENAI_MODEL = os.getenv("OPENAI_GPT_MODEL", "gpt-4o-mini")


# --- НОВЫЙ ПРОМПТ С ФОКУСОМ НА ЭМПАТИИ ---
GENERAL_PROMPT_TEMPLATE = """
Ты — ИИ-ассистент в крипто-боте. Твоя личность: умный, краткий, по делу, но с эмпатией.

ПРАВИЛА:
1.  **КРАТКОСТЬ:** Отвечай 1-3 предложениями.
2.  **ЭМПАТИЯ:** Если пользователь говорит, что ему грустно, одиноко или у него плохой день, твой ПЕРВЫЙ ответ должен быть поддерживающим и сочувствующим. НЕ предлагай сразу помощь. Задай открытый вопрос. Пример: "Мне очень жаль это слышать. Хочешь поговорить об этом?"
3.  **КОНТЕКСТ:** Изучи историю чата. Если пользователь спрашивает "помнишь?", ответь прямо и предложи повторить действие.
4.  **САМОСОЗНАНИЕ:** Ты — бот с функциями (цены, анализ, алерты). Не отправляй пользователя на внешние сайты.
5.  **ДАТА:** Сегодня {current_date}.
6.  **ЯЗЫК:** Русский.

ИСТОРИЯ ДИАЛОГА:
{chat_history}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ: '{user_input}'

ТВОЙ КРАТКИЙ И ЭМПАТИЧНЫЙ ОТВЕТ:
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
        history_records = await db_ops.get_chat_history(session=db_session, user_id=user_id, limit=10)
        history_for_prompt = [{"role": record.role, "text": record.message_text} for record in history_records]
        
        current_date_str = datetime.now().strftime("%d %B %Y года")
        
        prompt = GENERAL_PROMPT_TEMPLATE.format(
            current_date=current_date_str,
            chat_history=format_history_for_prompt(history_for_prompt), 
            user_input=user_input
        )

        async def _gemini_call() -> str | None:
            if not GEMINI_API_KEY:
                return None
            headers = {"Content-Type": "application/json"}
            api_payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512}}
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(GEMINI_API_URL, json=api_payload, headers=headers)
                    response.raise_for_status()
                    api_data = response.json()
                    return api_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                logger.warning(f"Gemini chat failed: {e}")
                return None

        async def _openai_call() -> str | None:
            if not OPENAI_API_KEY:
                return None
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload_oa = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(OPENAI_API_URL, json=payload_oa, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"OpenAI chat failed: {e}")
                return None

        tasks = []
        if GEMINI_API_KEY:
            tasks.append(asyncio.create_task(_gemini_call()))
        if OPENAI_API_KEY:
            tasks.append(asyncio.create_task(_openai_call()))

        ai_response = ""
        if tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            for d in done:
                res = d.result()
                if res:
                    ai_response = res
                    break

        if not ai_response:
            ai_response = get_text(lang, 'ai_generic_empty')

        await update.effective_message.reply_text(ai_response, parse_mode=constants.ParseMode.MARKDOWN)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=ai_response)

    except Exception as e:
        logger.error(
            f"Ошибка в обработчике общего диалога для {user_id} и запроса '{user_input}': {e}",
            exc_info=True,
        )
        await update.effective_message.reply_text(get_text(lang, 'ai_generic_error'))