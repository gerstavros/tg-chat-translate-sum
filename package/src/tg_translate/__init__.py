"""tg-translate — Telegram full-translation & summary companion."""

from .backend import (
    ChatInfo,
    MAX_PER_CHAT,
    MessageInfo,
    MODEL,
    check_env,
    list_chats_sync,
    mark_read_sync,
    run_unread_summary,
    translate_chat_sync,
)
