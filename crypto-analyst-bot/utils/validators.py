import re

SYMBOL_RE = re.compile(r'^[A-Za-z0-9]{2,10}$')
ID_RE = re.compile(r'^\d+$')

def is_valid_symbol(value: str) -> bool:
    return bool(SYMBOL_RE.fullmatch(value.strip()))

def is_valid_id(value: str) -> bool:
    return bool(ID_RE.fullmatch(value.strip()))

