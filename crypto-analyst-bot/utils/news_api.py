import os
import json
import logging
from typing import List, Dict
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup

from .cache import get_cache, set_cache

logger = logging.getLogger(__name__)

CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")


async def _fetch_cryptopanic(symbol: str, limit: int = 5) -> List[Dict]:
    if not CRYPTOPANIC_API_KEY:
        logger.warning("CRYPTOPANIC_API_KEY not set")
        return []
    params = {
        "auth_token": CRYPTOPANIC_API_KEY,
        "currencies": symbol.upper(),
        "public": "true",
    }
    cache_key = f"cp:{symbol}:{limit}"
    cached = await get_cache(cache_key)
    if cached:
        return json.loads(cached)
    url = "https://cryptopanic.com/api/v1/posts/"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"CryptoPanic API error: {e}")
        return []
    results = []
    for item in data.get("results", [])[:limit]:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "source": item.get("source", {}).get("title"),
            "published_at": item.get("published_at"),
        })
    await set_cache(cache_key, json.dumps(results), ttl=300)
    return results


async def _fetch_coindesk(symbol: str, limit: int = 5) -> List[Dict]:
    url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
    cache_key = f"cd:{symbol}:{limit}"
    cached = await get_cache(cache_key)
    if cached:
        return json.loads(cached)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            text = resp.text
    except Exception as e:
        logger.error(f"CoinDesk RSS error: {e}")
        return []
    soup = BeautifulSoup(text, "xml")
    items = soup.find_all("item")
    results = []
    for itm in items:
        title = itm.title.text if itm.title else ""
        if symbol.lower() not in title.lower():
            continue
        link = itm.link.text if itm.link else ""
        pub_date = itm.pubDate.text if itm.pubDate else ""
        dt = None
        if pub_date:
            try:
                dt = parsedate_to_datetime(pub_date)
            except Exception:
                dt = None
        results.append({
            "title": title,
            "url": link,
            "source": "CoinDesk",
            "published_at": dt.isoformat() if dt else None,
        })
        if len(results) >= limit:
            break
    await set_cache(cache_key, json.dumps(results), ttl=300)
    return results


async def get_news(symbol: str, limit: int = 5) -> List[Dict]:
    news: List[Dict] = []
    news += await _fetch_cryptopanic(symbol, limit)
    news += await _fetch_coindesk(symbol, limit)
    news.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return news[:limit]
