import tempfile
from datetime import datetime
from typing import List, Tuple
import matplotlib.pyplot as plt

from .api_clients import coingecko_client

async def fetch_price_history(symbol: str, days: int = 30) -> List[Tuple[str, float]]:
    coin_id = await coingecko_client.search_coin(symbol)
    if not coin_id:
        return []
    data = await coingecko_client.get_market_chart(coin_id, days=days)
    if not data or "prices" not in data:
        return []
    prices = []
    for ts, price in data["prices"]:
        date = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        prices.append((date, price))
    return prices

async def create_price_chart(symbol: str, days: int = 30) -> str | None:
    history = await fetch_price_history(symbol, days=days)
    if not history:
        return None
    dates, values = zip(*history)
    plt.figure(figsize=(6, 3))
    plt.plot(dates, values)
    plt.title(f"{symbol.upper()} price ({days}d)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    plt.savefig(tmp.name)
    plt.close()
    return tmp.name
