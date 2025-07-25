# utils/api_clients.py
# Модуль для взаимодействия с внешними API, такими как CoinGecko,
# CoinMarketCap и Binance.

import os
import logging
import httpx
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

BINANCE_BASE_URL = "https://api.binance.com"

class CoinGeckoClient:
    """
    Асинхронный клиент для взаимодействия с API CoinGecko.
    """
    def __init__(self, api_key: str = COINGECKO_API_KEY):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.headers = {"accept": "application/json"}
        
        if api_key:
            self.headers["x-cg-demo-api-key"] = api_key
            logger.info("Используется API ключ для CoinGecko.")
        else:
            logger.warning("COINGECKO_API_KEY не найден. Используется публичный API с возможными ограничениями.")

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """
        Приватный метод для выполнения асинхронных GET-запросов.
        """
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Ошибка при запросе к CoinGecko API ({url}): {e}")
            return None

    async def get_simple_price(self, coin_ids: List[str], vs_currencies: List[str] = ['usd']) -> Optional[Dict]:
        """
        Получает текущую цену для одной или нескольких монет.
        """
        if not coin_ids: return None
        params = {
            "ids": ",".join(coin_ids),
            "vs_currencies": ",".join(vs_currencies),
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        }
        return await self._request("/simple/price", params)

    async def search_coin(self, query: str) -> Optional[str]:
        """
        Ищет монету по названию или символу и возвращает её ID.
        Возвращает ID наиболее релевантной монеты или None.
        """
        logger.info(f"Поиск монеты по запросу: '{query}'")
        data = await self._request("/search", params={"query": query})
        if data and data.get('coins'):
            # Возвращаем ID первого и самого релевантного результата
            top_result_id = data['coins'][0]['id']
            logger.info(f"Найдена монета: '{top_result_id}' для запроса '{query}'")
            return top_result_id
        logger.warning(f"Монета по запросу '{query}' не найдена.")
        return None

    async def get_market_chart(self, coin_id: str, vs_currency: str = 'usd', days: int = 30) -> Optional[Dict]:
        """Возвращает исторические данные цены за указанный период."""
        endpoint = f"/coins/{coin_id}/market_chart"
        params = {"vs_currency": vs_currency, "days": days}
        return await self._request(endpoint, params)

# Создаем один экземпляр клиента для использования во всем приложении
coingecko_client = CoinGeckoClient()


class CoinMarketCapClient:
    """Асинхронный клиент CoinMarketCap."""

    def __init__(self, api_key: str = COINMARKETCAP_API_KEY):
        self.base_url = "https://pro-api.coinmarketcap.com/v1"
        self.headers = {"Accepts": "application/json"}
        if api_key:
            self.headers["X-CMC_PRO_API_KEY"] = api_key
        else:
            logger.warning(
                "COINMARKETCAP_API_KEY не найден. Используются публичные лимиты."
            )

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Ошибка при запросе к CoinMarketCap API ({url}): {e}")
            return None

    async def get_market_pairs(self, symbol: str, limit: int = 5) -> Optional[List[Dict]]:
        params = {"symbol": symbol.upper(), "limit": limit}
        data = await self._request("/cryptocurrency/market-pairs/latest", params)
        if not data or "data" not in data:
            return None
        market_data = data["data"].get(symbol.upper()) or {}
        pairs = []
        for item in market_data.get("market_pairs", []):
            quote_info = next(iter(item.get("quote", {}).values()), {})
            pairs.append(
                {
                    "exchange": item.get("exchange_name"),
                    "pair": item.get("market_pair"),
                    "price": quote_info.get("price"),
                    "url": item.get("market_url"),
                }
            )
        return pairs


class BinanceClient:
    """Асинхронный клиент Binance для получения цены."""

    def __init__(self, base_url: str = BINANCE_BASE_URL):
        self.base_url = base_url

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Ошибка при запросе к Binance API ({url}): {e}")
            return None

    async def get_price(self, symbol: str) -> Optional[float]:
        data = await self._request("/api/v3/ticker/price", params={"symbol": symbol.upper()})
        if data and "price" in data:
            return float(data["price"])
        return None


# Экземпляры клиентов для использования в приложении
coinmarketcap_client = CoinMarketCapClient()
binance_client = BinanceClient()
