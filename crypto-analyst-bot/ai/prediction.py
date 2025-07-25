# ai/prediction.py
"""Simple price prediction utilities."""

import json
import logging
from datetime import datetime
from typing import List, Tuple, Optional

from telegram import Update, constants
from telegram.ext import CallbackContext
from sqlalchemy.ext.asyncio import AsyncSession

from utils.cache import get_cache, set_cache
from utils.api_clients import coingecko_client
from crypto.handler import COIN_ID_MAP, get_coin_ids_from_symbols
from settings.messages import get_text
from database import operations as db_ops

logger = logging.getLogger(__name__)

HISTORY_TTL = 3600  # seconds
PREDICTION_TTL = 3600

async def _fetch_history(symbol: str, days: int = 30) -> List[Tuple[datetime, float]]:
    """Fetches historical prices and caches them."""
    coin_id = COIN_ID_MAP.get(symbol.upper()) or await coingecko_client.search_coin(symbol)
    if not coin_id:
        return []
    cache_key = f"hist:{coin_id}:{days}"
    cached = await get_cache(cache_key)
    if cached:
        try:
            data = json.loads(cached)
            return [(datetime.fromtimestamp(ts / 1000), price) for ts, price in data]
        except Exception:
            pass
    data = await coingecko_client.get_market_chart(coin_id, days=days)
    if not data or "prices" not in data:
        return []
    await set_cache(cache_key, json.dumps(data["prices"]), ttl=HISTORY_TTL)
    return [(datetime.fromtimestamp(ts / 1000), price) for ts, price in data["prices"]]

def _linear_regression(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    n = len(points)
    if n < 2:
        return 0.0, 0.0
    xs, ys = zip(*points)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    if var_x == 0:
        return 0.0, mean_y
    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept

def _predict(prices: List[float], days_ahead: int) -> float:
    points = list(enumerate(prices))
    slope, intercept = _linear_regression(points)
    idx = len(prices) + days_ahead
    return intercept + slope * idx

async def get_price_prediction(symbol: str) -> Optional[Tuple[float, float]]:
    """Returns short and long term price prediction for symbol."""
    symbol = symbol.upper()
    cache_key = f"pred:{symbol}"
    cached = await get_cache(cache_key)
    if cached:
        try:
            val = json.loads(cached)
            return val.get("short"), val.get("long")
        except Exception:
            pass
    short_hist = await _fetch_history(symbol, days=30)
    long_hist = await _fetch_history(symbol, days=90)
    if len(short_hist) < 2 or len(long_hist) < 2:
        return None
    short_price = _predict([p for _, p in short_hist], 1)
    long_price = _predict([p for _, p in long_hist], 7)
    await set_cache(cache_key, json.dumps({"short": short_price, "long": long_price}), ttl=PREDICTION_TTL)
    return short_price, long_price

async def handle_predict_command(update: Update, context: CallbackContext, payload: str, db_session: AsyncSession):
    """Telegram command handler for /predict."""
    if not update.effective_message:
        return
    lang = context.user_data.get("lang", "ru")
    symbol = payload.strip().upper()
    if not symbol:
        await update.effective_message.reply_text(get_text(lang, "predict_usage"))
        return
    await update.effective_message.reply_text(
        get_text(lang, "predict_processing", symbol=symbol),
        parse_mode=constants.ParseMode.MARKDOWN,
    )
    try:
        prediction = await get_price_prediction(symbol)
        if not prediction:
            await update.effective_message.reply_text(get_text(lang, "predict_error"))
            return
        short_p, long_p = prediction
        text = get_text(
            lang,
            "predict_result",
            symbol=symbol,
            short=f"{short_p:,.2f}",
            long=f"{long_p:,.2f}",
        )
        await update.effective_message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)
        await db_ops.add_chat_message(session=db_session, user_id=update.effective_user.id, role="model", text=text)
    except Exception as e:
        logger.error(f"Prediction failed for {symbol}: {e}")
        await update.effective_message.reply_text(get_text(lang, "predict_error"))

async def update_prediction_cache():
    """Background task to refresh predictions for popular coins."""
    for symbol in list(COIN_ID_MAP.keys()):
        try:
            await get_price_prediction(symbol)
        except Exception as e:
            logger.warning(f"Failed to update prediction for {symbol}: {e}")
