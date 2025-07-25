import logging
import httpx
from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from settings.messages import get_text

logger = logging.getLogger(__name__)

API_URL = "https://api.opensea.io/api/v1/collection/{slug}/stats"

async def handle_nft_analytics(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Provides basic NFT collection analytics via OpenSea."""
    lang = context.user_data.get('lang', 'ru')
    slug = (payload or '').strip().lower().replace(' ', '-')
    if not slug:
        await update.effective_message.reply_text(get_text(lang, 'nft_no_data'))
        return

    await update.effective_message.reply_text(get_text(lang, 'nft_searching', slug=slug))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(API_URL.format(slug=slug))
            resp.raise_for_status()
            data = resp.json().get('stats', {})
    except Exception as e:
        logger.error(f"OpenSea request failed: {e}")
        await update.effective_message.reply_text(get_text(lang, 'nft_no_data'))
        return

    if not data:
        await update.effective_message.reply_text(get_text(lang, 'nft_no_data'))
        return

    floor = data.get('floor_price')
    volume = data.get('total_volume')
    owners = data.get('num_owners')
    lines = [get_text(lang, 'nft_header', slug=slug)]
    lines.append(f"• Floor price: {floor} ETH")
    lines.append(f"• Volume: {volume:,.0f} ETH")
    lines.append(f"• Owners: {owners}")
    await update.effective_message.reply_text('\n'.join(lines), parse_mode=constants.ParseMode.MARKDOWN)
