"""
i18n — Simple internationalization for Chat Translate & Sum for Telegram.

Usage:
  from .i18n import _

  label = _("app.title")                    # simple key
  text = _("app.status_chats", count=3)     # with format vars
  lang = get_language()                      # current language code

Translations are stored as JSON files in the locales/ directory.
Defaults to system language
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path
from typing import Any

_LOCALES_DIR = Path(__file__).parent / "locales"

# ── Load translations ──────────────────────────────────────────────────

_translations: dict[str, str] = {}
_current_lang: str = "en"


def _detect_language() -> str:
    """Detect user's preferred language from the system."""
    candidates = []
    try:
        sys_lang, _ = locale.getlocale(locale.LC_MESSAGES)
        if sys_lang:
            candidates.append(sys_lang)
    except (locale.Error, ValueError):
        pass
    candidates += [c for c in os.environ.get("LANGUAGE", "").split(":") if c]
    if os.environ.get("LANG"):
        candidates.append(os.environ["LANG"])
    for cand in candidates:
        base = cand.split(".")[0].replace("_", "-")
        for code in (base.lower(), base.split("-")[0].lower()):
            if code and (_LOCALES_DIR / f"{code}.json").exists():
                return code
    return "en"


def _load_translations(lang: str) -> dict[str, str]:
    """Load translations for a language, falling back to English."""
    # Try requested language
    path = _LOCALES_DIR / f"{lang}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback to English
    en_path = _LOCALES_DIR / "en.json"
    if en_path.exists():
        with open(en_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return {}


def set_language(lang: str) -> None:
    """Switch to a different language at runtime."""
    global _translations, _current_lang
    _translations = _load_translations(lang)
    _current_lang = lang


def get_language() -> str:
    """Get the current language code."""
    return _current_lang


def _(key: str, **kwargs: Any) -> str:
    """
    Translate a key to the current language.

    Supports {variable} placeholders:
      _("app.status_chats", count=3, unread=5) -> "3 συνομιλίες · 5 αδιάβαστα"
    """
    text = _translations.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def available_languages() -> list[tuple[str, str]]:
    """Return list of (code, name) for available translations."""
    result = []
    for f in sorted(_LOCALES_DIR.glob("*.json")):
        code = f.stem
        name = language_name(code)
        result.append((code, name))
    return result


def language_name(code: str) -> str:
    """
    Return the native name of a language code, read from its own locale
    file (key ``lang.<code>``). Falls back to the code itself when the
    locale file or key does not exist.
    """
    data = _load_translations(code)
    return data.get(f"lang.{code}", code)


# ── Initialize ─────────────────────────────────────────────────────────

set_language(_detect_language())
