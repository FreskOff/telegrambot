# analysis/handler.py
# Модуль для глубокого анализа токенов, включая поиск новостей.

import logging
import json
import os
import httpx
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

ANALYSIS_PROMPT = """
Ты - профессиональный крипто-аналитик. Тебе предоставлены результаты поиска Google по запросу пользователя.
Твоя задача - проанализировать эти данные и написать краткую, но содержательную аналитическую сводку (3-5 абзацев) на русском языке.

Структура ответа:
1.  **Ключевые новости:** Упомяни 2-3 самые свежие и важные новости.
2.  **Общий сентимент:** Опиши общее настроение вокруг токена.
3.  **Заключение:** Сделай краткий вывод.

Не давай финансовых советов. Используй Markdown.

**Запрос пользователя:** "{user_query}"
**Результаты поиска (JSON):**
```json
{search_results}
```
Твоя аналитическая сводка:
"""

async def handle_token_analysis(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message: return
    user_id = update.effective_user.id
    
    # --- ИСПРАВЛЕНИЕ: Проверяем, что payload не пустой ---
    if not payload:
        await update.effective_message.reply_text("😕 Пожалуйста, уточните, о каком токене вы хотите узнать.")
        return

    query = f"новости и аналитика криптовалюты {payload}"
    await update.effective_message.reply_text(f"🔍 Ищу и анализирую информацию по запросу: *{payload}*. Это может занять до 30 секунд...", parse_mode=constants.ParseMode.MARKDOWN)
    
    try:
        search_results_list = google_search.search(queries=[query])
        
        if not search_results_list or not search_results_list[0].results:
            await update.effective_message.reply_text("😕 Не удалось найти актуальной информации по вашему запросу.")
            return

        search_results = search_results_list[0].results
        prompt = ANALYSIS_PROMPT.format(user_query=payload, search_results=json.dumps(search_results, indent=2, ensure_ascii=False))
        
        headers = {'Content-Type': 'application/json'}
        api_payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.5, "maxOutputTokens": 2048}}

        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post(GEMINI_API_URL, json=api_payload, headers=headers)
            response.raise_for_status()
            api_data = response.json()
            analysis_text = api_data["candidates"][0]["content"]["parts"][0]["text"].strip()

        final_message = f"📊 *Аналитическая сводка по {payload}*\n\n{analysis_text}"
        await update.effective_message.reply_text(final_message, parse_mode=constants.ParseMode.MARKDOWN, disable_web_page_preview=True)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=final_message)

    except Exception as e:
        logger.error(f"Ошибка при выполнении анализа токена: {e}", exc_info=True)
        await update.effective_message.reply_text("💥 Произошла ошибка во время сбора и анализа информации.")