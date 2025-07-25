# ai/dispatcher.py
# Модуль для двухступенчатого определения намерения и извлечения данных
# с использованием строгих, основанных на правилах, промптов.

import os
import logging
import httpx
from dotenv import load_dotenv
from typing import Dict

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("Ключ GEMINI_API_KEY не найден.")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"


# --- ПРОМПТ 1: Строгая классификация намерения ---
CLASSIFY_INTENT_PROMPT = """
Ты — системный мозг крипто-бота. Твоя задача — проанализировать запрос пользователя и определить его основное намерение. Твой ответ должен быть ТОЛЬКО ОДНИМ словом из предоставленного списка. Не добавляй ничего лишнего.

**Список Допустимых Намерений:**
- GENERAL_CHAT: Общий разговор, эмоции, приветствия, благодарности, вопросы о тебе.
- CRYPTO_INFO: Прямой запрос цены, курса, стоимости криптовалюты.
- TOKEN_ANALYSIS: Глубокий анализ, новости, описание токена.
- WHERE_TO_BUY: Вопрос, где можно купить криптовалюту.
- PREMARKET_SCAN: Вопросы о новых токенах, ICO, предстоящих листингах.
- EDU_LESSON: Запрос на объяснение крипто-терминов и концепций.
- SETUP_ALERT: Команда на установку ценового оповещения.
- MANAGE_ALERTS: Команда на управление существующими оповещениями.
- PORTFOLIO_SUMMARY: Запрос на показ портфеля.
- TRACK_COIN: Команда на добавление монеты в портфель.
- UNTRACK_COIN: Команда на удаление монеты из портфеля.
- BOT_HELP: Прямой запрос помощи.
- ADMIN_ACTION: Запросы на управление ботом (только для администратора).
- UNSUPPORTED_INTENT: Все, что не подходит под другие категории.

**Запрос пользователя:** "{user_input}"

**Твой вердикт (одно слово):**
"""

# --- ПРОМПТ 2: Строгое извлечение данных (сущностей) ---
EXTRACT_ENTITIES_PROMPT = """
Ты — системный экстрактор данных для крипто-бота. Твоя задача — извлечь из запроса пользователя конкретные данные, основываясь на уже известном намерении.

**Правила:**
1.  Ответь СТРОГО в формате `ключ:значение`.
2.  Если нужных данных в запросе нет, верни `payload:`.
3.  Для чисел убирай пробелы и символы валют.

---
**Намерение:** "{intent}"
**Запрос пользователя:** "{user_input}"
---

**Инструкции по извлечению для каждого намерения:**
- **CRYPTO_INFO:** Извлеки все символы токенов в ключ `symbols`. (Например, "цена btc и eth" -> `symbols:BTC,ETH`)
- **TOKEN_ANALYSIS:** Извлеки название или символ токена в ключ `topic`. (Например, "новости про Solana" -> `topic:Solana`)
- **SETUP_ALERT:** Извлеки данные в формате `СИМВОЛ:ЦЕНА:НАПРАВЛЕНИЕ` в ключ `alert_data`. Если направление не указано, используй `above`. (Например, "алерт на биток 120 000" -> `alert_data:BTC:120000:above`)
- **EDU_LESSON:** Извлеки тему урока в ключ `topic`. (Например, "что такое дао" -> `topic:DAO`)
- **TRACK_COIN:** Извлеки символ токена в ключ `symbol`. (Например, "добавь рипл" -> `symbol:XRP`)
- **UNTRACK_COIN:** Извлеки символ токена в ключ `symbol`. (Например, "удали кардано" -> `symbol:ADA`)
- **WHERE_TO_BUY:** Извлеки символ токена в ключ `symbol`. (Например, "где купить догикоин" -> `symbol:DOGE`)
- **ADMIN_ACTION:** Извлеки текст команды в ключ `command`.
- **Для всех остальных намерений:** Просто верни `payload:`, если нет очевидных данных для извлечения.

**Твой ответ (в формате `ключ:значение`):**
"""

async def classify_intent(user_input: str, is_admin: bool = False) -> str:
    """Шаг 1: Определяет только тип намерения."""
    if not GEMINI_API_KEY:
        return "UNSUPPORTED_INTENT"
    prompt = CLASSIFY_INTENT_PROMPT.format(user_input=user_input)
    if is_admin:
        prompt += "\n(Запрос от администратора)"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {'Content-Type': 'application/json'}
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0, "maxOutputTokens": 32}}
            response = await client.post(GEMINI_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            intent_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "UNSUPPORTED_INTENT").strip()
            return intent_text if intent_text else "UNSUPPORTED_INTENT"
    except Exception as e:
        logger.error(f"Ошибка на шаге 1 (классификация): {e}")
        return "UNSUPPORTED_INTENT"


async def extract_entities(intent: str, user_input: str, is_admin: bool = False) -> Dict[str, str]:
    """Шаг 2: Извлекает данные для конкретного намерения."""
    if not GEMINI_API_KEY:
        return {"payload": "AI_SERVICE_UNCONFIGURED"}
    prompt = EXTRACT_ENTITIES_PROMPT.format(intent=intent, user_input=user_input)
    if is_admin:
        prompt += "\n(Запрос от администратора)"
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {'Content-Type': 'application/json'}
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0, "maxOutputTokens": 128}}
            response = await client.post(GEMINI_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            response_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "payload:").strip()
            
            if ":" in response_text:
                key, value = response_text.split(":", 1)
                return {key.strip(): value.strip()}
            return {"payload": ""}
    except Exception as e:
        logger.error(f"Ошибка на шаге 2 (извлечение): {e}")
        return {"payload": "AI_API_HTTP_ERROR"}
