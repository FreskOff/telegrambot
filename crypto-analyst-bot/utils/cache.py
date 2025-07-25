import os
import json
import logging
from typing import Optional

try:
    import redis.asyncio as redis
except Exception:
    redis = None

logger = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

if redis:
    redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
else:
    redis_client = None
    logger.warning("redis-py not installed, caching disabled")

async def get_cache(key: str) -> Optional[str]:
    if not redis_client:
        return None
    try:
        return await redis_client.get(key)
    except Exception as e:
        logger.error(f"Failed to get cache for {key}: {e}")
        return None

async def set_cache(key: str, value: str, ttl: int = 60) -> None:
    if not redis_client:
        return
    try:
        await redis_client.set(key, value, ex=ttl)
    except Exception as e:
        logger.error(f"Failed to set cache for {key}: {e}")
