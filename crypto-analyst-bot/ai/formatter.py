# ai/formatter.py
# Модуль для преобразования структурированных данных в красивые сообщения.

import os
import logging
import json
import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

# --- ПРОМПТ РАЗДЕЛЕН НА ЧАСТИ ДЛЯ БЕЗОПАСНОЙ СБОРКИ ---
FORMATTER_PROMPT_PART_1 = """
Твоя задача - ТОЛЬКО форматировать JSON-данные о криптовалюте в красивое сообщение для Telegram.
- Используй Markdown: *жирный* для названий и цен, _курсив_ для пояснений.
- Используй эмодзи: 📈, 📉, 💰, 📊.
- НЕ придумывай, НЕ вычисляй и НЕ изменяй данные. Если значения нет или оно равно 0, так и показывай.
- Говори на русском.

Пример:
JSON: {"bitcoin": {"usd": 65000, "usd_market_cap": 1280000000000, "usd_24h_vol": 35000000000, "usd_24h_change": -2.5}}
ОТВЕТ:
📊 *Bitcoin (BTC)*
*Цена:* $65,000.00
*Капитализация:* $1,280,000,000,000
*Объем (24ч):* $35,000,000,000
*Изменение (24ч):* -2.50% 📉

JSON для форматирования:
```json
"""

FORMATTER_PROMPT_PART_2 = """
```
Твой отформатированный ответ:
"""

async def format_data_with_ai(data: dict) -> str:
    """
    Отправляет данные в формате JSON в модель Gemini для форматирования.
    """
    if not GEMINI_API_KEY:
        return f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"

    json_string = json.dumps(data, indent=2, ensure_ascii=False)
    
    # --- ИСПРАВЛЕНИЕ: Безопасное создание промпта через конкатенацию ---
    prompt = FORMATTER_PROMPT_PART_1 + json_string + FORMATTER_PROMPT_PART_2

    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024}
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(GEMINI_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            api_data = response.json()
            formatted_text = api_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if not formatted_text:
                return f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
            return formatted_text
    except Exception as e:
        logger.error(f"Ошибка в ИИ-Форматтере: {e}")
        return f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"