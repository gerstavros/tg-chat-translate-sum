"""tg-translate — Telegram full-translation & summary companion."""

# κράτα το ίδιο με το version στο package/pyproject.toml
APP_VERSION = "0.2.5"

from .backend import (
    ChatInfo,
    MAX_PER_CHAT,
    MessageInfo,
    MODEL,
    check_env,
    list_chats_sync,
    mark_read_sync,
    summarize_chat_sync,
    translate_chat_sync,
)
