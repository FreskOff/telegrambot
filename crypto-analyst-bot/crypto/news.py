import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from utils import news_api
from database import operations as db_ops
from settings.messages import get_text

logger = logging.getLogger(__name__)

# Simple popularity weights for sources
SOURCE_WEIGHTS = {
    "coindesk": 2,
    "cointelegraph": 2,
    "cryptopanic": 1,
}


async def _get_symbol_from_history(session: AsyncSession, user_id: int) -> Optional[str]:
    """Attempt to find last mentioned token symbol in recent chat history."""
    history = await db_ops.get_chat_history(session, user_id, limit=4)
    for msg in reversed(history):
        if msg.role == "model":
            found = re.findall(r"\*([A-Z]{2,5})\*", msg.message_text)
            if found:
                return found[0]
    return None


async def _fetch_and_store(symbol: str, limit: int, db_session: Optional[AsyncSession]) -> List[Dict]:
    articles = await news_api.get_news(symbol, limit)
    if db_session and articles:
        try:
            await db_ops.add_news_articles(db_session, symbol, articles)
        except Exception as e:
            logger.error(f"Failed to store news: {e}")
    return articles


async def get_crypto_news(
    symbol: str,
    limit: int = 5,
    since: Optional[datetime] = None,
    popular: bool = False,
    db_session: Optional[AsyncSession] = None,
) -> List[Dict]:
    """Return recent news for a token with optional filters."""
    articles: List[Dict] = []

    if db_session:
        stored = await db_ops.get_recent_news(db_session, symbol, limit=limit)
        for art in stored:
            if since and art.published_at and art.published_at < since:
                continue
            articles.append(
                {
                    "title": art.title,
                    "url": art.url,
                    "source": art.source,
                    "published_at": art.published_at.isoformat() if art.published_at else None,
                }
            )
        if len(articles) < limit:
            fetched = await _fetch_and_store(symbol, limit, db_session)
            for art in fetched:
                dt = None
                if art.get("published_at"):
                    try:
                        dt = datetime.fromisoformat(art["published_at"])
                    except ValueError:
                        dt = None
                if since and dt and dt < since:
                    continue
                if art["url"] not in {a["url"] for a in articles}:
                    articles.append(art)
    else:
        fetched = await _fetch_and_store(symbol, limit, None)
        for art in fetched:
            dt = None
            if art.get("published_at"):
                try:
                    dt = datetime.fromisoformat(art["published_at"])
                except ValueError:
                    dt = None
            if since and dt and dt < since:
                continue
            articles.append(art)

    if popular:
        articles.sort(
            key=lambda x: SOURCE_WEIGHTS.get((x.get("source") or "").lower(), 0),
            reverse=True,
        )
    else:
        articles.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    return articles[:limit]


async def handle_news_command(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Telegram command handler to show latest crypto news."""
    lang = context.user_data.get("lang", "ru")
    args = payload.split()
    symbol = args[0] if args else ""
    since = None
    popular = False

    for a in args[1:]:
        if a.lower() == "popular":
            popular = True
        elif a.lower().startswith("since="):
            try:
                since = datetime.fromisoformat(a.split("=", 1)[1])
            except ValueError:
                continue

    if not symbol:
        found = await _get_symbol_from_history(db_session, update.effective_user.id)
        symbol = found or "BTC"

    await update.effective_message.reply_text(get_text(lang, "news_fetching", symbol=symbol))

    try:
        news = await get_crypto_news(symbol, limit=5, since=since, popular=popular, db_session=db_session)
    except Exception as e:
        logger.error(f"News fetch error: {e}")
        news = []

    if not news:
        text = get_text(lang, "news_no_data", symbol=symbol)
        await update.effective_message.reply_text(text)
        await db_ops.add_chat_message(session=db_session, user_id=update.effective_user.id, role="model", text=text)
        return

    lines = [get_text(lang, "news_header", symbol=symbol)]
    for art in news:
        date = ""
        if art.get("published_at"):
            try:
                dt = datetime.fromisoformat(art["published_at"])
                date = dt.strftime("%Y-%m-%d")
            except ValueError:
                date = art["published_at"]
        source = f" ({art['source']})" if art.get("source") else ""
        line = f"• [{art['title']}]({art['url']}){source} {date}"
        lines.append(line)

    response = "\n".join(lines)
    await update.effective_message.reply_text(
        response,
        parse_mode=constants.ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    await db_ops.add_chat_message(session=db_session, user_id=update.effective_user.id, role="model", text=response)
