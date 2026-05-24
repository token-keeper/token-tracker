from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_I18N_DIR = Path(__file__).resolve().parent / "i18n"
_SUPPORTED = {"ko", "en"}


@lru_cache(maxsize=8)
def load_strings(lang: str) -> dict[str, str]:
    """Load translated strings for the given language.

    Falls back to 'en' when the language is unknown or the file is missing.
    Cached per language — loaded only once per process.
    """
    chosen = lang if lang in _SUPPORTED else "en"
    path = _I18N_DIR / f"{chosen}.json"
    return json.loads(path.read_text(encoding="utf-8"))
