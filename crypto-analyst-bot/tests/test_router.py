import types
import asyncio
import pytest

from utils.intent_router import IntentRouter

def test_intent_router_dispatch():
    async def handler(update, context, payload, db):
        return f"handled {payload}"

    router = IntentRouter()
    router.register("TEST", handler)

    result = asyncio.run(router.dispatch("TEST", None, None, "ok", None))
    assert result == "handled ok"
