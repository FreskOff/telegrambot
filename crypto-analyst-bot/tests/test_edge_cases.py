import types, sys

# Setup fake modules similar to other tests
sys.modules.setdefault('telegram', types.ModuleType('telegram'))
sys.modules['telegram'].Update = object
sys.modules['telegram'].constants = types.SimpleNamespace(
    ParseMode=types.SimpleNamespace(MARKDOWN='MARKDOWN')
)
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
    def __init__(self, *a, **k):
        pass
    def add_job(self, *a, **k):
        pass
sys.modules['apscheduler.schedulers.asyncio'].AsyncIOScheduler = DummyScheduler
dotenv_mod = types.ModuleType('dotenv')
dotenv_mod.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault('dotenv', dotenv_mod)
sys.modules.setdefault('sqlalchemy.future', types.ModuleType('sqlalchemy.future'))
sys.modules['sqlalchemy.future'].select = lambda *args, **kwargs: None
sqlalchemy_mod = sys.modules['sqlalchemy']
sqlalchemy_mod.update = lambda *a, **k: None
sqlalchemy_mod.desc = lambda *a, **k: None
sqlalchemy_mod.delete = lambda *a, **k: None
sqlalchemy_mod.func = types.SimpleNamespace()
sqlalchemy_mod.select = lambda *a, **k: None
sqlalchemy_mod.distinct = lambda *a, **k: None
sys.modules.setdefault('sqlalchemy.orm', types.ModuleType('sqlalchemy.orm'))
sys.modules['sqlalchemy.orm'].selectinload = lambda *a, **k: None
sys.modules.setdefault('sqlalchemy.sql', types.ModuleType('sqlalchemy.sql'))
sys.modules['sqlalchemy.sql'].func = types.SimpleNamespace()
for mod in ['database', 'database.operations', 'database.models']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
sys.modules['database.models'].User = object
sys.modules['database.models'].Purchase = object
sys.modules['database.models'].Subscription = object
sys.modules['database.operations'].get_or_create_user = lambda *a, **k: None
sys.modules['database.operations'].get_subscription = lambda *a, **k: None
sys.modules['database.operations'].count_user_messages_today = lambda *a, **k: 0
def _noop_sync(*a, **k):
    pass
async def _noop(*a, **k):
    return None
sys.modules['database.operations'].start_dialog = _noop
sys.modules['database.operations'].add_chat_message = lambda *a, **k: None
async def _return_none(*a, **k):
    return None
async def _return_false(*a, **k):
    return False
sys.modules['database.operations'].get_product = _return_none
sys.modules['database.operations'].has_purchased = _return_false
sys.modules['database.operations'].get_course = _return_none
sys.modules['database.operations'].has_purchased_course = _return_false
sys.modules['database.operations'].add_course_purchase = _noop
sys.modules['database.operations'].add_purchase = _noop
sys.modules.setdefault('database.engine', types.ModuleType('database.engine'))
sys.modules['database.engine'].AsyncSessionFactory = object

import asyncio
import pytest
from bot import core


def test_handle_update_ignores_callback(monkeypatch):
    answered = {}
    async def ans(*a, **k):
        answered['ok'] = True
    update = types.SimpleNamespace(
        callback_query=types.SimpleNamespace(data='blah', answer=ans),
        pre_checkout_query=None,
        effective_message=None,
        effective_user=None,
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})
    async def fail(*a, **k):
        raise AssertionError('db should not be accessed')
    monkeypatch.setattr(core.db_ops, 'get_or_create_user', fail)
    asyncio.run(core.handle_update(update, context, db_session=None))
    assert answered.get('ok')


def test_daily_limit_exceeded(monkeypatch):
    messages = {}
    async def reply(text=None, *a, **k):
        messages['text'] = text
    update = types.SimpleNamespace(
        callback_query=None,
        pre_checkout_query=None,
        effective_message=types.SimpleNamespace(text='hi', reply_text=reply),
        effective_user=types.SimpleNamespace(is_bot=False, id=9),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})
    async def user_func(*a, **k):
        return types.SimpleNamespace(id=9, language='ru', show_recommendations=True)
    monkeypatch.setattr(core.db_ops, 'get_or_create_user', user_func)
    monkeypatch.setattr(core.db_ops, 'get_subscription', _noop)
    async def count_msgs(*a, **k):
        return core.DAILY_FREE_MESSAGES + 1
    monkeypatch.setattr(core.db_ops, 'count_user_messages_today', count_msgs)
    monkeypatch.setattr(core.db_ops, 'start_dialog', _noop)
    monkeypatch.setattr(core.db_ops, 'add_chat_message', _noop)
    monkeypatch.setattr(core, 'classify_intent', _noop)
    monkeypatch.setattr(core, 'get_text', lambda lang, key, **kw: 'LIMIT' if key == 'free_daily_limit' else key)
    asyncio.run(core.handle_update(update, context, db_session=None))
    assert messages.get('text') == 'LIMIT'


def test_buy_product_invoice(monkeypatch):
    calls = {}
    async def fake_invoice(update, context, typ, amount, desc):
        calls['payload'] = typ
        calls['amount'] = amount
        calls['desc'] = desc
    monkeypatch.setattr(core, 'send_payment_invoice', fake_invoice)
    product = types.SimpleNamespace(id=1, stars_price=10, name='Prod', content_type='text', content_value='val')
    async def get_product(*a, **k):
        return product
    async def has_purchased(*a, **k):
        return False
    monkeypatch.setattr(core.db_ops, 'get_product', get_product)
    monkeypatch.setattr(core.db_ops, 'has_purchased', has_purchased)
    messages = []
    async def reply(text=None, *a, **k):
        messages.append(text)
    update = types.SimpleNamespace(
        effective_message=types.SimpleNamespace(chat_id=5, reply_text=reply),
        effective_user=types.SimpleNamespace(id=5),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})
    monkeypatch.setattr(core, 'get_text', lambda *a, **k: 'purchase_open_form')
    asyncio.run(core.handle_buy_product(update, context, '1', db_session=None))
    assert calls['payload'] == 'product-1'
    assert messages[-1] == 'purchase_open_form'


def test_buy_course_invoice(monkeypatch):
    calls = {}
    async def fake_invoice(update, context, typ, amount, desc):
        calls['payload'] = typ
    monkeypatch.setattr(core, 'send_payment_invoice', fake_invoice)
    course = types.SimpleNamespace(
        id=2,
        title='Course',
        stars_price=20,
        content_type='text',
        content_value='c',
        description='d',
        file_id=None,
    )
    async def get_course(*a, **k):
        return course
    async def has_purchased_course(*a, **k):
        return False
    monkeypatch.setattr(core.db_ops, 'get_course', get_course)
    monkeypatch.setattr(core.db_ops, 'has_purchased_course', has_purchased_course)
    monkeypatch.setattr(core.db_ops, 'add_course_purchase', _noop)
    monkeypatch.setattr(core.db_ops, 'add_chat_message', _noop)
    messages = []
    async def reply(text=None, *a, **k):
        messages.append(text)
    update = types.SimpleNamespace(
        effective_message=types.SimpleNamespace(reply_text=reply),
        effective_user=types.SimpleNamespace(id=7),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})
    monkeypatch.setattr(core, 'get_text', lambda *a, **k: 'course_purchased')
    asyncio.run(core.handle_course_command(update, context, 'buy 2', db_session=None))
    assert calls['payload'] == 'course-2'
    assert 'course_purchased' in messages[0]


def test_buy_report_invoice(monkeypatch):
    calls = {}
    async def fake_invoice(update, context, typ, amount, desc):
        calls['payload'] = typ
    monkeypatch.setattr(core, 'send_payment_invoice', fake_invoice)
    messages = []
    async def reply(text=None, *a, **k):
        messages.append(text)
    update = types.SimpleNamespace(
        effective_message=types.SimpleNamespace(reply_text=reply),
        callback_query=None,
        effective_user=types.SimpleNamespace(id=11),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})
    monkeypatch.setattr(core, 'get_text', lambda *a, **k: 'purchase_open_form')
    asyncio.run(core.handle_buy_report(update, context, db_session=None))
    assert calls['payload'] == 'report'
    assert messages[-1] == 'purchase_open_form'


def test_buy_report_answers_callback(monkeypatch):
    answered = {}
    async def ans(*a, **k):
        answered['ok'] = True

    async def fake_invoice(*a, **k):
        pass
    monkeypatch.setattr(core, 'send_payment_invoice', fake_invoice)
    async def reply(*a, **k):
        pass
    update = types.SimpleNamespace(
        callback_query=types.SimpleNamespace(answer=ans),
        effective_message=types.SimpleNamespace(reply_text=reply),
        effective_user=types.SimpleNamespace(id=12),
    )
    context = types.SimpleNamespace(bot=types.SimpleNamespace(id=1), user_data={})
    monkeypatch.setattr(core, 'get_text', lambda *a, **k: 'purchase_open_form')
    asyncio.run(core.handle_buy_report(update, context, db_session=None))
    assert answered.get('ok')
