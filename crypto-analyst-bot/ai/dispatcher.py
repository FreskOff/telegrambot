# ai/dispatcher.py
# Модуль для двухступенчатого определения намерения и извлечения данных
# с использованием строгих, основанных на правилах, промптов.

import os
import json
import logging
import httpx
from dotenv import load_dotenv
from typing import Dict, Tuple

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("Ключ GEMINI_API_KEY не найден.")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_GPT_MODEL", "gpt-4o-mini")

# --- Загрузка конфигурации намерений ---
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
INTENTS_FILE = os.path.join(BASE_DIR, "config", "intents.json")
try:
    with open(INTENTS_FILE, "r", encoding="utf-8") as f:
        INTENT_DESCRIPTIONS: Dict[str, str] = json.load(f)
except Exception as e:  # pragma: no cover - fallback only on error
    logger.error(f"Не удалось загрузить {INTENTS_FILE}: {e}")
    INTENT_DESCRIPTIONS = {
        "GENERAL_CHAT": "Общий разговор.",
        "CRYPTO_INFO": "Запрос цены.",
        "UNSUPPORTED_INTENT": "Неизвестная категория.",
    }

INTENT_LIST_TEXT = "\n".join(
    f"- {name}: {desc}" for name, desc in INTENT_DESCRIPTIONS.items()
)


# --- ПРОМПТ 1: Строгая классификация намерения ---
CLASSIFY_INTENT_PROMPT = """
Ты — системный мозг крипто-бота. Твоя задача — проанализировать запрос пользователя и определить его основное намерение. Твой ответ должен быть ТОЛЬКО ОДНИМ словом из предоставленного списка. Не добавляй ничего лишнего.

**Список Допустимых Намерений:**
{INTENT_LIST_TEXT}

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
- **DEFI_FARM:** Просто верни `payload:` (нет дополнительных параметров).
- **NFT_ANALYTICS:** Извлеки слаг коллекции в ключ `slug`. (Например, "nft bored ape" -> `slug:bored-ape-yacht-club`)
- **DEPIN_PROJECTS:** Просто верни `payload:`.
- **CRYPTO_NEWS:** Извлеки символ токена в ключ `symbol`.
- **PRICE_PREDICTION:** Извлеки символ токена в ключ `symbol`.
- **SHOP_BUY:** Извлеки идентификатор товара в ключ `product_id`.
- **SUBSCRIPTION:** Просто верни `payload:`.
- **COURSE_INFO:** Извлеки идентификатор курса в ключ `course_id`.
- **Для всех остальных намерений:** Просто верни `payload:`, если нет очевидных данных для извлечения.

**Твой ответ (в формате `ключ:значение`):**
"""

async def classify_intent(user_input: str) -> str:
    """Шаг 1: Определяет только тип намерения."""
    prompt = CLASSIFY_INTENT_PROMPT.format(
        user_input=user_input,
        INTENT_LIST_TEXT=INTENT_LIST_TEXT,
    )

    if GEMINI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {'Content-Type': 'application/json'}
                payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0, "maxOutputTokens": 32}}
                response = await client.post(GEMINI_API_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                intent_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "UNSUPPORTED_INTENT").strip()
                if intent_text:
                    return intent_text
        except Exception as e:
            logger.warning(f"Gemini classify failed: {e}")

    if OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
                payload = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 32}
                resp = await client.post(OPENAI_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "UNSUPPORTED_INTENT").strip()
                return text if text else "UNSUPPORTED_INTENT"
        except Exception as e:
            logger.error(f"OpenAI classify failed: {e}")

    return "UNSUPPORTED_INTENT"


async def extract_entities(intent: str, user_input: str) -> Dict[str, str]:
    """Шаг 2: Извлекает данные для конкретного намерения."""
    prompt = EXTRACT_ENTITIES_PROMPT.format(intent=intent, user_input=user_input)

    if GEMINI_API_KEY:
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
            logger.warning(f"Gemini extract failed: {e}")

    if OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
                payload = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 128}
                resp = await client.post(OPENAI_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "payload:").strip()
                if ":" in text:
                    key, value = text.split(":", 1)
                    return {key.strip(): value.strip()}
                return {"payload": text}
        except Exception as e:
            logger.error(f"OpenAI extract failed: {e}")

    return {"payload": "AI_API_HTTP_ERROR"}
