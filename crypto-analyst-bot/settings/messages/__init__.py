import json
import os
from functools import lru_cache

BASE_DIR = os.path.dirname(__file__)

@lru_cache()
def _load_messages():
    messages = {}
    for lang_file in ("ru.json", "en.json"):
        path = os.path.join(BASE_DIR, lang_file)
        lang = os.path.splitext(lang_file)[0]
        with open(path, "r", encoding="utf-8") as f:
            messages[lang] = json.load(f)
    return messages


def get_text(language: str, key: str, **kwargs) -> str:
    msgs = _load_messages()
    lang = language if language in msgs else "ru"
    text = msgs.get(lang, {}).get(key) or msgs.get("ru", {}).get(key, "")
    return text.format(**kwargs)
