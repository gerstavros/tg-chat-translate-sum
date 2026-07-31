"""
tg-translate — Telegram full-translation & summary companion.

Backend module: Telegram client, translation, config loading.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

# --- Load .env ---
load_dotenv()
env_path = Path.home() / ".unread" / ".env"
if env_path.exists():
    load_dotenv(env_path)

UNREAD_SESSION = Path.home() / ".unread" / "storage" / "session.sqlite.session"
WINDOW_STATE_PATH = Path.home() / ".chat-translate-sum" / "window_state.json"
_GEOMETRY_RE = re.compile(r"^\d+x\d+(\+-?\d+\+-?\d+)?$")


def load_window_geometry() -> str | None:
    """Return the main window's last-saved geometry or none."""
    try:
        geometry = json.loads(WINDOW_STATE_PATH.read_text()).get("geometry")
        if isinstance(geometry, str) and _GEOMETRY_RE.match(geometry):
            return geometry
    except Exception:
        pass
    return None


def save_window_geometry(geometry: str) -> None:
    """Persist the main window's geometry so it can be restored on next launch."""
    try:
        WINDOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        WINDOW_STATE_PATH.write_text(json.dumps({"geometry": geometry}))
    except Exception:
        pass

# --- Config ---
MODEL = os.environ.get("TRANSLATE_MODEL", "gpt-4.1-mini")
MAX_PER_CHAT = int(os.environ.get("MAX_PER_CHAT", "10000"))


# --- Types ---


class ChatInfo:
    """Serialisable chat summary for the GUI/CLI."""

    def __init__(self, dialog) -> None:
        self.id: int = dialog.entity.id
        self.name: str = dialog.name or "(no name)"
        self.username: str = (
            dialog.entity.username
            if hasattr(dialog.entity, "username") and dialog.entity.username
            else ""
        )
        self.unread_count: int = dialog.unread_count
        self.has_unread: bool = dialog.unread_count > 0
        self.is_user: bool = dialog.is_user
        self.is_group: bool = dialog.is_group

    @property
    def kind_icon(self) -> str:
        return "chat" if self.is_user else "group" if self.is_group else "channel"


class MessageInfo:
    """Serialisable message info for the GUI."""

    def __init__(self, msg, translation: str = "") -> None:
        self.id: int = msg.id
        self.date: str = msg.date.strftime("%Y-%m-%d %H:%M")
        self.sender: str = "?"
        if msg.sender:
            self.sender = (
                getattr(msg.sender, "first_name", None)
                or getattr(msg.sender, "title", None)
                or getattr(msg.sender, "username", None)
                or "?"
            )
        self.text: str = msg.text or ""
        self.translation: str = translation
        self.media_type: str = self._detect_media(msg)

    @staticmethod
    def _detect_media(msg) -> str:
        """Detect media type from a Telethon message. Voice not working yet on front"""
        if msg.text:
            return ""
        if msg.photo:
            return "\U0001f4f7 Photo"
        if msg.video:
            d = msg.video.duration if hasattr(msg.video, "duration") and msg.video.duration else ""
            return f"\U0001f3a5 Video ({d}s)" if d else "\U0001f3a5 Video"
        if msg.voice:
            d = msg.voice.duration if hasattr(msg.voice, "duration") and msg.voice.duration else ""
            return f"\U0001f3a4 Voice ({d}s)" if d else "\U0001f3a4 Voice"
        if msg.video_note:
            d = msg.video_note.duration if hasattr(msg.video_note, "duration") and msg.video_note.duration else ""
            return f"\U0001f300 Video note ({d}s)" if d else "\U0001f300 Video note"
        if msg.document:
            return "\U0001f4c4 Document"
        if msg.sticker:
            return "\U0001f3f7\ufe0f Sticker"
        if msg.poll:
            return "\U0001f4ca Poll"
        if msg.contact:
            return "\U0001f464 Contact"
        return "\U0001f4ce Media"

    @property
    def is_greek(self) -> bool:
        return self.translation.strip() in ("already Greek", "")


# --- Telegram client ---


def _make_client_unconnected():
    """Build (but not connect) a Telethon client, reusing unread's session if available."""
    from telethon import TelegramClient

    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")

    if not api_id or not api_hash:
        raise RuntimeError(
            "Missing TG_API_ID and TG_API_HASH.\n"
            "Create a .env file (see .env.example).\n"
            "Get credentials at https://my.telegram.org -> API Development"
        )

    session_path = str(UNREAD_SESSION)
    if not Path(session_path).exists():
        session_path = "tg-translate-session"

    return TelegramClient(session_path, int(api_id), api_hash)


async def create_telegram_client():
    """Connect an already-authorized Telethon client.

    Login (QR/SMS) must happen separately via LoginSession before this is called;
    this never falls back to an interactive console prompt..
    """
    client = _make_client_unconnected()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Telegram client is not authorized. Run the login flow first.")
    return client


async def is_authorized(client) -> bool:
    return await client.is_user_authorized()


def is_authorized_sync() -> bool:
    """Check (without raising) whether a valid Telegram session already exists."""
    if not os.environ.get("TG_API_ID") or not os.environ.get("TG_API_HASH"):
        return False

    async def _run():
        client = _make_client_unconnected()
        await client.connect()
        try:
            return await client.is_user_authorized()
        finally:
            await client.disconnect()

    try:
        return _run_async(_run)
    except Exception:
        return False


class LoginSession:
    """Owns a persistent asyncio event loop + connected client for interactive login.

    Unlike the one-shot *_sync wrappers above, QR/SMS login needs a single
    connection kept alive across multiple user actions (show QR -> wait for
    scan, or send code -> confirm code -> optional 2FA password). All public
    methods are blocking and thread-safe; call them from a background thread,
    never from the Tk main thread.
    """

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self.client = None
        self._qr = None
        self._phone = None

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def connect(self) -> bool:
        async def _c():
            self.client = _make_client_unconnected()
            await self.client.connect()
            return await self.client.is_user_authorized()

        return self._run(_c())

    def start_qr(self) -> str:
        async def _q():
            self._qr = await self.client.qr_login()
            return self._qr.url

        return self._run(_q())

    def qr_wait(self, timeout: float = 30) -> str:
        from telethon.errors import SessionPasswordNeededError

        async def _w():
            try:
                await self._qr.wait(timeout=timeout)
                return "ok"
            except SessionPasswordNeededError:
                return "need_password"
            except asyncio.TimeoutError:
                return "timeout"

        return self._run(_w())

    def qr_recreate(self) -> str:
        async def _r():
            await self._qr.recreate()
            return self._qr.url

        return self._run(_r())

    def send_code(self, phone: str) -> None:
        async def _s():
            self._phone = phone
            await self.client.send_code_request(phone)

        self._run(_s())

    def sign_in_code(self, code: str) -> str:
        from telethon.errors import SessionPasswordNeededError

        async def _si():
            try:
                await self.client.sign_in(self._phone, code=code)
                return "ok"
            except SessionPasswordNeededError:
                return "need_password"

        return self._run(_si())

    def sign_in_password(self, password: str) -> None:
        async def _sp():
            await self.client.sign_in(password=password)

        self._run(_sp())

    def close(self) -> None:
        async def _cl():
            if self.client:
                await self.client.disconnect()

        try:
            self._run(_cl())
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


# --- Chat listing ---


async def get_unread_chats(client, min_unread=1, only_unread=True) -> list[ChatInfo]:
    """Return serialisable chat list sorted by unread count desc.

    If only_unread=True (default), only chats with >= min_unread are returned.
    If only_unread=False, ALL chats are returned.
    """
    results = []
    async for dialog in client.iter_dialogs():
        if only_unread and dialog.unread_count < min_unread:
            continue
        results.append(ChatInfo(dialog))
    results.sort(key=lambda c: c.unread_count, reverse=True)
    return results


async def fetch_unread_messages(client, chat_info: ChatInfo, max_msgs=200) -> list:
    """Fetch unread Telethon Message objects for a chat. Returns chronological."""
    chat = await client.get_entity(chat_info.id)

    dialog = None
    async for d in client.iter_dialogs():
        if d.entity.id == chat_info.id:
            dialog = d
            break

    read_max = getattr(dialog.dialog, "read_inbox_max_id", 0) if dialog else 0

    messages = await client.get_messages(chat, limit=max_msgs)
    unread = [m for m in messages if m.id > read_max]
    unread.reverse()
    return unread


async def fetch_last_messages(client, chat_info: ChatInfo, count=100) -> list:
    """Fetch last N messages (regardless of read status). Returns chronological."""
    chat = await client.get_entity(chat_info.id)
    messages = await client.get_messages(chat, limit=count)
    messages.reverse()
    return messages


# --- Translation ---


def _translate_batch(texts: list[str], api_key: str, model: str) -> list[str]:
    """Translate a batch of texts via OpenAI."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    from .i18n import get_language, language_name
    lang = get_language()
    target = language_name(lang)

    system = (
        "You are a professional translator. Your only job is to "
        f"translate texts from any language to {target}, "
        "without omitting anything, without summarizing, "
        "without adding comments. Translate each message in full."
    )

    user = f"Translate the following messages to {target}. Each one separately.\n\n"
    for i, t in enumerate(texts, 1):
        user += f"--- Message {i} ---\n{t}\n\n"
    user += (
        "Reply ONLY with a JSON object of the form: "
        '{"translations": ["translation 1", "translation 2", ...]} '
        "where each element is the full translation of the corresponding message. "
        f"If a message is already in {target}, keep it as-is. "
        "Translate ALL messages without exception."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            response_format={"type": "json_object"},
        )
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
        )

    raw = resp.choices[0].message.content

    translations: list[str] = []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    translations = val
                    break
        elif isinstance(data, list):
            translations = data
    except json.JSONDecodeError:
        pass

    if not translations:
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("{") or line.startswith("}"):
                continue
            if line and line[0].isdigit():
                for sep in [". ", ") ", ". "]:
                    if sep in line[:6]:
                        line = line.split(sep, 1)[1]
                        break
            translations.append(line)

    return translations


def translate_messages(
    messages: list,
    api_key: str,
    model: str = MODEL,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[MessageInfo]:
    """Translate messages in batches of 10. Returns list of MessageInfo."""
    BATCH_SIZE = 10
    texts = [m.text or "(media)" for m in messages]
    all_results: list[MessageInfo] = []
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx, start in enumerate(range(0, len(texts), BATCH_SIZE)):
        batch_texts = texts[start: start + BATCH_SIZE]
        batch_msgs = messages[start: start + BATCH_SIZE]

        batch_translations = _translate_batch(batch_texts, api_key, model)

        for i, msg in enumerate(batch_msgs):
            trans = batch_translations[i] if i < len(batch_translations) else "(translation error)"
            all_results.append(MessageInfo(msg, trans))

        if progress_callback:
            progress_callback(batch_idx + 1, total_batches)

    return all_results


# --- Mark as read ---


async def mark_as_read(client, chat_id: int, last_msg_id: int) -> None:
    """Mark all messages up to last_msg_id as read."""
    chat = await client.get_entity(chat_id)
    if last_msg_id:
        await client.send_read_acknowledge(chat, max_id=last_msg_id)
    else:
        await client.send_read_acknowledge(chat, clear_mentions=True)


# --- Summary via unread ---


def run_unread_summary(chat_ref: str) -> None:
    """Run unread CLI for a chat summary."""
    subprocess.run(["unread", chat_ref, "--report-language", "el"])


# --- Async runner (for sync contexts) ---


def _run_async(coro_func, *args, **kwargs):
    """Run an async function in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_func(*args, **kwargs))
    finally:
        loop.close()


def list_chats_sync(only_unread=True) -> list[ChatInfo]:
    """Sync wrapper: list all chats.

    If only_unread=False, all dialogs are returned (including fully read ones).
    """
    async def _run():
        client = await create_telegram_client()
        try:
            return await get_unread_chats(client, only_unread=only_unread)
        finally:
            await client.disconnect()

    return _run_async(_run)


def translate_chat_sync(
    chat: ChatInfo,
    api_key: str,
    model: str = MODEL,
    max_msgs: int = MAX_PER_CHAT,
    only_unread: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[list[MessageInfo], float]:
    """Sync wrapper: translate messages for a chat.

    If only_unread=True, translate only unread messages.
    If only_unread=False, translate last X messages regardless of read status.
    Returns (messages, est_cost).
    """
    async def _run():
        client = await create_telegram_client()
        try:
            if only_unread:
                msgs = await fetch_unread_messages(client, chat, max_msgs)
            else:
                msgs = await fetch_last_messages(client, chat, max_msgs)
            if not msgs:
                return [], 0.0
            results = translate_messages(msgs, api_key, model, progress_callback)
            total_chars = sum(len(m.text or "") for m in msgs)
            est_cost = (total_chars / 4 / 1000) * 0.00015
            return results, est_cost
        finally:
            await client.disconnect()

    return _run_async(_run)


def mark_read_sync(chat: ChatInfo, last_msg_id: int) -> None:
    """Sync wrapper: mark messages as read."""
    async def _run():
        client = await create_telegram_client()
        try:
            await mark_as_read(client, chat.id, last_msg_id)
        finally:
            await client.disconnect()

    _run_async(_run)



import tempfile
import time
from pathlib import Path

_VIDEO_TEMP = Path(tempfile.gettempdir()) / "tg-translate-videos"

def _ensure_video_dir():
    _VIDEO_TEMP.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for f in _VIDEO_TEMP.iterdir():
        if f.is_file() and now - f.stat().st_mtime > 259200:
            f.unlink()

async def download_video(client, msg) -> str | None:
    if not msg.video:
        return None
    size = getattr(msg.video, "size", 0) or 0
    if size > 50 * 1024 * 1024:
        return None
    _ensure_video_dir()
    ext = ".mp4"
    if msg.video.mime_type:
        em = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/webm": ".webm"}
        ext = em.get(msg.video.mime_type, ".mp4")
    fname = f"{msg.id}_{int(time.time())}{ext}"
    path = str(_VIDEO_TEMP / fname)
    await client.download_media(msg, path)
    return path

async def send_reaction(client, chat_id, msg_id, reaction):
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji
    await client(SendReactionRequest(peer=chat_id, msg_id=msg_id, reaction=[ReactionEmoji(emoticon=reaction)]))

def download_video_sync(msg) -> str | None:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_dv_async(msg))
    finally:
        loop.close()

async def _dv_async(msg):
    client = await create_telegram_client()
    try:
        return await download_video(client, msg)
    finally:
        await client.disconnect()

def send_reaction_sync(chat_id, msg_id, reaction):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_sr_async(chat_id, msg_id, reaction))
    finally:
        loop.close()

async def _sr_async(chat_id, msg_id, reaction):
    client = await create_telegram_client()
    try:
        await send_reaction(client, chat_id, msg_id, reaction)
    finally:
        await client.disconnect()
def check_env() -> tuple[bool, str]:
    """Check if required environment variables are set. Returns (is_ok, message)."""
    missing = []
    if not os.environ.get("TG_API_ID") or not os.environ.get("TG_API_HASH"):
        missing.append("TG_API_ID / TG_API_HASH (https://my.telegram.org)")
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY (https://platform.openai.com)")

    if missing:
        return False, "Missing:\n" + "\n".join(f"  * {m}" for m in missing)
    return True, "OK"
