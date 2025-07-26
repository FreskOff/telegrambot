import os
import types
import sys
import json
import asyncio

# --- Stub external dependencies for main module import ---

sys.modules.setdefault("uvicorn", types.ModuleType("uvicorn"))
sys.modules["uvicorn"].run = lambda *a, **k: None

sys.modules.setdefault("telegram", types.ModuleType("telegram"))


def _conv(obj):
    if isinstance(obj, dict):
        return types.SimpleNamespace(**{k: _conv(v) for k, v in obj.items()})
    return obj


class DummyUpdate:
    @staticmethod
    def de_json(data, bot):
        return _conv(data)


sys.modules["telegram"].Update = DummyUpdate
sys.modules["telegram"].constants = types.SimpleNamespace(ParseMode="MARKDOWN")
sys.modules["telegram"].Bot = type("Bot", (), {"id": 1})

sys.modules.setdefault("telegram.ext", types.ModuleType("telegram.ext"))


class DummyApp:
    def __init__(self):
        async def send_message(*a, **k):
            pass

        self.bot = types.SimpleNamespace(send_message=send_message)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


class DummyBuilder:
    def token(self, token):
        return self

    def build(self):
        return DummyApp()


class Application:
    @staticmethod
    def builder():
        return DummyBuilder()


sys.modules["telegram.ext"].Application = Application
sys.modules["telegram.ext"].CallbackContext = type(
    "CallbackContext",
    (),
    {"from_update": staticmethod(lambda u, a: types.SimpleNamespace())},
)

sys.modules.setdefault("sqlalchemy", types.ModuleType("sqlalchemy"))
sys.modules.setdefault("sqlalchemy.ext", types.ModuleType("sqlalchemy.ext"))
sys.modules.setdefault(
    "sqlalchemy.ext.asyncio", types.ModuleType("sqlalchemy.ext.asyncio")
)
sys.modules["sqlalchemy.ext.asyncio"].AsyncSession = object

bot_pkg = types.ModuleType("bot")
core_mod = types.ModuleType("bot.core")
core_mod.handle_update = lambda *a, **k: None
bot_pkg.core = core_mod
sys.modules["bot"] = bot_pkg
sys.modules["bot.core"] = core_mod

import fastapi

admin_routes = types.ModuleType("admin.routes")
admin_routes.router = fastapi.APIRouter()
sys.modules["admin.routes"] = admin_routes

db_engine = types.ModuleType("database.engine")
db_engine.init_db = lambda: None
db_engine.get_db_session = lambda: None
db_engine.AsyncSessionFactory = type("Factory", (), {})
sys.modules["database.engine"] = db_engine

bg_sched = types.ModuleType("background.scheduler")
bg_sched.start_scheduler = lambda *a, **k: None
sys.modules["background.scheduler"] = bg_sched

analysis_mod = types.ModuleType("analysis.metrics")
analysis_mod.gather_metrics = lambda *a, **k: {}
sys.modules["analysis.metrics"] = analysis_mod

db_ops_mod = types.ModuleType("database.operations")


async def _get_user(*a, **k):
    return None


db_ops_mod.get_user = _get_user
sys.modules["database.operations"] = db_ops_mod

settings_mod = types.ModuleType("settings.messages")
settings_mod.get_text = lambda *a, **k: "text"
sys.modules["settings.messages"] = settings_mod

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "token")
os.environ.setdefault("WEBHOOK_URL", "http://example.com")

import main


def _make_request(data: bytes):
    async def body():
        return data

    return types.SimpleNamespace(body=body)


def test_telegram_webhook_valid_body(monkeypatch):
    update = {
        "callback_query": None,
        "pre_checkout_query": None,
        "effective_message": {"text": "hi"},
        "effective_chat": {"id": 1},
        "effective_user": {"id": 2},
    }
    req = _make_request(json.dumps(update).encode("utf-8"))

    called = {}

    async def fake_process(data):
        called["data"] = data

    monkeypatch.setattr(main, "process_update", fake_process)
    scheduled = {}
    monkeypatch.setattr(
        asyncio, "create_task", lambda coro: scheduled.setdefault("coro", coro)
    )

    res = asyncio.run(
        main.telegram_webhook(req, os.environ["TELEGRAM_BOT_TOKEN"], db_session=None)
    )
    assert res.status_code == 200

    asyncio.run(scheduled["coro"])
    assert called["data"] == update


def test_telegram_webhook_invalid_json(monkeypatch):
    req = _make_request(b"{")
    warnings = []
    monkeypatch.setattr(main.logger, "warning", lambda *a, **k: warnings.append(a))
    monkeypatch.setattr(main, "process_update", lambda *a, **k: None)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: warnings.append("task"))

    res = asyncio.run(
        main.telegram_webhook(req, os.environ["TELEGRAM_BOT_TOKEN"], db_session=None)
    )
    assert res.status_code == 200
    assert warnings and warnings[0]
    assert "task" not in warnings


def test_telegram_webhook_trailing_comma(monkeypatch):
    update = {
        "callback_query": None,
        "pre_checkout_query": None,
        "effective_message": {"text": "hi"},
        "effective_chat": {"id": 1},
        "effective_user": {"id": 2},
    }
    body = json.dumps(update).encode("utf-8") + b","
    req = _make_request(body)

    called = {}

    async def fake_process(data):
        called["data"] = data

    monkeypatch.setattr(main, "process_update", fake_process)
    scheduled = {}
    monkeypatch.setattr(
        asyncio, "create_task", lambda coro: scheduled.setdefault("coro", coro)
    )

    res = asyncio.run(
        main.telegram_webhook(req, os.environ["TELEGRAM_BOT_TOKEN"], db_session=None)
    )
    assert res.status_code == 200

    asyncio.run(scheduled["coro"])
    assert called["data"] == update


def test_telegram_webhook_trailing_comma_inside(monkeypatch):
    update = {
        "callback_query": None,
        "pre_checkout_query": None,
        "effective_message": {"text": "hi"},
        "effective_chat": {"id": 1},
        "effective_user": {"id": 2},
    }
    # insert a trailing comma before closing object
    text = json.dumps(update)
    body = text[:-1] + ",}"
    req = _make_request(body.encode("utf-8"))

    called = {}

    async def fake_process(data):
        called["data"] = data

    monkeypatch.setattr(main, "process_update", fake_process)
    scheduled = {}
    monkeypatch.setattr(
        asyncio, "create_task", lambda coro: scheduled.setdefault("coro", coro)
    )

    res = asyncio.run(
        main.telegram_webhook(req, os.environ["TELEGRAM_BOT_TOKEN"], db_session=None)
    )
    assert res.status_code == 200

    asyncio.run(scheduled["coro"])
    assert called["data"] == update


def test_telegram_webhook_double_comma(monkeypatch):
    update = {
        "callback_query": None,
        "pre_checkout_query": None,
        "effective_message": {"text": "hi"},
        "effective_chat": {"id": 1},
        "effective_user": {"id": 2},
    }
    # introduce a double comma inside JSON
    text = json.dumps(update)
    broken = text.replace('"hi"', '"hi",')
    req = _make_request(broken.encode("utf-8"))

    called = {}

    async def fake_process(data):
        called["data"] = data

    monkeypatch.setattr(main, "process_update", fake_process)
    scheduled = {}
    monkeypatch.setattr(
        asyncio, "create_task", lambda coro: scheduled.setdefault("coro", coro)
    )

    res = asyncio.run(
        main.telegram_webhook(req, os.environ["TELEGRAM_BOT_TOKEN"], db_session=None)
    )
    assert res.status_code == 200

    asyncio.run(scheduled["coro"])
    assert called["data"] == update
