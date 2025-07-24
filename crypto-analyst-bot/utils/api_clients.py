# utils/api_clients.py
# Модуль для взаимодействия с внешними API, такими как CoinGecko.

import os
import logging
import httpx
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

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

# Создаем один экземпляр клиента для использования во всем приложении
coingecko_client = CoinGeckoClient()