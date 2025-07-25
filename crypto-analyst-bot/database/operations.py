# database/operations.py
# Функции для выполнения CRUD-операций (Create, Read, Update, Delete) с базой данных.

import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update as sqlalchemy_update, desc, delete as sqlalchemy_delete
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func
from telegram import User as TelegramUser

from .models import (
    User,
    PriceAlert,
    TrackedCoin,
    AlertDirection,
    ChatHistory,
    Product,
    Purchase,
)

logger = logging.getLogger(__name__)

# --- Операции с пользователями ---
async def get_or_create_user(session: AsyncSession, tg_user: TelegramUser) -> User:
    """
    Находит пользователя в БД по его Telegram ID. Если пользователь не найден,
    создает новую запись. Возвращает экземпляр модели User.
    """
    result = await session.execute(select(User).filter(User.id == tg_user.id))
    db_user = result.scalar_one_or_none()
    if db_user:
        # Опционально обновляем данные, если они изменились
        if db_user.username != tg_user.username or db_user.first_name != tg_user.first_name:
            db_user.username = tg_user.username
            db_user.first_name = tg_user.first_name
            db_user.last_name = tg_user.last_name
            await session.commit()
        return db_user
    else:
        new_user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        return new_user

async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    result = await session.execute(select(User).filter(User.id == user_id))
    return result.scalar_one_or_none()

async def update_user_settings(session: AsyncSession, user_id: int, **kwargs):
    if not kwargs:
        return
    await session.execute(
        sqlalchemy_update(User).where(User.id == user_id).values(**kwargs)
    )
    await session.commit()

async def get_user_stats(session: AsyncSession, user_id: int) -> dict:
    user = await get_user(session, user_id)
    result = await session.execute(
        select(func.count()).select_from(ChatHistory).filter(ChatHistory.user_id == user_id)
    )
    count = result.scalar_one() or 0
    return {
        "language": user.language if user else "ru",
        "timezone": user.timezone if user else "UTC",
        "currency": user.currency if user else "USD",
        "message_count": count,
    }

# --- Работа со звёздами ---
async def get_star_balance(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(select(User.stars_balance).filter(User.id == user_id))
    balance = result.scalar_one_or_none()
    return balance or 0

async def add_stars(session: AsyncSession, user_id: int, amount: int):
    if not amount:
        return
    await session.execute(
        sqlalchemy_update(User)
        .where(User.id == user_id)
        .values(stars_balance=User.stars_balance + amount)
    )
    await session.commit()

async def deduct_stars(session: AsyncSession, user_id: int, amount: int) -> bool:
    balance = await get_star_balance(session, user_id)
    if balance < amount:
        return False
    await add_stars(session, user_id, -amount)
    return True

# --- Операции с Алертами ---
async def add_price_alert(session: AsyncSession, user_id: int, symbol: str, price: float, direction: str) -> PriceAlert:
    """Добавляет новый ценовой алерт для пользователя."""
    alert_direction = AlertDirection.ABOVE if direction.lower() == 'above' else AlertDirection.BELOW
    new_alert = PriceAlert(user_id=user_id, coin_symbol=symbol.upper(), target_price=price, direction=alert_direction)
    session.add(new_alert)
    await session.commit()
    await session.refresh(new_alert)
    return new_alert

async def get_user_alerts(session: AsyncSession, user_id: int) -> List[PriceAlert]:
    """Возвращает список активных алертов пользователя."""
    result = await session.execute(select(PriceAlert).filter(PriceAlert.user_id == user_id, PriceAlert.is_active == True))
    return result.scalars().all()

async def get_all_active_alerts(session: AsyncSession) -> List[PriceAlert]:
    """Возвращает все активные алерты всех пользователей для проверки планировщиком."""
    result = await session.execute(select(PriceAlert).filter(PriceAlert.is_active == True).options(selectinload(PriceAlert.user)))
    return result.scalars().all()

async def deactivate_alert(session: AsyncSession, alert_id: int):
    """Деактивирует алерт после того, как он сработал."""
    await session.execute(sqlalchemy_update(PriceAlert).where(PriceAlert.id == alert_id).values(is_active=False, triggered_at=func.now()))
    await session.commit()

async def delete_user_alerts_by_symbol(session: AsyncSession, user_id: int, symbol: str) -> int:
    """Удаляет все активные алерты пользователя для указанного символа."""
    statement = sqlalchemy_delete(PriceAlert).where(
        PriceAlert.user_id == user_id,
        PriceAlert.coin_symbol == symbol.upper(),
        PriceAlert.is_active == True
    )
    result = await session.execute(statement)
    await session.commit()
    return result.rowcount # Возвращает количество удаленных алертов

# --- Операции с Портфолио ---
async def add_coin_to_portfolio(
    session: AsyncSession,
    user_id: int,
    symbol: str,
    quantity: float = 0.0,
    buy_price: float = 0.0,
) -> TrackedCoin:
    """Добавляет монету в портфолио пользователя или обновляет существующую."""
    symbol = symbol.upper()
    result = await session.execute(
        select(TrackedCoin).filter(
            TrackedCoin.user_id == user_id,
            TrackedCoin.coin_symbol == symbol,
        )
    )
    coin = result.scalar_one_or_none()
    if coin:
        if quantity:
            total_qty = (coin.quantity or 0) + quantity
            if total_qty > 0:
                total_cost = (coin.quantity or 0) * (coin.buy_price or 0) + quantity * buy_price
                coin.buy_price = total_cost / total_qty
            coin.quantity = total_qty
        await session.commit()
        await session.refresh(coin)
        return coin

    new_coin = TrackedCoin(
        user_id=user_id,
        coin_symbol=symbol,
        quantity=quantity,
        buy_price=buy_price,
    )
    session.add(new_coin)
    await session.commit()
    await session.refresh(new_coin)
    return new_coin


async def get_user_portfolio(session: AsyncSession, user_id: int) -> List[TrackedCoin]:
    """Возвращает список монет в портфолио пользователя."""
    result = await session.execute(select(TrackedCoin).filter(TrackedCoin.user_id == user_id))
    return result.scalars().all()


async def remove_coin_from_portfolio(session: AsyncSession, user_id: int, symbol: str) -> bool:
    """Удаляет монету из портфолио пользователя."""
    result = await session.execute(
        select(TrackedCoin).filter(
            TrackedCoin.user_id == user_id,
            TrackedCoin.coin_symbol == symbol.upper(),
        )
    )
    coin = result.scalar_one_or_none()
    if not coin:
        return False
    await session.delete(coin)
    await session.commit()
    return True

# --- Операции с Историей Чата ---
async def add_chat_message(session: AsyncSession, user_id: int, role: str, text: str) -> ChatHistory:
    """Добавляет новое сообщение в историю чата пользователя."""
    new_message = ChatHistory(user_id=user_id, role=role, message_text=text)
    session.add(new_message)
    await session.commit()
    await session.refresh(new_message)
    return new_message
async def get_chat_history(session: AsyncSession, user_id: int, limit: int = 10) -> List[ChatHistory]:
    """Возвращает последние N сообщений из истории чата пользователя."""
    result = await session.execute(select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(desc(ChatHistory.timestamp)).limit(limit))
    return list(reversed(result.scalars().all()))

# --- Операции с Магазином ---
async def list_products(session: AsyncSession):
    result = await session.execute(select(Product).filter(Product.is_active == True))
    return result.scalars().all()

async def get_product(session: AsyncSession, product_id: int):
    result = await session.execute(select(Product).filter(Product.id == product_id))
    return result.scalar_one_or_none()

async def add_purchase(session: AsyncSession, user_id: int, product_id: int):
    purchase = Purchase(user_id=user_id, product_id=product_id)
    session.add(purchase)
    await session.commit()
    await session.refresh(purchase)
    return purchase

async def has_purchased(session: AsyncSession, user_id: int, product_id: int) -> bool:
    result = await session.execute(
        select(Purchase).filter(Purchase.user_id == user_id, Purchase.product_id == product_id)
    )
    return result.scalar_one_or_none() is not None
