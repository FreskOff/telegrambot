import types, sys
sys.modules.setdefault('telegram', types.ModuleType('telegram'))
sys.modules['telegram'].Update = object
sys.modules['telegram'].constants = types.SimpleNamespace(ParseMode='MARKDOWN')
sys.modules['telegram'].User = object
sys.modules.setdefault('telegram.ext', types.ModuleType('telegram.ext'))
sys.modules['telegram.ext'].CallbackContext = object
sys.modules.setdefault('sqlalchemy', types.ModuleType('sqlalchemy'))
sys.modules.setdefault('sqlalchemy.ext', types.ModuleType('sqlalchemy.ext'))
sys.modules.setdefault('sqlalchemy.ext.asyncio', types.ModuleType('sqlalchemy.ext.asyncio'))
sys.modules['sqlalchemy.ext.asyncio'].AsyncSession = object
sys.modules.setdefault('httpx', types.ModuleType('httpx'))
dotenv_mod = types.ModuleType('dotenv')
dotenv_mod.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault('dotenv', dotenv_mod)
sys.modules.setdefault('sqlalchemy.future', types.ModuleType('sqlalchemy.future'))
sys.modules['sqlalchemy.future'].select = lambda *args, **kwargs: None
sqlalchemy_mod = sys.modules['sqlalchemy']
sqlalchemy_mod.update = lambda *args, **kwargs: None
sqlalchemy_mod.desc = lambda *args, **kwargs: None
sqlalchemy_mod.delete = lambda *args, **kwargs: None
sys.modules.setdefault('sqlalchemy.orm', types.ModuleType('sqlalchemy.orm'))
sys.modules['sqlalchemy.orm'].selectinload = lambda *args, **kwargs: None
sys.modules.setdefault('sqlalchemy.sql', types.ModuleType('sqlalchemy.sql'))
sys.modules['sqlalchemy.sql'].func = types.SimpleNamespace()
for mod in ['database', 'database.operations', 'database.models']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

import pytest
from ai import prediction

def test_linear_regression():
    slope, intercept = prediction._linear_regression([(0, 1), (1, 3)])
    assert round(slope, 2) == 2.0
    assert round(intercept, 2) == 1.0
