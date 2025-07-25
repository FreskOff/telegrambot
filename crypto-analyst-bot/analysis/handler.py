# analysis/handler.py
# Модуль для глубокого анализа токенов, включая поиск новостей.

import logging
import json
import os
import httpx
import time
from fpdf import FPDF
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops
from settings.messages import get_text

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GPT4_MODEL = os.getenv("OPENAI_GPT_MODEL", "gpt-4o")

# кэш ответов {payload: (timestamp, message)}
analysis_cache: dict[str, tuple[float, str]] = {}
CACHE_TTL = 600  # seconds

EXTENDED_REPORT_PRICE = 100  # stars

EXTENDED_ANALYSIS_PROMPT = """
Ты эксперт по ончейн‑анализу. Сформируй подробный отчёт с историческими данными,
графиками и краткими метриками по запросу пользователя.
Ответ на русском в Markdown.

Запрос: "{user_query}"
Данные поиска:
```json
{search_results}
```
Полный отчёт:
"""


ANALYSIS_PROMPT = """
Ты опытный криптоаналитик. Используй данные поиска ниже, чтобы кратко (2-3 абзаца) подвести итог по запросу.
Структура: важные новости, общий сентимент, вывод. Не давай финансовых советов. Ответ на русском в Markdown.

Запрос: "{user_query}"
Данные поиска:
```json
{search_results}
```
Сводка:
"""


async def _generate_summary(prompt: str) -> str:
    """Запрашивает AI-модель (OpenAI GPT-4o или Gemini) и возвращает ответ."""
    if OPENAI_API_KEY:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": GPT4_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
        }
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(OPENAI_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    else:
        headers = {"Content-Type": "application/json"}
        api_payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 2048},
        }
        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post(GEMINI_API_URL, json=api_payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _markdown_to_pdf_bytes(text: str) -> bytes:
    """Генерирует простой PDF из Markdown-текста."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    for line in text.split("\n"):
        pdf.multi_cell(0, 10, line)
    return pdf.output(dest="S").encode("latin-1")


async def generate_extended_report(user_query: str, search_results: list) -> tuple[str, bytes]:
    """Формирует расширенный отчёт и PDF (заготовка)."""
    prompt = EXTENDED_ANALYSIS_PROMPT.format(
        user_query=user_query,
        search_results=json.dumps(search_results, indent=2, ensure_ascii=False),
    )
    analysis_md = await _generate_summary(prompt)
    pdf_bytes = _markdown_to_pdf_bytes(analysis_md)
    return analysis_md, pdf_bytes

async def handle_token_analysis(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'ru')
    
    # --- ИСПРАВЛЕНИЕ: Проверяем, что payload не пустой ---
    if not payload:
        await update.effective_message.reply_text(get_text(lang, 'analysis_missing_token'))
        return

    extended = False
    if payload.lower().endswith('::full'):
        extended = True
        payload = payload[:-6]

    cache_key = (payload.lower().strip() + (':full' if extended else ''))
    cached = analysis_cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        final_message = cached[1]
        await update.effective_message.reply_text(final_message, parse_mode=constants.ParseMode.MARKDOWN, disable_web_page_preview=True)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=final_message)
        return

    query = f"новости и аналитика криптовалюты {payload}"
    await update.effective_message.reply_text(
        get_text(lang, 'analysis_searching', payload=payload),
        parse_mode=constants.ParseMode.MARKDOWN,
    )
    
    try:
        search_results_list = google_search.search(queries=[query])
        
        if not search_results_list or not search_results_list[0].results:
            await update.effective_message.reply_text(get_text(lang, 'analysis_no_info'))
            return

        search_results = search_results_list[0].results
        if extended:
            user_stars = await db_ops.get_user_stars(db_session, user_id)
            if user_stars < EXTENDED_REPORT_PRICE:
                await update.effective_message.reply_text(get_text(lang, 'analysis_full_insufficient_stars'))
                return
            await db_ops.deduct_stars(db_session, user_id, EXTENDED_REPORT_PRICE)
            await update.effective_message.reply_text(get_text(lang, 'analysis_full_ready'))
            md_text, pdf_bytes = await generate_extended_report(payload, search_results)
            await update.effective_message.reply_document(document=pdf_bytes, filename=f"{payload}_report.pdf")
            final_message = md_text
        else:
            prompt = ANALYSIS_PROMPT.format(
                user_query=payload,
                search_results=json.dumps(search_results, indent=2, ensure_ascii=False),
            )
            analysis_text = await _generate_summary(prompt)
            final_message = get_text(lang, 'analysis_header', payload=payload, analysis=analysis_text)
            await update.effective_message.reply_text(
                final_message,
                parse_mode=constants.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=final_message)
        analysis_cache[cache_key] = (time.time(), final_message)

    except Exception as e:
        logger.error(f"Ошибка при выполнении анализа токена: {e}", exc_info=True)
        await update.effective_message.reply_text(get_text(lang, 'analysis_error'))
