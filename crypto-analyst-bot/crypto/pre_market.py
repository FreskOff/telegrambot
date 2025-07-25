"""crypto/pre_market.py
Модуль для получения информации о предстоящих ICO/IDO и новых листингах.
Предоставляет обычную и VIP версии данных.
"""

import os
import logging
from typing import List, Dict, Optional
from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup
from utils.api_clients import coingecko_client

logger = logging.getLogger(__name__)
load_dotenv()

COINMARKETCAL_API_KEY = os.getenv("COINMARKETCAL_API_KEY")
COINMARKETCAL_BASE_URL = "https://developers.coinmarketcal.com/v1"
COINGECKO_EVENTS_URL = "https://api.coingecko.com/api/v3/events"
CRYPTORANK_API_URL = "https://api.cryptorank.io/v0/events"
CRYPTORANK_API_KEY = os.getenv("CRYPTORANK_API_KEY")

async def fetch_coinmarketcal_events(limit: int = 5) -> List[Dict]:
    """Получает события из CoinMarketCal."""
    url = f"{COINMARKETCAL_BASE_URL}/events"
    headers = {"Accept": "application/json"}
    if COINMARKETCAL_API_KEY:
        headers["x-api-key"] = COINMARKETCAL_API_KEY
    else:
        logger.warning("COINMARKETCAL_API_KEY не найден. Используются публичные лимиты.")
    params = {"max": limit}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            events = []
            for item in data.get("body", []):
                coins = item.get("coins") or []
                coin = coins[0] if coins else {}
                events.append({
                    "token_name": coin.get("name"),
                    "symbol": coin.get("symbol"),
                    "description": item.get("title"),
                    "event_type": "Event",
                    "event_date": item.get("date_event"),
                    "source_url": item.get("source"),
                })
            return events
    except Exception as e:
        logger.error(f"Ошибка при запросе к CoinMarketCal: {e}")
        return []

async def fetch_icodrops_upcoming(limit: int = 5) -> List[Dict]:
    """Парсит сайт ICO Drops для получения списка предстоящих ICO."""
    url = "https://icodrops.com/category/upcoming-ico/"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select(".ico-main-info")[:limit]
            icos = []
            for card in cards:
                token_name = card.find("h3").get_text(strip=True)
                symbol_elem = card.find("span", class_="ico-list-info")
                symbol = symbol_elem.get_text(strip=True) if symbol_elem else None
                icos.append({
                    "token_name": token_name,
                    "symbol": symbol,
                    "description": "ICO Drops",
                    "event_type": "ICO",
                    "event_date": None,
                    "source_url": url,
                })
            return icos
    except Exception as e:
        logger.error(f"Ошибка при парсинге ICO Drops: {e}")
        return []


async def fetch_coingecko_events(limit: int = 5) -> List[Dict]:
    """Получает список событий из CoinGecko Events API."""
    params = {
        "upcoming_events_only": "true",
        "page": 1,
        "per_page": limit,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(COINGECKO_EVENTS_URL, params=params)
            response.raise_for_status()
            data = response.json()
            events = []
            for item in data.get("data", []):
                coin = (item.get("scoins") or [{}])[0] if item.get("scoins") else {}
                events.append({
                    "token_name": coin.get("name") or item.get("title"),
                    "symbol": coin.get("symbol"),
                    "description": item.get("description"),
                    "event_type": item.get("type"),
                    "event_date": item.get("start_date"),
                    "platform": item.get("platform"),
                    "importance": "high" if item.get("sponsored") else None,
                    "source_url": item.get("website"),
                })
            return events
    except Exception as e:
        logger.error(f"Ошибка при запросе к CoinGecko Events: {e}")
        return []


async def fetch_cryptorank_events(limit: int = 5) -> List[Dict]:
    """Получает события из CryptoRank."""
    headers = {}
    if CRYPTORANK_API_KEY:
        headers["API-KEY"] = CRYPTORANK_API_KEY
    params = {"limit": limit}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(CRYPTORANK_API_URL, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            events = []
            for item in data.get("data", []):
                coin = item.get("coin") or {}
                events.append({
                    "token_name": coin.get("name"),
                    "symbol": coin.get("symbol"),
                    "description": item.get("title"),
                    "event_type": item.get("type"),
                    "event_date": item.get("date"),
                    "platform": item.get("platform"),
                    "importance": item.get("importance"),
                    "source_url": item.get("url"),
                })
            return events
    except Exception as e:
        logger.error(f"Ошибка при запросе к CryptoRank: {e}")
        return []


async def filter_events_by_type(events: List[Dict], event_type: Optional[str]) -> List[Dict]:
    if not event_type:
        return events
    return [e for e in events if str(e.get("event_type", "")).lower() == event_type.lower()]


async def filter_events_by_market_cap(
    events: List[Dict],
    min_cap: float = 0.0,
    max_cap: Optional[float] = None,
) -> List[Dict]:
    if min_cap <= 0 and max_cap is None:
        return events

    filtered = []
    for event in events:
        symbol = event.get("symbol")
        if not symbol:
            continue
        coin_id = await coingecko_client.search_coin(symbol)
        if not coin_id:
            continue
        data = await coingecko_client.get_simple_price(coin_ids=[coin_id])
        if not data or coin_id not in data:
            continue
        cap = data[coin_id].get("usd_market_cap") or 0
        if cap >= min_cap and (max_cap is None or cap <= max_cap):
            filtered.append(event)
    return filtered

async def get_premarket_signals(
    vip: bool = False,
    limit: int = 5,
    event_type: Optional[str] = None,
    min_market_cap: float = 0.0,
    max_market_cap: Optional[float] = None,
) -> List[Dict]:
    """Возвращает список предстоящих событий с возможностью фильтрации."""

    base_limit = limit * 2 if vip else limit
    events: List[Dict] = []

    events += await fetch_coinmarketcal_events(limit=base_limit)
    events += await fetch_icodrops_upcoming(limit=base_limit)
    events += await fetch_coingecko_events(limit=base_limit)
    events += await fetch_cryptorank_events(limit=base_limit)

    if event_type:
        events = await filter_events_by_type(events, event_type)

    if min_market_cap > 0 or max_market_cap is not None:
        events = await filter_events_by_market_cap(
            events, min_cap=min_market_cap, max_cap=max_market_cap
        )

    return events

