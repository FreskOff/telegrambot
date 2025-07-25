# database/engine.py
# Настройка подключения к базе данных PostgreSQL с использованием SQLAlchemy.

import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from .models import Base # Импортируем базовый класс моделей

logger = logging.getLogger(__name__)
load_dotenv()

# --- Конфигурация ---
# Получаем строку подключения из переменных окружения.
# Пример для Railway: postgresql://user:password@host:port/database
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL не найден в переменных окружения!")
    raise ValueError("Необходимо указать DATABASE_URL для подключения к БД.")

# --- Создание асинхронного движка ---
# `create_async_engine` создает пул соединений для асинхронной работы.
# `echo=False` в продакшене, можно поставить `True` для отладки SQL-запросов.
try:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True  # ОБЯЗАТЕЛЬНО для Railway и других облаков
    )
except Exception as e:
    logger.error(f"Не удалось создать движок SQLAlchemy: {e}")
    raise

# --- Создание фабрики сессий ---
# `AsyncSession` - это основной интерфейс для взаимодействия с БД.
# `expire_on_commit=False` важно для асинхронных приложений, чтобы
# объекты оставались доступными после коммита транзакции.
AsyncSessionFactory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

async def get_db_session() -> AsyncSession:
    """
    Зависимость (Dependency) для FastAPI для получения сессии базы данных.
    Обеспечивает, что сессия будет корректно создана для каждого запроса
    и закрыта после его выполнения.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Инициализирует базу данных, создавая все таблицы на основе моделей.
    Вызывается один раз при старте приложения в main.py.
    """
    async with engine.begin() as conn:
        # `conn.run_sync(Base.metadata.create_all)` создает таблицы,
        # если они еще не существуют.
        logger.info("Проверка и создание таблиц в базе данных...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Таблицы успешно проверены/созданы.")