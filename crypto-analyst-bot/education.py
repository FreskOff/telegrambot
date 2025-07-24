"""education.py
Модуль с краткими пояснениями терминов и набросками для будущих обучающих курсов.
"""

from typing import Dict, Optional

# Небольшой словарь терминов. В дальнейшем данные будут загружаться администратором
# через бота или из базы данных.
TERMS: Dict[str, str] = {
    "DEFI": "DeFi (Decentralized Finance) — экосистема финансовых сервисов на базе блокчейна без посредников.",
    "DAO": "DAO (Decentralized Autonomous Organization) — децентрализованная автономная организация, управляемая участниками через смарт‑контракты.",
    "NFT": "NFT (Non‑Fungible Token) — уникальный токен, подтверждающий право собственности на цифровой объект.",
    "DEX": "DEX (Decentralized Exchange) — децентрализованная биржа для обмена криптоактивов напрямую между пользователями.",
}


def get_definition(term: str) -> Optional[str]:
    """Возвращает краткое объяснение термина."""
    return TERMS.get(term.upper())


# ---- Заготовки для расширенного обучения ----
class CourseInfo:
    """Модель данных для будущих мини‑курсов."""

    def __init__(self, course_id: str, title: str, stars_price: int):
        self.course_id = course_id
        self.title = title
        self.stars_price = stars_price
        # В дальнейшем здесь будут поля с описанием и ссылкой на файл или видео


# Демонстрационный список курсов. В будущем данные будут браться из БД
# или загружаться администратором через панель бота.
DEMO_COURSES = [
    CourseInfo(course_id="defi101", title="DeFi за 30 минут", stars_price=50),
    CourseInfo(course_id="dao-guide", title="Как устроены DAO", stars_price=40),
]


def list_courses() -> list[CourseInfo]:
    """Возвращает список доступных мини‑курсов."""
    return DEMO_COURSES


def get_course(course_id: str) -> Optional[CourseInfo]:
    """Возвращает информацию о курсе по идентификатору."""
    for course in DEMO_COURSES:
        if course.course_id == course_id:
            return course
    return None
