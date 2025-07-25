import logging
import httpx
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from settings.messages import get_text

logger = logging.getLogger(__name__)

API_URL = "https://api.coingecko.com/api/v3/coins/markets"

async def handle_depin_projects(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Shows top DePIN projects by market cap."""
    lang = context.user_data.get('lang', 'ru')
    await update.effective_message.reply_text(get_text(lang, 'depin_searching'))

    params = {
        "vs_currency": "usd",
        "category": "depin",
        "order": "market_cap_desc",
        "per_page": 5,
        "page": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"DePIN request failed: {e}")
        await update.effective_message.reply_text(get_text(lang, 'depin_no_data'))
        return

    if not data:
        await update.effective_message.reply_text(get_text(lang, 'depin_no_data'))
        return

    lines = [get_text(lang, 'depin_header')]
    for coin in data:
        lines.append(f"• {coin['name']} ({coin['symbol'].upper()}) — ${coin['market_cap']:,.0f} MC")

    await update.effective_message.reply_text('\n'.join(lines), parse_mode=constants.ParseMode.MARKDOWN)
