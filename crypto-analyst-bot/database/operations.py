# database/operations.py
# Функции для выполнения CRUD-операций (Create, Read, Update, Delete) с базой данных.

import logging
from typing import List, Optional, Any
from datetime import datetime, timedelta
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
    Dialog,
    AlertDirection,
    ChatHistory,
    Product,
    Purchase,
    Subscription,
    Course,
    CoursePurchase,
    UsageStats,
    NewsArticle,
)
from utils import hash_value

logger = logging.getLogger(__name__)

async def safe_commit(session: AsyncSession):
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Ошибка при commit(): {e}")
        raise

# --- Операции с пользователями ---
async def get_or_create_user(session: AsyncSession, tg_user: TelegramUser) -> User:
    """
    Находит пользователя в БД по его Telegram ID. Если пользователь не найден,
    создает новую запись. Возвращает экземпляр модели User.
    """
    result = await session.execute(select(User).filter(User.id == tg_user.id))
    db_user = result.scalar_one_or_none()
    if db_user:
        updated = False
        if db_user.username != tg_user.username or db_user.first_name != tg_user.first_name or db_user.last_name != tg_user.last_name:
            db_user.username = tg_user.username
            db_user.first_name = tg_user.first_name
            db_user.last_name = tg_user.last_name
            updated = True
        db_user.last_activity_at = datetime.now(datetime.UTC)
        db_user.last_contact_at = datetime.now(datetime.UTC)
        updated = True
        if updated:
            try:
                await safe_commit(session)
                await session.refresh(db_user)
            except Exception as e:
                logger.error(f"Ошибка при обновлении объекта после commit: {e}")
                raise
        return db_user
    else:
        new_user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            last_activity_at=datetime.now(datetime.UTC),
            last_contact_at=datetime.now(datetime.UTC),
            show_recommendations=True,
        )
        session.add(new_user)
        try:
            await safe_commit(session)
            await session.refresh(new_user)
        except Exception as e:
            logger.error(f"Ошибка при обновлении объекта после commit: {e}")
            raise
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
    await safe_commit(session)

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
        "price_requests": user.price_requests if user else 0,
        "analysis_requests": user.analysis_requests if user else 0,
        "lesson_requests": user.lesson_requests if user else 0,
        "stars_spent": user.stars_spent if user else 0,
        "last_contact": user.last_contact_at.isoformat() if user and user.last_contact_at else None,
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
    await safe_commit(session)
    await update_usage_stats(session, user_id)

async def increment_request_counter(session: AsyncSession, user_id: int, field: str):
    if field not in ("price_requests", "analysis_requests", "lesson_requests"):
        return
    await session.execute(
        sqlalchemy_update(User)
        .where(User.id == user_id)
        .values(**{field: getattr(User, field) + 1, "last_contact_at": datetime.now(datetime.UTC)})
    )
    await safe_commit(session)
    await update_usage_stats(session, user_id)

async def deduct_stars(session: AsyncSession, user_id: int, amount: int) -> bool:
    balance = await get_star_balance(session, user_id)
    if balance < amount:
        return False
    await session.execute(
        sqlalchemy_update(User)
        .where(User.id == user_id)
        .values(
            stars_balance=User.stars_balance - amount,
            stars_spent=User.stars_spent + amount,
        )
    )
    await safe_commit(session)
    await update_usage_stats(session, user_id)
    return True

async def update_usage_stats(session: AsyncSession, user_id: int):
    """Обновляет агрегированную статистику по пользователю."""
    user = await get_user(session, user_id)
    if not user:
        return
    fav = max(
        (
            ("price", user.price_requests),
            ("analysis", user.analysis_requests),
            ("lesson", user.lesson_requests),
        ),
        key=lambda x: x[1],
    )[0]
    result = await session.execute(select(UsageStats).filter(UsageStats.user_id == user_id))
    stats = result.scalar_one_or_none()
    if stats:
        stats.last_activity = user.last_contact_at
        stats.stars_spent = user.stars_spent
        stats.favorite_function = fav
    else:
        stats = UsageStats(
            user_id=user_id,
            last_activity=user.last_contact_at,
            stars_spent=user.stars_spent,
            favorite_function=fav,
        )
        session.add(stats)
    await safe_commit(session)

# --- Операции с Алертами ---
async def add_price_alert(session: AsyncSession, user_id: int, symbol: str, price: float, direction: str) -> PriceAlert:
    """Добавляет новый ценовой алерт для пользователя."""
    alert_direction = AlertDirection.ABOVE if direction.lower() == 'above' else AlertDirection.BELOW
    new_alert = PriceAlert(user_id=user_id, coin_symbol=symbol.upper(), target_price=price, direction=alert_direction)
    session.add(new_alert)
    try:
        await safe_commit(session)
        await session.refresh(new_alert)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
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
    await safe_commit(session)

async def delete_user_alerts_by_symbol(session: AsyncSession, user_id: int, symbol: str) -> int:
    """Удаляет все активные алерты пользователя для указанного символа."""
    statement = sqlalchemy_delete(PriceAlert).where(
        PriceAlert.user_id == user_id,
        PriceAlert.coin_symbol == symbol.upper(),
        PriceAlert.is_active == True
    )
    result = await session.execute(statement)
    await safe_commit(session)
    return result.rowcount # Возвращает количество удаленных алертов

# --- Операции с Портфолио ---
async def add_coin_to_portfolio(
    session: AsyncSession,
    user_id: int,
    symbol: str,
    quantity: float = 0.0,
    buy_price: float = 0.0,
    buy_date: datetime | None = None,
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
        if buy_date:
            coin.purchase_date = buy_date
        try:
            await safe_commit(session)
            await session.refresh(coin)
        except Exception as e:
            logger.error(f"Ошибка при обновлении объекта после commit: {e}")
            raise
        return coin

    new_coin = TrackedCoin(
        user_id=user_id,
        coin_symbol=symbol,
        quantity=quantity,
        buy_price=buy_price,
        purchase_date=buy_date,
    )
    session.add(new_coin)
    try:
        await safe_commit(session)
        await session.refresh(new_coin)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
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
    await safe_commit(session)
    return True

# --- Операции с Диалогами ---
async def get_active_dialog(session: AsyncSession, user_id: int) -> Optional[Dialog]:
    result = await session.execute(
        select(Dialog).filter(Dialog.user_id == user_id, Dialog.is_active == True)
    )
    return result.scalar_one_or_none()


async def start_dialog(session: AsyncSession, user_id: int, topic: str | None = None) -> Dialog:
    dialog = await get_active_dialog(session, user_id)
    if dialog:
        return dialog
    dialog = Dialog(user_id=user_id, topic=topic)
    session.add(dialog)
    try:
        await safe_commit(session)
        await session.refresh(dialog)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    return dialog


async def end_dialog(session: AsyncSession, dialog_id: int):
    await session.execute(
        sqlalchemy_update(Dialog)
        .where(Dialog.id == dialog_id)
        .values(is_active=False, ended_at=datetime.now(datetime.UTC))
    )
    await safe_commit(session)


async def update_dialog(session: AsyncSession, dialog_id: int, **kwargs):
    if not kwargs:
        return
    await session.execute(
        sqlalchemy_update(Dialog).where(Dialog.id == dialog_id).values(**kwargs)
    )
    await safe_commit(session)


async def get_top_user_topics(session: AsyncSession, user_id: int, limit: int = 3) -> List[str]:
    result = await session.execute(
        select(ChatHistory.request_type, func.count())
        .filter(ChatHistory.user_id == user_id, ChatHistory.request_type != None)
        .group_by(ChatHistory.request_type)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [row[0] for row in result.all()]

# --- Операции с Историей Чата ---
async def add_chat_message(
    session: AsyncSession,
    user_id: int,
    role: str,
    text: str,
    *,
    dialog_id: Optional[int] = None,
    request_type: Optional[str] = None,
    entities: Optional[Any] = None,
    duration_ms: Optional[int] = None,
    error: bool = False,
    event: Optional[str] = None,
) -> ChatHistory:
    """Добавляет новое сообщение в историю чата пользователя."""
    user = await get_user(session, user_id)
    if dialog_id is None:
        dialog = await start_dialog(session, user_id)
        dialog_id = dialog.id
    new_message = ChatHistory(
        user_id=user_id,
        dialog_id=dialog_id,
        role=role,
        message_text=text,
        username_hash=hash_value(user.username) if user else None,
        first_name_hash=hash_value(user.first_name) if user else None,
        language=user.language if user else "ru",
        timezone=user.timezone if user else "UTC",
        currency=user.currency if user else "USD",
        request_type=request_type,
        entities=(
            entities if isinstance(entities, str) else None if entities is None else str(entities)
        ),
        duration_ms=duration_ms,
        error=error,
        event=event,
    )
    session.add(new_message)
    await session.execute(
        sqlalchemy_update(User)
        .where(User.id == user_id)
        .values(last_contact_at=datetime.now(datetime.UTC))
    )
    try:
        await safe_commit(session)
        await session.refresh(new_message)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    return new_message

async def update_chat_message(session: AsyncSession, message_id: int, **kwargs):
    if not kwargs:
        return
    await session.execute(
        sqlalchemy_update(ChatHistory).where(ChatHistory.id == message_id).values(**kwargs)
    )
    await safe_commit(session)
async def get_chat_history(session: AsyncSession, user_id: int, limit: int = 10) -> List[ChatHistory]:
    """Возвращает последние N сообщений из истории чата пользователя."""
    result = await session.execute(select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(desc(ChatHistory.timestamp)).limit(limit))
    return list(reversed(result.scalars().all()))

# --- Отзывы ---
async def add_feedback(session: AsyncSession, user_id: int, text: str) -> ChatHistory:
    """Сохраняет отзыв пользователя."""
    return await add_chat_message(
        session=session,
        user_id=user_id,
        role="user",
        text=text,
        event="feedback",
    )


async def get_feedback_messages(session: AsyncSession, limit: int = 100) -> List[ChatHistory]:
    """Возвращает последние отзывы пользователей."""
    result = await session.execute(
        select(ChatHistory)
        .filter(ChatHistory.event == "feedback")
        .order_by(desc(ChatHistory.timestamp))
        .limit(limit)
    )
    return result.scalars().all()

# --- Операции с Магазином ---
async def list_products(session: AsyncSession):
    result = await session.execute(select(Product).filter(Product.is_active == True))
    return result.scalars().all()

async def get_product(session: AsyncSession, product_id: int):
    result = await session.execute(select(Product).filter(Product.id == product_id))
    return result.scalar_one_or_none()

async def create_product(
    session: AsyncSession,
    name: str,
    description: str,
    item_type: str,
    stars_price: int,
    content_type: str,
    content_value: str,
    rating: int = 0,
    is_active: bool = True,
) -> Product:
    product = Product(
        name=name,
        description=description,
        rating=rating,
        item_type=item_type,
        stars_price=stars_price,
        content_type=content_type,
        content_value=content_value,
        is_active=is_active,
    )
    session.add(product)
    try:
        await safe_commit(session)
        await session.refresh(product)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    return product

async def update_product(session: AsyncSession, product_id: int, **kwargs) -> None:
    if not kwargs:
        return
    await session.execute(
        sqlalchemy_update(Product).where(Product.id == product_id).values(**kwargs)
    )
    await safe_commit(session)

async def delete_product(session: AsyncSession, product_id: int) -> None:
    await session.execute(sqlalchemy_delete(Product).where(Product.id == product_id))
    await safe_commit(session)

async def add_purchase(session: AsyncSession, user_id: int, product_id: int):
    purchase = Purchase(user_id=user_id, product_id=product_id)
    session.add(purchase)
    try:
        await safe_commit(session)
        await session.refresh(purchase)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    await update_usage_stats(session, user_id)
    return purchase

async def has_purchased(session: AsyncSession, user_id: int, product_id: int) -> bool:
    result = await session.execute(
        select(Purchase).filter(Purchase.user_id == user_id, Purchase.product_id == product_id)
    )
    return result.scalar_one_or_none() is not None


# --- Подписки ---
async def create_or_update_subscription(
    session: AsyncSession,
    user_id: int,
    is_active: bool = False,
    next_payment: Optional[datetime] = None,
    level: str = "basic",
) -> Subscription:
    result = await session.execute(select(Subscription).filter(Subscription.user_id == user_id))
    sub = result.scalar_one_or_none()
    if sub:
        sub.is_active = is_active
        sub.next_payment = next_payment
        sub.level = level or sub.level
    else:
        sub = Subscription(user_id=user_id, is_active=is_active, next_payment=next_payment, level=level)
        session.add(sub)
    try:
        await safe_commit(session)
        await session.refresh(sub)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    await update_usage_stats(session, user_id)
    return sub


async def get_subscription(session: AsyncSession, user_id: int) -> Optional[Subscription]:
    result = await session.execute(select(Subscription).filter(Subscription.user_id == user_id))
    return result.scalar_one_or_none()


async def get_active_subscriptions(session: AsyncSession) -> List[Subscription]:
    result = await session.execute(select(Subscription).filter(Subscription.is_active == True))
    return result.scalars().all()


async def get_subscription_end_date(session: AsyncSession, user_id: int) -> str | None:
    """Return subscription end date as DD.MM.YYYY string or None."""
    sub = await get_subscription(session, user_id)
    if sub and sub.next_payment:
        return sub.next_payment.strftime('%d.%m.%Y')
    return None


async def total_users(session: AsyncSession) -> int:
    """Return total number of registered users."""
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one() or 0


# --- Курсы и покупки курсов ---
async def list_courses(session: AsyncSession):
    result = await session.execute(select(Course).filter(Course.is_active == True))
    return result.scalars().all()


async def get_course(session: AsyncSession, course_id: int):
    result = await session.execute(select(Course).filter(Course.id == course_id))
    return result.scalar_one_or_none()

async def create_course(
    session: AsyncSession,
    title: str,
    description: str,
    stars_price: int,
    content_type: str,
    file_id: Optional[str] = None,
    is_active: bool = True,
) -> Course:
    course = Course(
        title=title,
        description=description,
        stars_price=stars_price,
        content_type=content_type,
        file_id=file_id,
        is_active=is_active,
    )
    session.add(course)
    try:
        await safe_commit(session)
        await session.refresh(course)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    return course

async def update_course(session: AsyncSession, course_id: int, **kwargs) -> None:
    if not kwargs:
        return
    await session.execute(
        sqlalchemy_update(Course).where(Course.id == course_id).values(**kwargs)
    )
    await safe_commit(session)

async def delete_course(session: AsyncSession, course_id: int) -> None:
    await session.execute(sqlalchemy_delete(Course).where(Course.id == course_id))
    await safe_commit(session)


async def add_course_purchase(session: AsyncSession, user_id: int, course_id: int):
    purchase = CoursePurchase(user_id=user_id, course_id=course_id)
    session.add(purchase)
    try:
        await safe_commit(session)
        await session.refresh(purchase)
    except Exception as e:
        logger.error(f"Ошибка при обновлении объекта после commit: {e}")
        raise
    return purchase


async def has_purchased_course(session: AsyncSession, user_id: int, course_id: int) -> bool:
    result = await session.execute(
        select(CoursePurchase).filter(CoursePurchase.user_id == user_id, CoursePurchase.course_id == course_id)
    )
    return result.scalar_one_or_none() is not None


async def list_user_purchases(session: AsyncSession, user_id: int) -> list[Purchase]:
    """Возвращает все покупки пользователя."""
    result = await session.execute(
        select(Purchase).filter(Purchase.user_id == user_id)
    )
    return result.scalars().all()


async def list_user_course_purchases(session: AsyncSession, user_id: int) -> list[CoursePurchase]:
    """Возвращает все покупки курсов пользователя."""
    result = await session.execute(
        select(CoursePurchase).filter(CoursePurchase.user_id == user_id)
    )
    return result.scalars().all()

# --- Административная аналитика ---
async def list_recent_users(session: AsyncSession, limit: int = 20) -> list[User]:
    """Возвращает последних зарегистрировавшихся пользователей."""
    result = await session.execute(
        select(User).order_by(User.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


async def list_recent_purchases(session: AsyncSession, limit: int = 20) -> list[Purchase]:
    """Возвращает последние покупки."""
    result = await session.execute(
        select(Purchase).order_by(Purchase.purchased_at.desc()).limit(limit)
    )
    return result.scalars().all()


async def get_most_purchased_products(session: AsyncSession, limit: int = 5) -> list[tuple[str, int]]:
    """Возвращает самые популярные товары (имя, количество покупок)."""
    result = await session.execute(
        select(Product.name, func.count(Purchase.id))
        .join(Purchase, Purchase.product_id == Product.id)
        .group_by(Product.name)
        .order_by(func.count(Purchase.id).desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_top_request_types(session: AsyncSession, limit: int = 5) -> list[tuple[str, int]]:
    """Возвращает наиболее частые типы запросов."""
    result = await session.execute(
        select(ChatHistory.request_type, func.count())
        .filter(ChatHistory.request_type != None)
        .group_by(ChatHistory.request_type)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def new_subscriptions_count(session: AsyncSession, days: int = 1) -> int:
    """Количество новых подписок за период."""
    cutoff = datetime.now(datetime.UTC) - timedelta(days=days)
    result = await session.execute(
        select(func.count()).select_from(Subscription).where(Subscription.created_at >= cutoff)
    )
    return result.scalar_one() or 0


async def inactive_users_count(session: AsyncSession, days: int = 30) -> int:
    """Количество пользователей, не проявлявших активность более ``days`` дней."""
    cutoff = datetime.now(datetime.UTC) - timedelta(days=days)
    result = await session.execute(
        select(func.count()).select_from(User).where(User.last_contact_at < cutoff)
    )
    return result.scalar_one() or 0


# --- Новости ---
async def add_news_articles(session: AsyncSession, symbol: str, articles: List[dict]):
    """Сохраняет новости, избегая дубликатов по URL."""
    for art in articles:
        result = await session.execute(select(NewsArticle).filter(NewsArticle.url == art.get("url")))
        if result.scalar_one_or_none():
            continue
        article = NewsArticle(
            symbol=symbol.upper(),
            title=art.get("title"),
            url=art.get("url"),
            source=art.get("source"),
            published_at=art.get("published_at"),
        )
        session.add(article)
    await safe_commit(session)


async def get_recent_news(session: AsyncSession, symbol: str, limit: int = 5) -> List[NewsArticle]:
    result = await session.execute(
        select(NewsArticle)
        .filter(NewsArticle.symbol == symbol.upper())
        .order_by(desc(NewsArticle.published_at))
        .limit(limit)
    )
    return result.scalars().all()

