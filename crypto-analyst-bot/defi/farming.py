import logging
import httpx
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from settings.messages import get_text

logger = logging.getLogger(__name__)

API_URL = "https://yields.llama.fi/pools"

async def handle_defi_farming(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Fetches top farming pools from DefiLlama."""
    lang = context.user_data.get('lang', 'ru')
    await update.effective_message.reply_text(get_text(lang, 'defi_searching'))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(API_URL)
            resp.raise_for_status()
            data = resp.json().get('data', [])
    except Exception as e:
        logger.exception(f"DefiLlama request failed: {e}")
        await update.effective_message.reply_text(
            get_text(lang, 'defi_api_error', error=str(e))
        )
        return

    if not data:
        await update.effective_message.reply_text(get_text(lang, 'defi_no_data'))
        return

    # sort by apy desc and pick top 3
    top = sorted(data, key=lambda x: x.get('apy', 0), reverse=True)[:3]
    lines = [get_text(lang, 'defi_header')]
    for p in top:
        project = p.get('project')
        chain = p.get('chain')
        apy = p.get('apy')
        symbol = p.get('symbol')
        lines.append(f"• {project} {symbol} ({chain}) — {apy:.2f}% APY")

    await update.effective_message.reply_text('\n'.join(lines), parse_mode=constants.ParseMode.MARKDOWN)
