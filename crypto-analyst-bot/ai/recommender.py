import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from database import operations as db_ops

logger = logging.getLogger(__name__)

async def generate_recommendations(session: AsyncSession, user_id: int) -> list[tuple]:
    """Возвращает список рекомендаций на основе истории и покупок."""
    recs: list[tuple] = []

    usage = await db_ops.get_user_stats(session, user_id)
    history = await db_ops.get_chat_history(session, user_id, limit=20)
    history_text = " ".join(
        h.message_text.lower() for h in history if h.role == "user"
    )

    purchases = await db_ops.list_user_purchases(session, user_id)
    purchased_product_ids = {p.product_id for p in purchases}
    course_purchases = await db_ops.list_user_course_purchases(session, user_id)
    purchased_course_ids = {p.course_id for p in course_purchases}

    subscription = await db_ops.get_subscription(session, user_id)
    if subscription and subscription.is_active and subscription.next_payment:
        days_left = (subscription.next_payment - datetime.utcnow()).days
        if days_left <= 5:
            recs.append(("renew", subscription.next_payment.strftime("%Y-%m-%d")))
    elif usage.get("message_count", 0) >= 20:
        recs.append(("subscribe", None))

    courses = await db_ops.list_courses(session)
    for c in courses:
        if c.id in purchased_course_ids:
            continue
        title_words = {w.lower() for w in c.title.split()}
        if any(w in history_text for w in title_words):
            recs.append(("course", c.id, c.title, c.stars_price))

    products = await db_ops.list_products(session)
    for p in products:
        if p.id in purchased_product_ids:
            continue
        if p.item_type == "signal" and "сигнал" in history_text:
            recs.append(("product", p.id, p.name, p.stars_price))

    return recs
