import types, asyncio, sys

sys.modules.setdefault('telegram', types.ModuleType('telegram'))
sys.modules['telegram'].Update = object
sys.modules['telegram'].constants = types.SimpleNamespace(ParseMode='MARKDOWN')
sys.modules.setdefault('telegram.ext', types.ModuleType('telegram.ext'))
sys.modules['telegram.ext'].CallbackContext = object

sys.modules.setdefault('database', types.ModuleType('database'))
sys.modules.setdefault('database.operations', types.ModuleType('database.operations'))

from settings import user as settings_user


def test_handle_hints_command_toggle(monkeypatch):
    messages = {}

    async def reply(text=None, *a, **k):
        messages['text'] = text

    update = types.SimpleNamespace(
        effective_message=types.SimpleNamespace(reply_text=reply),
        effective_user=types.SimpleNamespace(id=10)
    )
    context = types.SimpleNamespace(user_data={})

    async def update_user_settings(session, user_id, **kwargs):
        assert kwargs.get('show_recommendations') is False

    monkeypatch.setattr(settings_user.db_ops, 'update_user_settings', update_user_settings, raising=False)
    async def add_msg(*a, **k):
        pass
    monkeypatch.setattr(settings_user.db_ops, 'add_chat_message', add_msg, raising=False)
    monkeypatch.setattr(settings_user.db_ops, 'get_user', lambda *a, **k: types.SimpleNamespace(show_recommendations=True), raising=False)
    monkeypatch.setattr(settings_user, 'get_text', lambda lang, key, **kw: key)

    asyncio.run(settings_user.handle_hints_command(update, context, 'off', db_session=None))
    assert messages['text'] == 'recommendations_off'

