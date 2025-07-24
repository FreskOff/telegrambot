"""crypto/pre_market.py
Модуль для получения информации о предстоящих ICO/IDO и новых листингах.
Предоставляет обычную и VIP версии данных.
"""

import os
import logging
from typing import List, Dict
from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
load_dotenv()

COINMARKETCAL_API_KEY = os.getenv("COINMARKETCAL_API_KEY")
COINMARKETCAL_BASE_URL = "https://developers.coinmarketcal.com/v1"

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

async def get_premarket_signals(vip: bool = False, limit: int = 5) -> List[Dict]:
    """Возвращает список предстоящих событий.

    Если vip=True, возвращается расширенный (VIP) список. Пока что это
    заглушка, подготовленная для будущих подписок.
    """
    events = []
    events += await fetch_coinmarketcal_events(limit=limit)
    events += await fetch_icodrops_upcoming(limit=limit)

    if vip:
        events.append({
            "token_name": "VIP",
            "symbol": None,
            "description": "Расширенный список для подписчиков будет доступен позднее.",
            "event_type": "VIP",
            "event_date": None,
            "source_url": None,
        })

    return events
