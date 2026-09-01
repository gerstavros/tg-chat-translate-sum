"""
tg-translate — Telegram full-translation & summary companion.

Backend module: Telegram client, translation, config loading.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

# --- Load .env ---
# Settings save to APP_ENV_PATH; older versions wrote next to the package
# (package/.env). Migrate that file once so first-run credentials survive
# restarts, then load with priority: app config dir > CWD (dev).
APP_CONFIG_DIR = Path.home() / ".chat-translate-sum"
APP_ENV_PATH = APP_CONFIG_DIR / ".env"
_LEGACY_PACKAGE_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


def _load_env() -> None:
    try:
        if not APP_ENV_PATH.exists() and _LEGACY_PACKAGE_ENV.exists():
            APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_LEGACY_PACKAGE_ENV, APP_ENV_PATH)
            try:
                os.chmod(APP_ENV_PATH, 0o600)  # τα .env να μην είναι readable από άλλους
            except Exception:
                pass
    except Exception:
        pass
    for p in (APP_ENV_PATH, Path.cwd() / ".env"):
        if p.exists():
            load_dotenv(p)


_load_env()

SESSION_PATH = Path.home() / ".chat-translate-sum" / "session.session"
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


class NotAuthorizedError(RuntimeError):
    """Raised when an authorized Telegram session is required but missing."""


def _migrate_legacy_session() -> None:
    """Copy the old unread's Telegram session into our own path once, so the
    user doesn't have to log in again after the unread removal."""
    if SESSION_PATH.exists():
        return
    legacy = Path.home() / ".unread" / "storage" / "session.sqlite.session"
    if not legacy.exists():
        return
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, SESSION_PATH)
    except Exception:
        pass


def _make_client_unconnected():
    """Build (but not connect) a Telethon client using our own session."""
    from telethon import TelegramClient

    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")

    if not api_id or not api_hash:
        from .i18n import _

        raise RuntimeError(_("error.env_missing"))

    _migrate_legacy_session()
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(SESSION_PATH), int(api_id), api_hash)


async def create_telegram_client():
    """Connect an already-authorized Telethon client.

    Login (QR/SMS) must happen separately via LoginSession before this is called;
    this never falls back to an interactive console prompt..
    """
    client = _make_client_unconnected()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        from .i18n import _

        raise NotAuthorizedError(_("error.not_authorized"))
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
    """Translate messages in batches of 10. Returns list of MessageInfo. Test needed for bigger or smaller batchs"""
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
    chat = await client.get_entity(chat_id)
    if last_msg_id:
        await client.send_read_acknowledge(chat, max_id=last_msg_id)
    else:
        await client.send_read_acknowledge(chat, clear_mentions=True)


# --- Summary ---

SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", MODEL)
SUMMARY_BATCH_CHARS = int(os.environ.get("SUMMARY_BATCH_CHARS", "6000"))


def _message_link(chat: ChatInfo, msg_id: int) -> str:
    """Build a Telegram message link for a chat, or '' if unknown."""
    try:
        if chat.username:
            return f"https://t.me/{chat.username}/{msg_id}"
        return f"https://t.me/c/{chat.id}/{msg_id}"
    except Exception:
        return ""


def _message_line(msg, chat: ChatInfo) -> str:
    """Render a single Telethon message as a compact digest line."""
    time_str = "?"
    if msg.date:
        try:
            time_str = msg.date.strftime("%H:%M")
        except Exception:
            time_str = "?"
    name = None
    if msg.sender:
        name = (
            getattr(msg.sender, "first_name", None)
            or getattr(msg.sender, "title", None)
            or getattr(msg.sender, "username", None)
        )
    reactions = ""
    try:
        if msg.reactions and getattr(msg.reactions, "results", None):
            counts = [f"{r.reaction.emoticon}×{r.count}" for r in msg.reactions.results if getattr(r, "reaction", None) and hasattr(r.reaction, "emoticon")]
            if counts:
                reactions = " [reactions: " + ", ".join(counts) + "]"
    except Exception:
        pass
    text = (msg.text or "").strip()
    if not text:
        if msg.photo:
            text = "[photo]"
        elif msg.video:
            text = "[video]"
        elif getattr(msg, "document", None):
            text = "[document]"
        elif msg.sticker:
            text = "[sticker]"
        else:
            text = "[media]"
    link = _message_link(chat, msg.id or 0)
    cite = f"[#{msg.id}]({link})" if link else f"#{msg.id}"
    author = f" {name}:" if name else ":"
    return f"[{time_str}] {author} {text}{reactions} {cite}"


def _summary_prompt(
    lang_code: str, lang_name: str, lines: list[str], phase: str
) -> tuple[str, str]:
    """Return (system, user) for a digest chunk or for the final merge.

    `phase` is "map" (one chunk) or "reduce" (merging chunk digests).
    Format mirrors the unread `summary` preset: TL;DR + Main + Ideas and
    Decisions + Worth checking, written in the user's UI language.
    """
    body = "\n\n".join(f"{i + 1}. {ln}" for i, ln in enumerate(lines))

    lang_rule = (
        f"Write the entire analysis in `{lang_name}` (language code `{lang_code}`). "
        "Detect the source messages' language yourself — if it differs from the "
        "output language, write the analysis in the output language anyway. "
        "Direct quotations stay in the source language; everything else — "
        "headings, bullets, prose — is in the output language."
    )

    if phase == "map":
        system = (
            "You are an attentive Telegram chat reader producing a report called "
            "`summary` for a busy person. Give them a concentrate, not a recap. "
            "Rely only on the provided messages; never invent facts.\n\n"
            "Genre rules (strict):\n"
            "- No retelling. If your wording is close to what the author wrote, it's "
            "not an insight — drop it.\n"
            "- Cut the chatter: greetings, acknowledgements, 'ok', 'thanks', lone "
            "emoji, unanswered questions don't belong.\n"
            "- One bullet = one conclusion. Don't pile several subjects into one line.\n"
            "- Prefer concrete to abstract. 'Team agreed to switch from Y to X because "
            "of Z' is good; 'discussed strategy' is bad.\n"
            "- As many bullets as warranted, no more. A short exchange can compress to "
            "2-3 bullets; don't stretch to a round number.\n"
            "- Reactions tags (`[reactions: 👍×N ...]`) signal messages the chat "
            "responded to — prefer them, but reactions alone don't make a banal "
            "message valuable.\n"
            "- Every bullet must cite a specific message via the `[#<id>](link)` that "
            "appears at the end of the message line. Keep those links verbatim.\n\n"
            "Output the report in strict markdown with these sections:\n"
            "## TL;DR\n"
            "One or two lines: what happened in the chat during the period.\n\n"
            "## Main\n"
            "2-4 bullets of the concentrated insights/takeaways the chat produced. "
            "Each bullet: what's specifically new/important + a citation.\n\n"
            "## Ideas and Decisions\n"
            "What was proposed or decided, what can be taken on. Skip this section "
            "entirely if there was nothing of the sort.\n\n"
            "## Worth checking\n"
            "3-5 messages that give the most signal per byte, each with a link and a "
            "one-line reason to read it.\n\n"
            "If the chat had nothing valuable (just greetings, stickers, etc.), write "
            "a single line: 'Nothing valuable was discussed during the period.' and "
            "stop. Do not stretch.\n\n"
            + lang_rule
        )
        user = (
            "Analyze this Telegram chat and produce the `summary` report.\n\n"
            f"{body}"
        )
    else:  # reduce
        system = (
            "Below are several already-written summaries of the same chat, produced "
            "from different chunks of the conversation. Merge them into ONE final "
            "report in the requested format.\n\n"
            "Merge rules:\n"
            "1. Don't duplicate bullets. If the same thought appears in multiple "
            "chunks, combine into one bullet, gathering all relevant citations.\n"
            "2. Preserve the section structure (## TL;DR, ## Main, ## Ideas and "
            "Decisions, ## Worth checking).\n"
            "3. Keep the limits: 2-4 Main bullets, 3-5 Worth checking. Drop middling "
            "bullets rather than ship a wall.\n"
            "4. TL;DR appears exactly once — pick the best variant or rewrite, don't "
            "concatenate.\n"
            "5. Keep facts intact: numbers, names, [#N](link) citations — verbatim.\n\n"
            + lang_rule
        )
        user = f"Merge these chunk summaries into one final report:\n\n{body}"

    return system, user


def _summarize_chunk(
    lines: list[str], api_key: str, model: str, phase: str = "map"
) -> str:
    """Send one chunk (or the merge of chunk digests) to OpenAI."""
    from openai import OpenAI

    from .i18n import get_language, language_name

    client = OpenAI(api_key=api_key)
    lang = get_language()

    system, user = _summary_prompt(lang, language_name(lang), lines, phase)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def summarize_chat_sync(
    chat: ChatInfo,
    api_key: str,
    model: str = SUMMARY_MODEL,
    max_msgs: int = MAX_PER_CHAT,
    only_unread: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[str, int]:
    """Sync wrapper: summarize messages for a chat via OpenAI.

    Returns (report_text, message_count). Empty report on no messages.
    """
    async def _run():
        client = await create_telegram_client()
        try:
            if only_unread:
                msgs = await fetch_unread_messages(client, chat, max_msgs)
            else:
                msgs = await fetch_last_messages(client, chat, max_msgs)
            if not msgs:
                return "", 0

            digests: list[str] = []
            chunk: list[str] = []
            chunk_chars = 0
            total = len(msgs)
            done = 0
            for msg in msgs:
                line = _message_line(msg, chat)
                chunk.append(line)
                chunk_chars += len(line) + 1
                done += 1
                if chunk_chars >= SUMMARY_BATCH_CHARS:
                    digests.append(_summarize_chunk(chunk, api_key, model, phase="map"))
                    chunk, chunk_chars = [], 0
                    if progress_callback:
                        progress_callback(done, total)
            if chunk:
                digests.append(_summarize_chunk(chunk, api_key, model, phase="map"))
            if progress_callback:
                progress_callback(total, total)

            if len(digests) == 1:
                return digests[0], total

            merged = _summarize_chunk(digests, api_key, model, phase="reduce")
            return merged, total
        finally:
            await client.disconnect()

    return _run_async(_run)


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
