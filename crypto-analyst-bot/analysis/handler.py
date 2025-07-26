# analysis/handler.py
# Модуль для глубокого анализа токенов, включая поиск новостей.

import logging
import json
import os
import httpx
import time
import tempfile
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops
from settings.messages import get_text
from utils.api_clients import coingecko_client
from utils import news_api
from utils import google_search

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GPT4_MODEL = os.getenv("OPENAI_GPT_MODEL", "gpt-4o-mini")

# кэш ответов {payload: (timestamp, message)}
analysis_cache: dict[str, tuple[float, str]] = {}
CACHE_TTL = 600  # seconds
EXTENDED_ANALYSIS_PRICE = 100


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

EXTENDED_ANALYSIS_PROMPT = """
Ты профессиональный криптоаналитик. Используй исторические данные и результаты поиска ниже, чтобы подготовить детальный обзор токена. Структура: ключевые новости, анализ ончейн-метрик, динамика цены, вывод. Ответ на русском в Markdown.

Запрос: "{user_query}"
Исторические данные:
{historical}
Данные поиска:
```json
{search_results}
```
Обзор:
"""


async def _generate_summary(prompt: str, symbol: str, db_session: AsyncSession | None = None) -> str:
    """Запрашивает AI-модель и обогащает запрос новостями."""
    news = await news_api.get_news(symbol)
    if news:
        prompt += "\nАктуальные новости:\n```json\n" + json.dumps(news, ensure_ascii=False, indent=2) + "\n```"
        if db_session:
            await db_ops.add_news_articles(db_session, symbol, news)
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

async def _fetch_price_history(symbol: str) -> list[tuple[str, float]]:
    coin_id = await coingecko_client.search_coin(symbol)
    if not coin_id:
        return []
    data = await coingecko_client.get_market_chart(coin_id, days=30)
    if not data or "prices" not in data:
        return []
    prices = []
    for ts, price in data["prices"]:
        date = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        prices.append((date, price))
    return prices

def _create_price_chart(prices: list[tuple[str, float]], symbol: str) -> str:
    if not prices:
        return ""
    dates, values = zip(*prices)
    plt.figure(figsize=(6, 3))
    plt.plot(dates, values)
    plt.title(f"{symbol.upper()} price (30d)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    plt.savefig(tmp.name)
    plt.close()
    return tmp.name

def _generate_pdf(text: str, chart_path: str) -> str:
    pdf_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with PdfPages(pdf_tmp.name) as pdf:
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.axis("off")
        ax.text(0.05, 0.95, text, va="top", wrap=True)
        pdf.savefig(fig)
        plt.close(fig)
        if chart_path:
            img = plt.imread(chart_path)
            fig, ax = plt.subplots()
            ax.imshow(img)
            ax.axis("off")
            pdf.savefig(fig)
            plt.close(fig)
    return pdf_tmp.name

def _write_markdown(text: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".md")
    with open(tmp.name, "w", encoding="utf-8") as f:
        f.write(text)
    return tmp.name

async def _generate_extended_report(symbol: str, search_results: list, db_session: AsyncSession) -> tuple[str, str, str, str]:
    history = await _fetch_price_history(symbol)
    prompt = EXTENDED_ANALYSIS_PROMPT.format(
        user_query=symbol,
        search_results=json.dumps(search_results, indent=2, ensure_ascii=False),
        historical=json.dumps(history, ensure_ascii=False),
    )
    text = await _generate_summary(prompt, symbol, db_session)
    chart = _create_price_chart(history, symbol)
    pdf = _generate_pdf(text, chart)
    md = _write_markdown(text)
    return text, pdf, md, chart

async def handle_token_analysis(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    if not update.effective_message:
        return
    user_id = update.effective_user.id
    await db_ops.increment_request_counter(db_session, user_id, "analysis_requests")
    lang = context.user_data.get('lang', 'ru')

    if not payload:
        await update.effective_message.reply_text(get_text(lang, 'analysis_missing_token'))
        return

    extended = False
    token = payload.strip()
    lowered = token.lower()
    for prefix in ('full ', 'extended ', 'расширенный '):
        if lowered.startswith(prefix):
            extended = True
            token = token[len(prefix):].strip()
            break

    cache_key = ("full:" if extended else "") + token.lower()
    cached = analysis_cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        final_message = cached[1]
        await update.effective_message.reply_text(final_message, parse_mode=constants.ParseMode.MARKDOWN, disable_web_page_preview=True)
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=final_message)
        return

    query = f"новости и аналитика криптовалюты {token}"
    await update.effective_message.reply_text(
        get_text(lang, 'analysis_searching', payload=token),
        parse_mode=constants.ParseMode.MARKDOWN,
    )

    if extended:
        subscription = await db_ops.get_subscription(db_session, user_id)
        premium = subscription and subscription.is_active and subscription.level == 'premium'
        if not premium:
            balance = await db_ops.get_star_balance(db_session, user_id)
            if balance < EXTENDED_ANALYSIS_PRICE:
                await update.effective_message.reply_text(
                    get_text(lang, 'analysis_premium_insufficient', price=EXTENDED_ANALYSIS_PRICE)
                )
                return
        await update.effective_message.reply_text(get_text(lang, 'analysis_premium_start'))
    
    try:
        search_results_list = google_search.search(queries=[query])
        
        if not search_results_list or not search_results_list[0].results:
            await update.effective_message.reply_text(get_text(lang, 'analysis_no_info'))
            return

        search_results = search_results_list[0].results
        if extended:
            analysis_text, pdf_path, md_path, chart_path = await _generate_extended_report(token, search_results, db_session)
        else:
            prompt = ANALYSIS_PROMPT.format(
                user_query=token,
                search_results=json.dumps(search_results, indent=2, ensure_ascii=False),
            )
            analysis_text = await _generate_summary(prompt, token, db_session)

        final_message = get_text(lang, 'analysis_header', payload=token, analysis=analysis_text)
        if extended:
            if not premium:
                await db_ops.deduct_stars(db_session, user_id, EXTENDED_ANALYSIS_PRICE)
            with open(pdf_path, 'rb') as pf:
                await update.effective_message.reply_document(
                    pf,
                    filename=f"{token}_report.pdf",
                    caption=final_message,
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
            with open(md_path, 'rb') as mf:
                await update.effective_message.reply_document(mf, filename=f"{token}_report.md")
            for path in (pdf_path, md_path, chart_path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        else:
            await update.effective_message.reply_text(
                final_message,
                parse_mode=constants.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        await db_ops.add_chat_message(session=db_session, user_id=user_id, role='model', text=final_message)
        analysis_cache[cache_key] = (time.time(), final_message)

    except Exception as e:
        logger.error(
            f"Ошибка при выполнении анализа токена для {user_id} и запроса '{token}': {e}",
            exc_info=True,
        )
        await update.effective_message.reply_text(get_text(lang, 'analysis_error'))
