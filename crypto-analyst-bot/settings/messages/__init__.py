import json
import logging
import pathlib

logger = logging.getLogger(__name__)
messages = {}


def _load_messages():
    if messages:
        return messages

    # Load JSON message files stored in the same directory as this module.
    # Using ``Path(__file__).parent`` ensures we correctly reference the
    # directory containing the locale files rather than a non-existent
    # ``__init__`` path without the ``.py`` extension.
    base = pathlib.Path(__file__).resolve().parent
    for fp in base.glob("*.json"):
        try:
            with fp.open(encoding="utf-8") as f:
                lang = fp.stem
                messages[lang] = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("⚠️  %s повреждён (%s). Пропускаю.", fp.name, e)
            messages[fp.stem] = {}

    return messages


def get_text(language: str, key: str, **kwargs) -> str:
    msgs = _load_messages()
    lang = language if language in msgs else "ru"
    text = msgs.get(lang, {}).get(key) or msgs.get("ru", {}).get(key, "")
    return text.format(**kwargs)
