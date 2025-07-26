import types, sys
sys.modules.setdefault('telegram', types.ModuleType('telegram'))
sys.modules['telegram'].Update = object
sys.modules['telegram'].constants = types.SimpleNamespace(ParseMode='MARKDOWN')
sys.modules['telegram'].User = object
sys.modules['telegram'].InlineKeyboardButton = object
sys.modules['telegram'].InlineKeyboardMarkup = object
sys.modules['telegram'].ReplyKeyboardMarkup = object
sys.modules['telegram'].LabeledPrice = object
sys.modules['telegram'].Bot = type('Bot', (), {'id': 1})
sys.modules.setdefault('telegram.ext', types.ModuleType('telegram.ext'))
sys.modules['telegram.ext'].CallbackContext = object
sys.modules.setdefault('sqlalchemy', types.ModuleType('sqlalchemy'))
sys.modules.setdefault('sqlalchemy.ext', types.ModuleType('sqlalchemy.ext'))
sys.modules.setdefault('sqlalchemy.ext.asyncio', types.ModuleType('sqlalchemy.ext.asyncio'))
sys.modules['sqlalchemy.ext.asyncio'].AsyncSession = object
sys.modules.setdefault('httpx', types.ModuleType('httpx'))
sys.modules.setdefault('matplotlib', types.ModuleType('matplotlib'))
sys.modules.setdefault('matplotlib.pyplot', types.ModuleType('matplotlib.pyplot'))
sys.modules.setdefault('matplotlib.backends', types.ModuleType('matplotlib.backends'))
sys.modules.setdefault('matplotlib.backends.backend_pdf', types.ModuleType('matplotlib.backends.backend_pdf'))
sys.modules['matplotlib.backends.backend_pdf'].PdfPages = object
sys.modules.setdefault('bs4', types.ModuleType('bs4'))
sys.modules['bs4'].BeautifulSoup = object
sys.modules.setdefault('ddgs', types.ModuleType('ddgs'))
sys.modules['ddgs'].DDGS = object
sys.modules.setdefault('apscheduler', types.ModuleType('apscheduler'))
sys.modules.setdefault('apscheduler.schedulers', types.ModuleType('apscheduler.schedulers'))
sys.modules.setdefault('apscheduler.schedulers.asyncio', types.ModuleType('apscheduler.schedulers.asyncio'))
class DummyScheduler:
    def __init__(self, *args, **kwargs):
        pass
    def add_job(self, *args, **kwargs):
        pass
sys.modules['apscheduler.schedulers.asyncio'].AsyncIOScheduler = DummyScheduler
dotenv_mod = types.ModuleType('dotenv')
dotenv_mod.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault('dotenv', dotenv_mod)
sys.modules.setdefault('sqlalchemy.future', types.ModuleType('sqlalchemy.future'))
sys.modules['sqlalchemy.future'].select = lambda *args, **kwargs: None
sqlalchemy_mod = sys.modules['sqlalchemy']
sqlalchemy_mod.update = lambda *args, **kwargs: None
sqlalchemy_mod.desc = lambda *args, **kwargs: None
sqlalchemy_mod.delete = lambda *args, **kwargs: None
sqlalchemy_mod.func = types.SimpleNamespace()
sqlalchemy_mod.select = lambda *args, **kwargs: None
sqlalchemy_mod.distinct = lambda *args, **kwargs: None
sys.modules.setdefault('sqlalchemy.orm', types.ModuleType('sqlalchemy.orm'))
sys.modules['sqlalchemy.orm'].selectinload = lambda *args, **kwargs: None
sys.modules.setdefault('sqlalchemy.sql', types.ModuleType('sqlalchemy.sql'))
sys.modules['sqlalchemy.sql'].func = types.SimpleNamespace()
for mod in ['database', 'database.operations', 'database.models']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
sys.modules['database.models'].User = object
sys.modules['database.models'].Purchase = object
sys.modules['database.models'].Subscription = object
sys.modules['database.operations'].get_or_create_user = lambda *args, **kwargs: None
sys.modules['database.operations'].get_subscription = lambda *args, **kwargs: None
sys.modules['database.operations'].count_user_messages_today = lambda *args, **kwargs: 0
async def _noop(*a, **k):
    return None
sys.modules['database.operations'].start_dialog = _noop
sys.modules['database.operations'].add_chat_message = lambda *a, **k: None
sys.modules.setdefault('database.engine', types.ModuleType('database.engine'))
sys.modules['database.engine'].AsyncSessionFactory = object

import asyncio
import pytest
from bot import core

def test_handle_update_ignores_bot(monkeypatch):
    update = types.SimpleNamespace(
        callback_query=None,
        pre_checkout_query=None,
        effective_message=types.SimpleNamespace(text="hi"),
        effective_user=types.SimpleNamespace(is_bot=True, id=1),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})

    async def fail(*args, **kwargs):
        raise AssertionError("db should not be accessed")

    monkeypatch.setattr(core.db_ops, "get_or_create_user", fail)

    asyncio.run(core.handle_update(update, context, db_session=None))


def test_handle_update_ignores_empty(monkeypatch):
    update = types.SimpleNamespace(
        callback_query=None,
        pre_checkout_query=None,
        effective_message=types.SimpleNamespace(text="  "),
        effective_user=types.SimpleNamespace(is_bot=False, id=2),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})

    async def fail(*args, **kwargs):
        raise AssertionError("db should not be accessed")

    monkeypatch.setattr(core.db_ops, "get_or_create_user", fail)

    asyncio.run(core.handle_update(update, context, db_session=None))


def test_handle_update_daily_limit(monkeypatch):
    messages = {}

    async def reply(text=None, *a, **k):
        messages["text"] = text

    update = types.SimpleNamespace(
        callback_query=None,
        pre_checkout_query=None,
        effective_message=types.SimpleNamespace(text="hi", reply_text=reply),
        effective_user=types.SimpleNamespace(is_bot=False, id=3),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})

    async def user_func(*args, **kwargs):
        return types.SimpleNamespace(id=3, language="ru", show_recommendations=True)

    monkeypatch.setattr(core.db_ops, "get_or_create_user", user_func)
    async def no_sub(*a, **k):
        return None
    async def count_msgs(*a, **k):
        return core.DAILY_FREE_MESSAGES
    monkeypatch.setattr(core.db_ops, "get_subscription", no_sub)
    monkeypatch.setattr(core.db_ops, "count_user_messages_today", count_msgs)

    async def fail(*a, **k):
        raise AssertionError("should not be called")

    monkeypatch.setattr(core.db_ops, "start_dialog", fail)
    async def add_msg(*a, **k):
        pass
    monkeypatch.setattr(core.db_ops, "add_chat_message", add_msg)
    monkeypatch.setattr(core, "classify_intent", fail)
    monkeypatch.setattr(core, "get_text", lambda lang, key, **kw: "LIMIT" if key == "free_daily_limit" else key)

    asyncio.run(core.handle_update(update, context, db_session=None))
    assert messages.get("text") == "LIMIT"
