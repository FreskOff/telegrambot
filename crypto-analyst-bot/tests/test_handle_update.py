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
