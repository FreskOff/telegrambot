# database/models.py
# Определения таблиц базы данных с использованием SQLAlchemy ORM.

import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, BigInteger, DateTime,
    Boolean, Float, Enum as SQLAlchemyEnum, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(BigInteger, primary_key=True, index=True, comment="Telegram User ID")
    username = Column(String, nullable=True, unique=True, comment="Telegram @username")
    first_name = Column(String, nullable=True, comment="Имя пользователя")
    last_name = Column(String, nullable=True, comment="Фамилия пользователя")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), onupdate=func.now())
    language = Column(String, nullable=False, default="ru")
    timezone = Column(String, nullable=False, default="UTC")
    currency = Column(String, nullable=False, default="USD")
    stars_balance = Column(Integer, nullable=False, default=0, comment="Баланс звёзд для платных функций")

    # --- Метрики активности ---
    price_requests = Column(Integer, nullable=False, default=0)
    analysis_requests = Column(Integer, nullable=False, default=0)
    lesson_requests = Column(Integer, nullable=False, default=0)
    stars_spent = Column(Integer, nullable=False, default=0)
    last_contact_at = Column(DateTime(timezone=True), nullable=True)
    
    alerts = relationship("PriceAlert", back_populates="user", cascade="all, delete-orphan")
    tracked_coins = relationship("TrackedCoin", back_populates="user", cascade="all, delete-orphan")
    chat_history = relationship("ChatHistory", back_populates="user", cascade="all, delete-orphan")
    learning_progress = relationship("LearningProgress", back_populates="user", cascade="all, delete-orphan")

class AlertDirection(enum.Enum):
    ABOVE = 'above'
    BELOW = 'below'

class PriceAlert(Base):
    __tablename__ = 'price_alerts'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    coin_symbol = Column(String, nullable=False, index=True)
    target_price = Column(Float, nullable=False)
    direction = Column(SQLAlchemyEnum(AlertDirection), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    user = relationship("User", back_populates="alerts")

class TrackedCoin(Base):
    __tablename__ = 'tracked_coins'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    coin_symbol = Column(String, nullable=False, index=True)
    quantity = Column(Float, nullable=True, default=0.0)
    buy_price = Column(Float, nullable=True, default=0.0, comment="Цена покупки за единицу")
    purchase_date = Column(DateTime(timezone=True), nullable=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="tracked_coins")

class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    role = Column(String, nullable=False)
    message_text = Column(Text, nullable=False)
    username_hash = Column(String, nullable=True)
    first_name_hash = Column(String, nullable=True)
    language = Column(String, nullable=False, default='ru')
    timezone = Column(String, nullable=False, default='UTC')
    currency = Column(String, nullable=False, default='USD')
    request_type = Column(String, nullable=True, index=True)
    entities = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error = Column(Boolean, nullable=False, default=False)
    event = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="chat_history")

# --- Новые таблицы для будущего функционала ---

class PremarketSignal(Base):
    """Хранит информацию о новых токенах и событиях."""
    __tablename__ = 'premarket_signals'
    id = Column(Integer, primary_key=True, index=True)
    token_name = Column(String, nullable=False)
    symbol = Column(String, nullable=True, index=True)
    description = Column(Text, nullable=True)
    event_type = Column(String, nullable=False, comment="Напр. 'ICO', 'Listing', 'Airdrop'")
    event_date = Column(DateTime(timezone=True), nullable=True)
    source_url = Column(String, nullable=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

class Lesson(Base):
    """Хранит обучающие материалы."""
    __tablename__ = 'lessons'
    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String, nullable=False, unique=True, index=True, comment="Тема урока, напр. 'DeFi'")
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    difficulty = Column(String, nullable=True, comment="Напр. 'Beginner', 'Advanced'")

class LearningProgress(Base):
    """Отслеживает прогресс обучения пользователя."""
    __tablename__ = 'learning_progress'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id'), nullable=False)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="learning_progress")
    lesson = relationship("Lesson")

class Product(Base):
    """Описывает цифровой товар, который можно купить."""
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False, default=0, comment="Рейтинг товара в звёздах")
    item_type = Column(String, nullable=False, default='report', comment="Тип товара: отчёт, сигнал, курс")
    stars_price = Column(Integer, nullable=False)
    content_type = Column(String, nullable=False)  # text or file
    content_value = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

class Purchase(Base):
    """Фиксирует покупки пользователей."""
    __tablename__ = 'purchases'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False, index=True)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship('User')
    product = relationship('Product')


class Subscription(Base):
    """Состояние подписки пользователя на приватный канал."""

    __tablename__ = 'subscriptions'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    is_active = Column(Boolean, default=False, nullable=False)
    next_payment = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship('User')


class Course(Base):
    """Учебный курс, доступный для покупки."""

    __tablename__ = 'courses'

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    stars_price = Column(Integer, nullable=False, default=0)
    content_type = Column(String, nullable=False)  # text, video, pdf, file
    file_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class CoursePurchase(Base):
    """Покупка пользователем курса."""

    __tablename__ = 'course_purchases'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey('courses.id'), nullable=False, index=True)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship('User')
    course = relationship('Course')


class UsageStats(Base):
    """Агрегированные статистики активности пользователя."""

    __tablename__ = 'usage_stats'

    user_id = Column(BigInteger, ForeignKey('users.id'), primary_key=True)
    last_activity = Column(DateTime(timezone=True))
    stars_spent = Column(Integer, nullable=False, default=0)
    favorite_function = Column(String, nullable=True)

    user = relationship('User')

