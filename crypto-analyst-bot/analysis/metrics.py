"""Utility functions for calculating basic bot metrics."""

from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Purchase, Subscription


async def active_users_count(session: AsyncSession, days: int = 30) -> int:
    """Return number of users active in the last ``days`` days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await session.execute(
        select(func.count()).select_from(User).where(User.last_activity_at >= cutoff)
    )
    return result.scalar_one() or 0


async def purchase_frequency(session: AsyncSession, days: int = 30) -> float:
    """Average number of purchases per user for the last ``days`` days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    total_purchases = await session.execute(
        select(func.count()).select_from(Purchase).where(Purchase.purchased_at >= cutoff)
    )
    purchase_count = total_purchases.scalar_one() or 0

    user_result = await session.execute(
        select(func.count(distinct(Purchase.user_id))).where(Purchase.purchased_at >= cutoff)
    )
    user_count = user_result.scalar_one() or 0

    return purchase_count / user_count if user_count else 0.0


async def subscription_stats(session: AsyncSession) -> Dict[str, int]:
    """Return total and active subscription counts."""
    total_result = await session.execute(
        select(func.count()).select_from(Subscription)
    )
    total = total_result.scalar_one() or 0

    active_result = await session.execute(
        select(func.count()).select_from(Subscription).where(Subscription.is_active == True)
    )
    active = active_result.scalar_one() or 0

    return {"total": total, "active": active}


async def gather_metrics(session: AsyncSession) -> Dict[str, object]:
    """Collect and return all analytics metrics."""
    return {
        "active_users": await active_users_count(session),
        "purchase_frequency": await purchase_frequency(session),
        "subscriptions": await subscription_stats(session),
    }

