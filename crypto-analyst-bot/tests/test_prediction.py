import types, sys
sys.modules.setdefault('telegram', types.ModuleType('telegram'))
sys.modules['telegram'].Update = object
sys.modules['telegram'].constants = types.SimpleNamespace(ParseMode='MARKDOWN')
sys.modules.setdefault('telegram.ext', types.ModuleType('telegram.ext'))
sys.modules['telegram.ext'].CallbackContext = object

import pytest
from ai import prediction

@pytest.mark.asyncio
async def test_linear_regression():
    slope, intercept = prediction._linear_regression([(0, 1), (1, 3)])
    assert round(slope, 2) == 2.0
    assert round(intercept, 2) == 1.0
