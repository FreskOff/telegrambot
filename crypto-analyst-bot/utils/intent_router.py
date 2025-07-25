from __future__ import annotations

from typing import Callable, Awaitable, Dict, Optional, Any
import asyncio

Handler = Callable[[Any, Any, str, Any], Awaitable[Any]]

class IntentRouter:
    """Simple mapping from intent names to async handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}

    def register(self, intent: str, handler: Handler) -> None:
        self._handlers[intent.upper()] = handler

    def get(self, intent: str) -> Optional[Handler]:
        return self._handlers.get(intent.upper())

    async def dispatch(self, intent: str, update, context, payload: str, db_session):
        handler = self.get(intent)
        if not handler:
            return None
        if asyncio.iscoroutinefunction(handler):
            return await handler(update, context, payload, db_session)
        return handler(update, context, payload, db_session)
