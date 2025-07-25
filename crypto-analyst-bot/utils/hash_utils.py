import hashlib
from typing import Optional


def hash_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()
