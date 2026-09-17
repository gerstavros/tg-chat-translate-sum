"""
tg-translate GUI with CustomTkinter
"""

from __future__ import annotations

import io
import sys
import os
import re
import threading
import webbrowser
from pathlib import Path
from tkinter import Frame as TkFrame, Menu as TkMenu, Text

import customtkinter as ctk

from .i18n import _, set_language, get_language, available_languages, language_name
try:
    import vlc
except ImportError:
    vlc = None

from .icons import get

import tkinter.simpledialog as _sd
_orig_body = getattr(_sd._QueryDialog, "body", None)
if _orig_body:
    def _patched_body(self, master):
        result = _orig_body(self, master)
        if hasattr(self, "entry") and self.entry:
            self.entry.bind("<KP_Enter>", lambda e: self.ok())
        return result
    _sd._QueryDialog.body = _patched_body

#
from .backend import (
    APP_ENV_PATH,
    ChatInfo,
    MAX_PER_CHAT,
    MODEL,
    MessageInfo,
    NotAuthorizedError,
    check_env,
    download_video_sync,
    is_authorized_sync,
    list_chats_sync,
    load_window_geometry,
    mark_read_sync,
    save_window_geometry,
    send_reaction_sync,
    summarize_chat_sync,
    translate_chat_sync,
)

from . import APP_VERSION

# ── Theme ───────────────────────────────────────────────────────────────
ctk.set_appearance_mode("system")
ctk.set_default_color_theme(os.path.join(os.path.dirname(__file__), "assets", "theme.json"))

# ── Constants (να μπει στις ρυθμισεις?) ───────────────────────────────────────────────────────────
BUBBLE_PAD = 8
BUBBLE_RADIUS = 12


# ── Telegram text formatting ────────────────────────────────────────────


def _ctk_dialog(title, message, parent=None):
    dlg = ctk.CTkToplevel(parent) if parent else ctk.CTkToplevel()
    dlg.title(title)
    dlg.geometry("450x200")
    dlg.resizable(False, False)
    if parent:
        try:
            x = parent.winfo_rootx() + parent.winfo_width() // 2 - 225
            y = parent.winfo_rooty() + parent.winfo_height() // 2 - 100
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass
    dlg.transient(parent)
    dlg.update_idletasks()
    dlg.grab_set()
    ctk.CTkLabel(dlg, text=message, wraplength=400, font=("", 13)).pack(pady=30, padx=20)
    ctk.CTkButton(dlg, text=_("dialog.ok"), width=80, command=dlg.destroy).pack(pady=10)
    if parent:
        parent.wait_window(dlg)


def _apply_formatting(widget, text: str) -> None:
    # Use internal _textbox for CTkTextbox (bypasses font restriction in tag_config)
    if hasattr(widget, '_textbox'):
        tw = widget._textbox
    else:
        tw = widget
    pattern = (
        r"(?P<pre>```.+?```)|"
        r"(?P<code>`[^`]+?`)|"
        r"(?P<bold>\*\*(.+?)\*\*)|"
        r"(?P<italic>__(.+?)__)|"
        r"(?P<strike>~~(.+?)~~)|"
        r"(?P<link>\[([^\]]+)\]\(([^)]+)\))"
    )

    for tag_name in ("bold", "italic", "strike", "code", "pre", "link", "sep"):
        if tag_name not in tw.tag_names():
            if tag_name == "bold":
                tw.tag_config("bold", font=("TkDefaultFont", 12, "bold"))
            elif tag_name == "italic":
                tw.tag_config("italic", font=("TkDefaultFont", 12, "italic"))
            elif tag_name == "strike":
                tw.tag_config("strike", overstrike=True, font=("TkDefaultFont", 12, "overstrike"))
            elif tag_name == "code":
                fg = "#00cc66" if ctk.get_appearance_mode() == "Dark" else "#2d7d2d"
                bg = "#333333" if ctk.get_appearance_mode() == "Dark" else "#e8e8e8"
                tw.tag_config("code", font=("Courier", 11), foreground=fg, background=bg)
            elif tag_name == "pre":
                fg = "#e0e0e0" if ctk.get_appearance_mode() == "Dark" else "#333333"
                bg = "#2d2d2d" if ctk.get_appearance_mode() == "Dark" else "#f0f0f0"
                tw.tag_config("pre", font=("Courier", 11), foreground=fg, background=bg)
            elif tag_name == "link":
                tw.tag_config("link", foreground="#00aaff", underline=True)
            elif tag_name == "sep":
                tw.tag_config("sep", foreground="#888888", font=("TkDefaultFont", 9))

    pos = 0
    while pos < len(text):
        match = re.search(pattern, text[pos:], re.DOTALL)
        if not match:
            tw.insert("end", text[pos:])
            break

        if match.start() > 0:
            tw.insert("end", text[pos: pos + match.start()])

        kind = match.lastgroup
        if kind == "bold":
            tw.insert("end", match.group(4), "bold")
        elif kind == "italic":
            tw.insert("end", match.group(6), "italic")
        elif kind == "strike":
            tw.insert("end", match.group(8), "strike")
        elif kind == "code":
            tw.insert("end", match.group(0).strip("`"), "code")
        elif kind == "pre":
            tw.insert("end", "\n")
            content = match.group(0).strip("```").strip()
            start = tw.index("end-1c")
            tw.insert("end", content)
            end = tw.index("end-1c")
            tw.tag_add("pre", start, end)
            tw.insert("end", "\n")
        elif kind == "link":
            link_match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", match.group(0))
            if link_match:
                link_text, link_url = link_match.group(1), link_match.group(2)
                start = tw.index("end-1c")
                tw.insert("end", link_text, "link")
                end = tw.index("end-1c")
                tw.tag_bind("link", "<Button-1>", lambda e, u=link_url: webbrowser.open(u))
                tw.tag_bind("link", "<Enter>", lambda e: widget.configure(cursor="hand2"))
                tw.tag_bind("link", "<Leave>", lambda e: widget.configure(cursor=""))

        pos += match.end()

    tw.insert("end", "\n")


_URL_RE = re.compile(r"https?://[^\s<>'\"]+")


def _open_url_tag(event):
    tw = event.widget
    try:
        idx = tw.index("current")
        ranges = tw.tag_ranges("url_link")
        for i in range(0, len(ranges), 2):
            start, end = ranges[i], ranges[i + 1]
            if tw.compare(start, "<=", idx) and tw.compare(idx, "<=", end):
                webbrowser.open(tw.get(start, end))
                break
    except Exception:
        pass


def _insert_with_links(widget, text):
    tw = getattr(widget, "_textbox", widget)
    if "url_link" not in tw.tag_names():
        tw.tag_config("url_link", foreground="#00aaff", underline=True)
        tw.tag_bind("url_link", "<Button-1>", _open_url_tag)
        tw.tag_bind("url_link", "<Enter>", lambda e: tw.configure(cursor="hand2"))
        tw.tag_bind("url_link", "<Leave>", lambda e: tw.configure(cursor=""))
    pos = 0
    for m in _URL_RE.finditer(text):
        if m.start() > pos:
            tw.insert("end", text[pos:m.start()])
        url = m.group(0)
        while url and url[-1] in ".,;:!?)]}\"'" :
            url = url[:-1]
        tw.insert("end", url, "url_link")
        pos = m.start() + len(url)
    tw.insert("end", text[pos:])


# ── Media helpers ───────────────────────────────────────────────────────


def _download_message_media(client, msg) -> bytes | None:
    """Download media from a message. Returns bytes or None."""
    import asyncio

    async def _download():
        if msg.photo:
            buf = io.BytesIO()
            await client.download_media(msg, buf)
            buf.seek(0)
            return buf.read()
        return None

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_download())
    finally:
        loop.close()


def _photo_from_bytes(data: bytes, max_width=320):
    """convert image bytes to CTkImage (for scaling support), resized. Future: put variable to change from settings the iamge preview size."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)
        return ctk.CTkImage(img, size=img.size)
    except Exception:
        return None


# ── Context menu ────────────────────────────────────────────────────────


def _bind_arrows(app):
    try:
        for path in app.winfo_toplevel().tk.eval('winfo children .').split():
            if app.winfo_toplevel().tk.eval(f'winfo class {path}').strip() == 'Dialog':
                win = app._nametowidget(path)
                def nav(e, w=win):
                    try:
                        btns = [b for b in w.winfo_children() if b.winfo_class() == 'Button']
                        for i, btn in enumerate(btns):
                            if btn == w.focus_get():
                                if e.keysym == 'Left' and i > 0: btns[i-1].focus_set()
                                elif e.keysym == 'Right' and i < len(btns)-1: btns[i+1].focus_set()
                                elif e.keysym in ('Return', 'KP_Enter'): btn.invoke()
                                return
                        if btns and e.keysym in ('Left', 'Right'): btns[0].focus_set()
                    except: pass
                win.bind('<Left>', nav)
                win.bind('<Right>', nav)
                win.bind('<Return>', nav)
                win.bind('<KP_Enter>', nav)
    except: pass


_open_menu = None
_menu_close_bound = False


def _close_context_menu(event=None):
    global _open_menu
    m = _open_menu
    _open_menu = None
    if m is not None:
        try:
            if m.winfo_ismapped():
                m.unpost()
        except Exception:
            pass


def _add_context_menu(widget) -> None:
    """Add right-click context menu to a Text widget."""
    global _menu_close_bound
    if not _menu_close_bound:
        _menu_close_bound = True
        top = widget.winfo_toplevel()
        top.bind("<Button-1>", _close_context_menu, add="+")
        top.bind("<Button-2>", _close_context_menu, add="+")
        top.bind("<Escape>", _close_context_menu, add="+")
    menu = TkMenu(widget, tearoff=False)

    def _copy():
        widget.event_generate("<<Copy>>")

    def _select_all():
        widget.tag_add("sel", "1.0", "end")
        return "break"

    def _copy_all():
        content = widget.get("1.0", "end-1c")
        widget.clipboard_clear()
        widget.clipboard_append(content)

    menu.add_command(label=_("menu.copy"), command=_copy, accelerator="Ctrl+C")
    menu.add_command(label=_("menu.select_all"), command=_select_all, accelerator="Ctrl+A")
    menu.add_command(label=_("menu.copy_all"), command=_copy_all)

    def _show_menu(event):
        global _open_menu
        try:
            widget.selection_get()
            menu.entryconfig(0, state="normal")
        except Exception:
            menu.entryconfig(0, state="disabled")
        _open_menu = menu
        menu.post(event.x_root, event.y_root)

    widget.bind("<Button-3>", _show_menu)
    widget.bind("<Control-a>", _select_all)
    widget.bind("<Control-A>", _select_all)


# ── Main Application ────────────────────────────────────────────────────


class App(ctk.CTk):
    """Main GUI application."""

    def __init__(self) -> None:
        super().__init__()
        ctk.set_widget_scaling(1.1)

        self.title("Chat Translate & Sum for Telegram")
        self.geometry("1200x850")
        self.minsize(1200, 850)
        # Apply the saved geometry deferred: setting it before the window is first mapped gets ignored by the WM, which falls back to minsize.
        saved_geometry = load_window_geometry()
        if saved_geometry:
            self.after(10, lambda: self.geometry(saved_geometry))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._geometry_save_after_id: str | None = None
        self.bind("<Configure>", self._on_configure, add="+")

        # State
        self.chats: list[ChatInfo] = []
        self._current_chat: ChatInfo | None = None
        self._msg_frames: list[ctk.CTkFrame] = []
        self._photo_refs: list = []
        self._raw_msg_map: dict[int, object] = {}
        self._vlc_players: list = []
        self._translate_pending_filter: dict | None = None

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        # don't let child content resize the window.
        self.grid_propagate(False)

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self._build_footer()

        # Set window icon from logo
        try:
            from PIL import Image
            icon_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                from tkinter import PhotoImage
                # Use CTkImage for taskbar/dock
                self.iconphoto(True, PhotoImage(file=icon_path))
        except Exception:
            pass

        # Re-apply language preference from .env (bypasses load_dotenv's no-override)
        lang = ""
        try:
            from dotenv import dotenv_values
            env_vals = {}
            for p in (Path.cwd() / ".env", APP_ENV_PATH):
                try:
                    env_vals.update(dotenv_values(p))
                except Exception:
                    pass
            lang = env_vals.get("LANGUAGE", "")
            if lang and lang != get_language():
                set_language(lang)
        except Exception:
            pass
        if lang:
            self._rebuild_ui()

        self.after(100, self.load_chats)

    # ── Header ───────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text=_("app.title"), font=("", 20, "bold")).grid(
            row=0, column=0, padx=(0, 10))
        self.status_label = ctk.CTkLabel(header, text="", font=("", 12))
        self.status_label.grid(row=0, column=1, sticky="w")
        ctk.CTkButton(header, text=_("header.settings"), image=get("settings"), width=100,
                       command=self.open_settings).grid(row=0, column=2, padx=(10, 0))

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self.main_frame, fg_color="transparent", height=30)
        footer.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 8))
        footer.grid_columnconfigure(0, weight=1)
        self.footer_label = ctk.CTkLabel(footer, text="", font=("", 10))
        self.footer_label.grid(row=0, column=0, sticky="w")

    # ── Tabs ─────────────────────────────────────────────────────────

    def _build_tabs(self) -> None:
        self.tab_view = ctk.CTkTabview(self.main_frame)
        self.tab_view.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)

        self.tab_chats = self.tab_view.add(_("tab.chats"))
        self.tab_translate = self.tab_view.add(_("tab.translate"))
        self.tab_summary = self.tab_view.add(_("tab.summary"))

        self._build_chats_tab()
        self._build_translate_tab()
        self._build_summary_tab()

    # ── Chats tab ────────────────────────────────────────────────────

    def _build_chats_tab(self) -> None:
        self.tab_chats.grid_columnconfigure(0, weight=1)
        self.tab_chats.grid_rowconfigure(1, weight=1)

        self.chat_search_var = ctk.StringVar()
        self.chat_search_entry = ctk.CTkEntry(self.tab_chats, textvariable=self.chat_search_var, placeholder_text=_("chats.search"))
        self.chat_search_entry.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 8))
        self.chat_search_entry.bind("<KeyRelease>", self._filter_chats)

        self.chat_scroll = ctk.CTkScrollableFrame(self.tab_chats)
        self.chat_scroll.grid(row=1, column=0, sticky="nsew")
        self.chat_scroll.grid_columnconfigure(0, weight=1)
        self._selected_chat_id: int | None = None
        self._chat_items: list[ctk.CTkFrame] = []  # track item frames

        btn_frame = ctk.CTkFrame(self.tab_chats, fg_color="transparent")
        btn_frame.grid(row=2, column=0, pady=(15, 5))
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(btn_frame, text=_("chats.button.translate"), image=get("translate"),
                       command=self.translate_selected).grid(row=0, column=0, padx=5)
        ctk.CTkButton(btn_frame, text=_("chats.button.summary"), image=get("read"),
                       command=self.summary_selected).grid(row=0, column=1, padx=5)
        ctk.CTkButton(btn_frame, text=_("chats.button.refresh"), image=get("refresh"),
                       command=self.load_chats).grid(row=0, column=2, padx=5)

    def _populate_chat_tree(self) -> None:
        # eraze old item frames
        for item in self._chat_items:
            item.destroy()
        self._chat_items = []
        src = getattr(self, "_all_chats", self.chats)
        is_dark = ctk.get_appearance_mode() == "Dark"
        for c in src:
            item = ctk.CTkFrame(self.chat_scroll, fg_color="transparent", height=30)
            item.pack(fill="x", padx=4, pady=2)
            item.grid_columnconfigure(1, weight=1)
            # Column 0: type (chat, group or channel. loads icon from svg assets folder)
            icon_img = get(c.kind_icon, 18)
            icon = ctk.CTkLabel(item, text="", image=icon_img, width=30) if icon_img else ctk.CTkLabel(item, text=c.kind_icon[0].upper(), width=30)
            icon.grid(row=0, column=0, padx=(6, 2), pady=2, sticky="w")
            # Column 1: name
            name = ctk.CTkLabel(item, text=c.name, font=("", 14), anchor="w")
            name.grid(row=0, column=1, padx=2, pady=2, sticky="w")
            # Column 2: username
            uname_text = f"@{c.username}" if c.username else ""
            uname = ctk.CTkLabel(item, text=uname_text, font=("", 12),
                                 text_color=("gray40" if not is_dark else "gray60"), width=140)
            uname.grid(row=0, column=2, padx=2, pady=2, sticky="w")
            # Column 3: unread badge
            badge_text = str(c.unread_count) if c.unread_count else ""
            if badge_text:
                badge = ctk.CTkLabel(item, text=badge_text, font=("", 13, "bold"), width=36,
                                     fg_color=("#5EB5F7" if not is_dark else "#3B8ED0"),
                                     text_color="white", corner_radius=10)
            else:
                badge = ctk.CTkLabel(item, text="", width=36)
            badge.grid(row=0, column=3, padx=(4, 6), pady=2, sticky="e")
            # Click handle
            def _on_click(e, cid=c.id):
                self._select_chat(cid)
                self.translate_selected()
            def _on_select(e, cid=c.id):
                self._select_chat(cid)
            for w in (item, icon, name, uname, badge):
                w.bind("<Button-1>", _on_select)
            for w in (item, icon, name):
                w.bind("<Double-Button-1>", _on_click)
            item.cid = c.id
            self._chat_items.append(item)
        total = sum(c.unread_count for c in self.chats)
        self.status_label.configure(text=_("app.status_chats", count=len(self.chats), unread=total))
        self.footer_label.configure(text=_("app.loaded"))

    # ── Translate tab (bubble layout) ────────────────────────────────

    def _build_translate_tab(self) -> None:
        self.tab_translate.grid_columnconfigure(0, weight=1)
        self.tab_translate.grid_rowconfigure(2, weight=1)

        # Header
        self.translate_header = ctk.CTkLabel(
            self.tab_translate,
            text=_("translate.placeholder"),
            font=("", 14, "bold"),
        )
        self.translate_header.grid(row=0, column=0, sticky="w", pady=(0, 5))

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(self.tab_translate)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        self.progress_bar.set(0)

# Two-column scrollable area with PanedWindow
        paned = ctk.CTkFrame(self.tab_translate)
        paned.grid(row=2, column=0, sticky="nsew")
        paned.grid_columnconfigure((0, 1), weight=1)
        paned.grid_rowconfigure(1, weight=1)  # give weight to scrollable rows, not headers

        # Left column: originals
        left_header = ctk.CTkLabel(paned, text=_("translate.header_original"), font=("", 12, "bold"))
        left_header.grid(row=0, column=0, sticky="w", pady=(0, 3))
        self.left_scroll = ctk.CTkScrollableFrame(paned)
        self.left_scroll.grid(row=1, column=0, sticky="nsew", padx=(0, 2))
        self.left_scroll.grid_columnconfigure(0, weight=1)

        # Right column: translations
        right_header = ctk.CTkLabel(paned, text=_("chats.button.translate"), image=get("translate"), font=("", 12, "bold"), compound="left")
        right_header.grid(row=0, column=1, sticky="w", pady=(0, 3))
        self.right_scroll = ctk.CTkScrollableFrame(paned)
        self.right_scroll.grid(row=1, column=1, sticky="nsew", padx=(2, 0))
        self.right_scroll.grid_columnconfigure(0, weight=1)

        # Sync scrolling: when one scrolls, the other follows
        def _sync_both(source, target):
            def _handler(*args):
                frac = source._parent_canvas.yview()
                # Update the other frame
                target._parent_canvas.yview_moveto(frac[0])
                # Also update the source's own scrollbar
                source._scrollbar.set(frac[0], frac[1])
            return _handler

        self.left_scroll._parent_canvas.configure(
            yscrollcommand=_sync_both(self.left_scroll, self.right_scroll))
        self.right_scroll._parent_canvas.configure(
            yscrollcommand=_sync_both(self.right_scroll, self.left_scroll))

        # Footer buttons
        action_frame = ctk.CTkFrame(self.tab_translate, fg_color="transparent")
        action_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        action_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.mark_read_btn = ctk.CTkButton(
            action_frame, text=_("translate.mark_read"), image=get("read"),
            command=self.mark_current_read, state="disabled")
        self.mark_read_btn.grid(row=0, column=0, padx=5)

        self.copy_btn = ctk.CTkButton(
            action_frame, text=_("translate.copy"), image=get("copy"),
            command=self.copy_translations, state="disabled")
        self.copy_btn.grid(row=0, column=1, padx=5)

        retrans_btn = ctk.CTkButton(
            action_frame, text=_("translate.retranslate"), image=get("refresh"),
            command=self.retranslate, state="disabled"
        )
        retrans_btn.grid(row=0, column=2, padx=5)
        retrans_btn._is_retranslate = True

    # ── Summary tab ──────────────────────────────────────────────────

    def _build_summary_tab(self) -> None:
        """Build the summary tab with a text area (mayby change it to something more nice instead of textarea?)"""
        self.tab_summary.grid_columnconfigure(0, weight=1)
        self.tab_summary.grid_rowconfigure(2, weight=1)

        # header + μπάρα, όπως στην καρτέλα Μετάφρασης
        self.summary_header = ctk.CTkLabel(
            self.tab_summary,
            text=_("translate.placeholder"),
            font=("", 14, "bold"),
        )
        self.summary_header.grid(row=0, column=0, sticky="w", pady=(0, 5))

        self.summary_progress = ctk.CTkProgressBar(self.tab_summary)
        self.summary_progress.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        self.summary_progress.set(0)

        self.summary_text = ctk.CTkTextbox(
            self.tab_summary, wrap="word", font=("", 16),
        )
        self.summary_text.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        self.summary_text.insert("1.0", _("summary.placeholder") + "\n\n" + _("summary.hint") + "\n")
        _add_context_menu(self.summary_text)
        self.summary_mark_read_btn = ctk.CTkButton(self.tab_summary, text=_("translate.mark_read"), image=get("read"), compound="left", state="disabled", command=self.summary_mark_read)
        self.summary_mark_read_btn.grid(row=3, column=0, sticky="w", padx=10, pady=(10, 0))

    # ── Message bubbles (two-column) ─────────────────────────────────

    def _ask_yes_no(self, title, message, parent=None):
        res = None
        dlg = ctk.CTkToplevel(parent) if parent else ctk.CTkToplevel()
        dlg.title(title)
        dlg.geometry("400x150")
        dlg.resizable(False, False)
        if parent:
            x = parent.winfo_rootx() + parent.winfo_width() // 2 - 200
            y = parent.winfo_rooty() + parent.winfo_height() // 2 - 75
            dlg.geometry(f"+{x}+{y}")
        dlg.transient(parent)
        dlg.update_idletasks()
        dlg.grab_set()
        ctk.CTkLabel(dlg, text=message, wraplength=360, font=("", 12)).pack(pady=25)
        bf = ctk.CTkFrame(dlg, fg_color="transparent")
        bf.pack(pady=10)
        def _yes():
            nonlocal res
            res = True
            dlg.destroy()
        def _no():
            nonlocal res
            res = False
            dlg.destroy()
        def _cancel():
            nonlocal res
            res = None
            dlg.destroy()
        ctk.CTkButton(bf, text=_("dialog.yes"), width=70, command=_yes).pack(side="left", padx=8)
        ctk.CTkButton(bf, text=_("dialog.no"), width=70, command=_no).pack(side="left", padx=8)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        if parent:
            parent.wait_window(dlg)
        return res

    def _ask_integer(self, title, prompt, minv=1, maxv=500, default=5):
        from tkinter import StringVar
        res = None
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry("400x180")
        dlg.resizable(False, False)
        dlg.transient(self)
        x = self.winfo_rootx() + self.winfo_width() // 2 - 200
        y = self.winfo_rooty() + self.winfo_height() // 2 - 90
        dlg.geometry(f"+{x}+{y}")
        dlg.update_idletasks()
        dlg.grab_set()
        ctk.CTkLabel(dlg, text=prompt, wraplength=360, font=("", 12)).pack(pady=20)
        var = StringVar(value="")
        entry = ctk.CTkEntry(dlg, textvariable=var, width=100, justify="center", font=("", 14))
        entry.pack(pady=10)
        entry.focus_set()
        entry.configure(state="normal")
        bf = ctk.CTkFrame(dlg, fg_color="transparent")
        bf.pack(pady=10)
        def _ok():
            nonlocal res
            try:
                v = int(var.get())
                if minv <= v <= maxv:
                    res = v
                dlg.destroy()
            except ValueError:
                pass
        def _cancel():
            dlg.destroy()
        ctk.CTkButton(bf, text=_("dialog.ok"), width=70, command=_ok).pack(side="left", padx=8)
        ctk.CTkButton(bf, text=_("dialog.cancel"), width=70, command=_cancel).pack(side="left", padx=8)
        entry.bind("<Return>", lambda e: _ok())
        entry.bind("<KP_Enter>", lambda e: _ok())
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        self.wait_window(dlg)
        return res

    def _show_translate_dialog(self, chat) -> None:
        """Show translate filter dialog using built-in dialogs."""
        self.after(100, lambda: _bind_arrows(self))
        choice = self._ask_yes_no(_("translate.dialog_title"), _("translate.dialog_unread_only"), parent=self)
        if choice is None:
            return
        if choice:
            self._do_translate(chat, True, 0)
        else:
            count = self._ask_integer(_("translate.dialog_count_title"), _("translate.dialog_count_prompt"), 1, 500, 50)
            if count:
                self._do_translate(chat, False, count)

    def _show_summary_dialog(self, chat) -> None:
        """Show summary filter dialog using built-in dialogs."""
        self.after(100, lambda: _bind_arrows(self))
        choice = self._ask_yes_no(_("summary.dialog_title"), _("summary.dialog_unread_only"), parent=self)
        if choice is None:
            return
        if choice:
            self._do_summary(chat, 50, True)
        else:
            count = self._ask_integer(_("summary.dialog_count_title"), _("summary.dialog_count_prompt"), 1, 500, 50)
            if count:
                self._do_summary(chat, count, False)

    def _do_translate(self, chat, only_unread, msg_count) -> None:
        self._translate_pending_filter = {"only_unread": only_unread, "msg_count": msg_count}
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            _ctk_dialog(_("error.dialog_title"), _("error.api_key_not_found"), parent=self)
            return
        self._current_chat = chat
        self.tab_view.set(_("tab.translate"))
        status = _("translate.status_unread", count=chat.unread_count) if only_unread else _("translate.status_msgs", count=msg_count)
        self.translate_header.configure(text=_("translate.header_title", chat=chat.name, status=status))
        self._clear_bubbles()
        self.progress_bar.set(0)
        self.footer_label.configure(text=_("translate.fetching", chat=chat.name))
        self.mark_read_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self._set_retranslate_state("disabled")

        def _fetch_phase():
            from .backend import translate_chat_sync
            async def _fetch_only():
                from .backend import create_telegram_client, fetch_unread_messages, fetch_last_messages
                import io
                client = await create_telegram_client()
                try:
                    max_limit = msg_count if msg_count else 1000
                    if only_unread:
                        msgs = await fetch_unread_messages(client, chat, max_limit)
                    else:
                        msgs = await fetch_last_messages(client, chat, max_limit)
                    photo_map = {}
                    for m in msgs:
                        if m.photo:
                            try:
                                buf = io.BytesIO()
                                await client.download_media(m, buf)
                                buf.seek(0)
                                photo_map[m.id] = buf.read()
                            except Exception:
                                photo_map[m.id] = None
                    return msgs, photo_map
                finally:
                    await client.disconnect()

            import asyncio
            loop = asyncio.new_event_loop()
            try:
                raw_msgs, photo_map = loop.run_until_complete(_fetch_only())
            except Exception as err:
                self.after(0, lambda err=err: self._on_translate_error(err))
                return
            if not raw_msgs:
                self.after(0, lambda: self.footer_label.configure(text=_("translate.no_new")))
                self.after(0, lambda: self.progress_bar.set(1))
                return
            total = len(raw_msgs)


            # Group consecutive photo-only messages into single message
            grouped_msgs = []
            i = 0
            while i < len(raw_msgs):
                if raw_msgs[i].photo and not raw_msgs[i].text:
                    photos = [raw_msgs[i]]
                    j = i + 1
                    while j < len(raw_msgs) and raw_msgs[j].photo and not raw_msgs[j].text:
                        photos.append(raw_msgs[j])
                        j += 1
                    # Merge into one message with multiple photos
                    if len(photos) > 1:
                        merged = photos[0]
                        merged._extra_photos = photos[1:]
                        grouped_msgs.append(merged)
                        i = j
                        continue
                grouped_msgs.append(raw_msgs[i])
                i += 1
            raw_msgs = grouped_msgs
            total = len(raw_msgs)

            for i, msg in enumerate(raw_msgs):
                minfo = MessageInfo(msg, "")
                self._raw_msg_map[msg.id] = msg
                minfo.text = msg.text or ""
                extra = getattr(msg, "_extra_photos", None)
                if extra:
                    minfo.media_type = "Photo"
                elif msg.video:
                    dur = msg.video.duration if hasattr(msg.video, "duration") and msg.video.duration else ""
                    minfo.media_type = f"Video ({dur}s)" if dur else "Video"
                elif msg.photo:
                    minfo.media_type = "Photo"
                elif msg.voice:
                    dur = msg.voice.duration if hasattr(msg.voice, "duration") and msg.voice.duration else ""
                    minfo.media_type = f"Voice ({dur}s)" if dur else "Voice"
                elif msg.document:
                    minfo.media_type = "Document"
                elif msg.sticker:
                    minfo.media_type = "Sticker"
                else:
                    minfo.media_type = "Media"
                if extra:
                    photos = [photo_map.get(msg.id)] + [photo_map.get(m.id) for m in extra if m.photo]
                    photos = [p for p in photos if p]
                    self.after(0, lambda m=minfo, pbs=photos: self._add_bubble(m, pbs))
                elif msg.photo:
                    pb = photo_map.get(msg.id)
                    self.after(0, lambda m=minfo, pb=pb: self._add_bubble(m, pb))
                else:
                    self.after(0, lambda m=minfo: self._add_bubble(m))
                if i % 3 == 0:
                    self.after(0, lambda p=(i + 1) / total: self.progress_bar.set(p))

            self.after(0, lambda: self.footer_label.configure(text=_("translate.translating", count=total, model=MODEL)))
            from .backend import translate_messages
            try:
                translations = translate_messages(raw_msgs, api_key, MODEL, progress_callback=lambda n, t: self.after(0, lambda: self.progress_bar.set(n / t)))
            except Exception as err:
                self.after(0, lambda err=err: self._show_translate_error(err, MODEL))
                return
            self._translated_msgs = translations
            for i, minfo in enumerate(translations):
                t = minfo.translation
                self.after(0, lambda idx=i, t=t: self._update_bubble_translation(idx, t))
            total_chars = sum(len(m.text or "") for m in raw_msgs)
            est_cost = (total_chars / 4 / 1000) * 0.00015
            self.after(0, lambda: self.footer_label.configure(text=_("translate.done", count=total, cost=est_cost, model=MODEL)))
            self.after(0, lambda: self.progress_bar.set(1))
            self.after(0, lambda: self.mark_read_btn.configure(state="normal"))
            self.after(0, lambda: self.copy_btn.configure(state="normal"))
            self.after(0, lambda: self._set_retranslate_state("normal"))

        threading.Thread(target=_fetch_phase, daemon=True).start()

    def _do_summary(self, chat, msg_count, only_unread=True) -> None:
        self._current_chat = chat
        self.tab_view.set(_("tab.summary"))
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", _("summary.running", chat=chat.name) + "\n")
        self.footer_label.configure(text=_("summary.running", chat=chat.name))
        status = _("translate.status_unread", count=chat.unread_count) if only_unread else _("translate.status_msgs", count=msg_count)
        self.summary_header.configure(text=_("translate.header_title", chat=chat.name, status=status))

        def _run():
            try:
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    self.after(0, lambda: (self.summary_progress.stop(), self.summary_progress.set(0), self.summary_progress.configure(mode="determinate"), self.summary_text.configure(state="normal"), self.summary_text.delete("1.0", "end"), _insert_with_links(self.summary_text, _("error.env_missing")), self.summary_text.configure(state="disabled"), self.footer_label.configure(text=_("summary.failed"))))
                    return
                digest, count = summarize_chat_sync(
                    chat,
                    api_key,
                    max_msgs=msg_count or MAX_PER_CHAT,
                    only_unread=only_unread,
                    progress_callback=lambda done, total: self.after(
                        0, lambda: (self.summary_progress.configure(mode="determinate"), self.summary_progress.set(done / total if total else 1), self.summary_progress.configure(maximum=1))
                    ),
                )
                display = digest if digest else _("summary.empty")
                self.after(0, lambda: (self.summary_progress.stop(), self.summary_progress.set(1), self.summary_progress.configure(mode="determinate"), self.summary_text.configure(state="normal"), self.summary_text.delete("1.0", "end"), _insert_with_links(self.summary_text, display), self.summary_text.configure(state="disabled"), self.footer_label.configure(text=_("summary.done")), self.summary_mark_read_btn.configure(state="normal")))
            except Exception as e:
                self.after(0, lambda err=str(e): (self.summary_progress.stop(), self.summary_progress.set(0), self.summary_progress.configure(mode="determinate"), self.summary_text.configure(state="normal"), self.summary_text.delete("1.0", "end"), _insert_with_links(self.summary_text, f"Error:\n{err}\n"), self.summary_text.configure(state="disabled"), self.footer_label.configure(text=_("summary.failed"))))

        self.summary_progress.configure(mode="indeterminate")
        self.summary_progress.start()
        threading.Thread(target=_run, daemon=True).start()

    def _select_chat(self, chat_id: int) -> None:
        """Highlight a chat item and deselect others."""
        is_dark = ctk.get_appearance_mode() == "Dark"
        sel_bg = "#5EB5F7" if not is_dark else "#3B8ED0"
        norm_bg = "transparent"
        for item in self._chat_items:
            if getattr(item, 'cid', None) == chat_id:
                item.configure(fg_color=sel_bg)
            else:
                item.configure(fg_color=norm_bg)
        self._selected_chat_id = chat_id

    def _filter_chats(self, event=None) -> None:
        """Filter the chat list by search text."""
        query = self.chat_search_var.get().lower()
        src = getattr(self, "_all_chats", self.chats)
        for item in self._chat_items:
            cid = getattr(item, 'cid', None)
            chat = next((c for c in src if c.id == cid), None)
            if chat and (not query or query in chat.name.lower()):
                item.pack(fill="x", padx=4, pady=2)
            else:
                item.pack_forget()

    def _clear_bubbles(self) -> None:
        """Destroy all bubbles in both columns."""
        for left, right, _, _ in self._msg_frames:
            left.destroy()
            right.destroy()
        self._msg_frames.clear()
        self._photo_refs.clear()

    def _make_bubble(self, parent, row):
        """Create an empty bubble frame in the given scrollable frame at row."""
        is_dark = ctk.get_appearance_mode() == "Dark"
        bg = "#2a2a2a" if is_dark else "#e8e8e8"
        bd = "#3a3a3a" if is_dark else "#d0d0d0"
        bubble = ctk.CTkFrame(parent, fg_color=bg, corner_radius=BUBBLE_RADIUS,
                              border_width=1, border_color=bd)
        bubble.grid(row=row, column=0, sticky="ew", padx=BUBBLE_PAD, pady=(0, BUBBLE_PAD))
        bubble.grid_columnconfigure(0, weight=1)
        return bubble, bg

    def _fill_left_bubble(self, bubble, bg, minfo: MessageInfo, photos=None):
        """Fill a left-column bubble with header, photo, and original text."""
        row_idx = 0
        hdr_fg = "#aaaaaa" if ctk.get_appearance_mode() == "Dark" else "#666666"
        ctk.CTkLabel(
            bubble, text=f"{minfo.sender} · {minfo.date}",
            font=("", 10), text_color=hdr_fg,
        ).grid(row=row_idx, column=0, sticky="w", padx=10, pady=(6, 0))
        row_idx += 1

        # Photos (single or list)
        if isinstance(photos, list):
            for pb in photos:
                if pb:
                    photo = _photo_from_bytes(pb)
                    if photo:
                        self._photo_refs.append(photo)
                        img_label = ctk.CTkLabel(bubble, image=photo, text="", cursor="hand2")
                        img_label.grid(row=row_idx, column=0, sticky="w", padx=10, pady=(2, 2))
                        img_label.bind("<Button-1>", lambda e, pb=pb: self._show_image_viewer(pb))
                        row_idx += 1
        elif photos:
            photo = _photo_from_bytes(photos)
            if photo:
                self._photo_refs.append(photo)
                img_label = ctk.CTkLabel(bubble, image=photo, text="", cursor="hand2")
                img_label.grid(row=row_idx, column=0, sticky="w", padx=10, pady=(4, 0))
                img_label.bind("<Button-1>", lambda e, pb=photos: self._show_image_viewer(pb))
                row_idx += 1
        elif minfo.media_type:
            ctk.CTkLabel(
                bubble, text=f"[{minfo.media_type}]",
                font=("", 11), text_color="#888888",
            ).grid(row=row_idx, column=0, sticky="w", padx=10, pady=(4, 0))
            row_idx += 1
            # Video play button
            if "Video" in minfo.media_type:
                play_btn = ctk.CTkButton(
                    bubble, text="▶️ " + _("video.play"),
                    font=("", 11), width=100, height=28,
                    command=lambda mid=minfo.id: self._play_video_file(mid),
                )
                play_btn.grid(row=row_idx, column=0, sticky="w", padx=10, pady=(2, 0))
                row_idx += 1

        # Original text
        text_to_show = minfo.text or getattr(minfo, '_caption', '')
        if text_to_show:
            txt = Text(bubble, wrap="word", font=("TkDefaultFont", 12),
                       relief="flat", borderwidth=0, highlightthickness=0, takefocus=0, width=1, height=1, bg=bg, padx=5, pady=2)
            txt.grid(row=row_idx, column=0, sticky="ew", padx=10, pady=(2, 2))
            _apply_formatting(txt, text_to_show)
            _add_context_menu(txt)
            txt.update_idletasks()
            lines = txt.count("1.0", "end", "displaylines")[0] or 1
            txt.configure(height=int(lines) + 1, state="disabled")

        # ── Reaction bar (left bubble) ──
        self._add_reaction_bar(bubble, row_idx + 1, minfo.id)

    _REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "😡", "🎉"]
    _ALL_REACTIONS = [
        "👍", "❤️", "😂", "😮", "😢", "😡", "🎉",
        "👎", "🔥", "💯", "🙏", "🥰", "🤣", "💔", "🕊️", "⚡",
    ]

    def _add_reaction_bar(self, parent, row, msg_id: int) -> None:
        """Add a row of reaction emoji buttons + ⋯ for more."""
        chat_id = self._current_chat.id if self._current_chat else 0
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=row, column=0, sticky="w", padx=10, pady=(4, 6))
        for emoji in self._REACTIONS:
            btn = ctk.CTkButton(
                bar, text=emoji, width=32, height=28, font=("", 12),
                command=lambda c=chat_id, m=msg_id, r=emoji: self._on_reaction(c, m, r),
            )
            btn.pack(side="left", padx=1)
        # "More" button
        ctk.CTkButton(
            bar, text="⋯", width=28, height=28, font=("", 14),
            command=lambda c=chat_id, m=msg_id: self._show_more_reactions(c, m),
        ).pack(side="left", padx=2)

    def _on_reaction(self, chat_id: int, msg_id: int, reaction: str) -> None:
        """Send a reaction to Telegram in a background thread."""
        def _work():
            try:
                send_reaction_sync(chat_id, msg_id, reaction)
            except Exception as e:
                err = str(e)
                self.after(0, lambda err=err: _ctk_dialog(_("error.dialog_title"), err, parent=self))
        threading.Thread(target=_work, daemon=True).start()

    def _show_more_reactions(self, chat_id: int, msg_id: int) -> None:
        """Open a popup with all available reaction emoji."""
        top = ctk.CTkToplevel(self)
        top.title("")
        top.geometry("420x100")
        top.resizable(False, False)
        top.attributes("-topmost", True)
        # Position near cursor
        try:
            x = self.winfo_pointerx() - 200
            y = self.winfo_pointery() - 50
            top.geometry(f"+{x}+{y}")
        except Exception:
            pass
        frame = ctk.CTkFrame(top, fg_color="transparent")
        frame.pack(padx=10, pady=10)
        for i, emoji in enumerate(self._ALL_REACTIONS):
            btn = ctk.CTkButton(
                frame, text=emoji, width=36, height=32, font=("", 14),
                command=lambda r=emoji: (self._on_reaction(chat_id, msg_id, r), top.destroy()),
            )
            btn.grid(row=i // 6, column=i % 6, padx=2, pady=2)

    def _fill_right_bubble(self, bubble, bg, translation: str, photo_bytes=None, msg_id=0):
        """Fill a right-column bubble with translation text (or placeholder) + photo."""
        row_idx = 0

        # Photo (same as left if present)
        if photo_bytes:
            photo = _photo_from_bytes(photo_bytes)
            if photo:
                self._photo_refs.append(photo)
                img_label = ctk.CTkLabel(bubble, image=photo, text="", cursor="hand2")
                img_label.grid(row=row_idx, column=0, sticky="w", padx=10, pady=(4, 0))
                img_label.bind("<Button-1>", lambda e, pb=photo_bytes: self._show_image_viewer(pb))
                row_idx += 1

        if translation and translation.strip() not in ("ήδη Ελληνικά", ""):
            txt = Text(bubble, wrap="word", font=("TkDefaultFont", 12),
                       relief="flat", borderwidth=0, highlightthickness=0, takefocus=0, width=1, height=1, bg=bg, padx=5, pady=2)
            txt.grid(row=row_idx, column=0, sticky="ew", padx=10, pady=(6, 6))
            _apply_formatting(txt, translation)
            _add_context_menu(txt)
            txt.update_idletasks()
            lines = txt.count("1.0", "end", "displaylines")[0] or 1
            txt.configure(height=int(lines) + 1, state="disabled")
        elif not photo_bytes:
            # Only show placeholder if it's truly pending (no photo, no translation)
            ctk.CTkLabel(
                bubble, text=_("translate.pending"),
                font=("", 12, "italic"), text_color="#888888",
            ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 10))
        # ── Reaction bar (right bubble) ──
        self._add_reaction_bar(bubble, row_idx + 1, msg_id)

    def _add_bubble(self, minfo: MessageInfo, photo_bytes: bytes | None = None, pbs: list | None = None) -> None:
        """Create a pair of bubbles: left = original, right = translation (pending)."""
        pb = pbs or photo_bytes
        row = len(self._msg_frames)

        left_bubble, left_bg = self._make_bubble(self.left_scroll, row)
        self._fill_left_bubble(left_bubble, left_bg, minfo, pb)

        right_bubble, right_bg = self._make_bubble(self.right_scroll, row)
        self._fill_right_bubble(right_bubble, right_bg, "", msg_id=minfo.id)

        self._msg_frames.append((left_bubble, right_bubble, minfo, pb))

    def _update_bubble_translation(self, idx: int, translation: str) -> None:
        if idx >= len(self._msg_frames):
            return
        _, right_bubble, minfo, photo_bytes = self._msg_frames[idx]
        for child in right_bubble.winfo_children():
            child.destroy()
        is_dark = ctk.get_appearance_mode() == "Dark"
        bg = "#2a2a2a" if is_dark else "#e8e8e8"
        self._fill_right_bubble(right_bubble, bg, translation, photo_bytes, msg_id=minfo.id)
    def load_chats(self) -> None:
        self.status_label.configure(text=_("app.loading"))
        self.footer_label.configure(text=_("app.loading"))

        def _work():
            try:
                chats = list_chats_sync(only_unread=False)
                self.after(0, self._on_chats_loaded, chats, None)
            except Exception as e:
                self.after(0, self._on_chats_loaded, None, e)

        threading.Thread(target=_work, daemon=True).start()

    def _on_chats_loaded(self, chats, error):
        if error:
            if self._handle_startup_error(error):
                return
            _ctk_dialog(_("error.dialog_title"), str(error), parent=self)
            self.footer_label.configure(text=str(error), image=get("error", size=14), compound="left")
            return
        self.chats = chats or []
        self._all_chats = self.chats
        self._selected_chat_id = None
        self._populate_chat_tree()

    def _handle_startup_error(self, error) -> bool:
        """Open settings/login when the failure is a setup problem.

        Returns True when a recovery flow was started (it reloads the chats
        itself on success); False when the error should be shown as-is.
        """
        if isinstance(error, NotAuthorizedError):
            self._start_login_flow()
            return True
        ok, _msg = check_env()
        if not ok:
            if not getattr(self, "_recovery_open", False):
                self._prompt_settings_then_reload()
            return True
        return False

    def _start_login_flow(self) -> None:
        """Open the QR/SMS login window; reload chats when login succeeds."""
        from .login_window import run_login_flow

        self.status_label.configure(text=_("login.title"))
        if run_login_flow(parent=self):
            self.load_chats()
        else:
            self.footer_label.configure(
                text=_("error.not_authorized"), image=get("error", size=14), compound="left")

    def _prompt_settings_then_reload(self) -> None:
        """First-run flow: ask for API keys, then log in, then load chats."""
        if getattr(self, "_recovery_open", False):
            return
        self._recovery_open = True
        try:
            dialog = SettingsDialog(self)
            dialog.grab_set()
            self.wait_window(dialog)
            ok, _msg = check_env()
            if not ok:
                _ctk_dialog(_("error.dialog_title"), _("error.env_missing"), parent=self)
                self.footer_label.configure(
                    text=_("error.env_missing"), image=get("error", size=14), compound="left")
                return
            if not is_authorized_sync():
                self._start_login_flow()
                return
            self.load_chats()
        finally:
            self._recovery_open = False

    def _get_selected_chat(self) -> ChatInfo | None:
        if self._selected_chat_id is None:
            _ctk_dialog(_("chats.select_title"), _("chats.select_hint"), parent=self)
            return None
        src = getattr(self, "_all_chats", self.chats)
        for c in src:
            if c.id == self._selected_chat_id:
                return c
        return None

    def translate_selected(self) -> None:
        """Show translate filter dialog, then translate."""
        chat = self._get_selected_chat()
        if not chat:
            return
        self._show_translate_dialog(chat)

    def _on_translate_error(self, error) -> None:
        if isinstance(error, NotAuthorizedError):
            self._start_login_flow()
            return
        self.footer_label.configure(text=str(error), image=get("error", size=14), compound="left")

    def _show_translate_error(self, error, model: str = "") -> None:
        """Show the API error in the footer and re-enable retranslation."""
        detail = str(error).strip() or error.__class__.__name__
        self.footer_label.configure(
            text=_("translate.failed", model=model or MODEL, error=detail),
            image=get("error", size=14),
            compound="left",
        )
        self._set_retranslate_state("normal")

    def _set_retranslate_state(self, state: str) -> None:
        for child in self.tab_translate.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                for btn in child.winfo_children():
                    if isinstance(btn, ctk.CTkButton) and getattr(btn, '_is_retranslate', False):
                        btn.configure(state=state)

    def _update_all_bubbles(self, new_msgs: list) -> None:
        """Update right bubbles with new translations after retranslate."""
        for i, (left_bubble, right_bubble, old_minfo, pb) in enumerate(self._msg_frames):
            if i < len(new_msgs):
                new_minfo = new_msgs[i]
                for child in right_bubble.winfo_children():
                    child.destroy()
                is_dark = ctk.get_appearance_mode() == "Dark"
                bg = "#2a2a2a" if is_dark else "#e8e8e8"
                self._fill_right_bubble(right_bubble, bg, new_minfo.translation, pb, msg_id=new_minfo.id)
                self._msg_frames[i] = (left_bubble, right_bubble, new_minfo, pb)

    def retranslate(self) -> None:
        """Re-translate already-loaded messages without fetching new ones."""
        if not self._msg_frames or not self._current_chat:
            return
        raw_msgs = []
        for _, _, minfo, _ in self._msg_frames:
            raw = self._raw_msg_map.get(minfo.id)
            if raw:
                raw_msgs.append(raw)
        if not raw_msgs:
            return
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            _ctk_dialog(_("error.dialog_title"), _("error.api_key_not_found"), parent=self)
            return
        model = os.environ.get("TRANSLATE_MODEL", MODEL)
        self.mark_read_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self._set_retranslate_state("disabled")
        self.progress_bar.set(0)
        self.footer_label.configure(text=_("translate.translating", count=len(raw_msgs), model=model))

        def _work():
            try:
                from .backend import translate_messages
                new_msgs = translate_messages(raw_msgs, api_key, model)
                self.after(0, lambda: self._update_all_bubbles(new_msgs))
                self.after(0, lambda: self.progress_bar.set(1))
                self.after(0, lambda: self.footer_label.configure(text=_("translate.done", count=len(new_msgs), cost=0, model=model)))
                self.after(0, lambda: self._set_retranslate_state("normal"))
            except Exception as e:
                self.after(0, lambda e=e: self._show_translate_error(e, model))
        threading.Thread(target=_work, daemon=True).start()

    def summary_selected(self) -> None:
        """Show summary filter dialog, then summarize."""
        chat = self._get_selected_chat()
        if not chat:
            return
        self._show_summary_dialog(chat)

    def mark_current_read(self) -> None:
        if not hasattr(self, "_translated_msgs") or not self._translated_msgs or not self._current_chat:
            return
        last_id = self._translated_msgs[-1].id

        def _work():
            try:
                mark_read_sync(self._current_chat, last_id)
                self.after(0, self._on_marked_read)
            except Exception as e:
                self.after(0, lambda e=str(e): _ctk_dialog(_("error.dialog_title"), e, parent=self))

        threading.Thread(target=_work, daemon=True).start()

    def _on_marked_read(self) -> None:
        self.footer_label.configure(text=_("translate.mark_read_ok"))
        self.mark_read_btn.configure(state="disabled")
        self.after(500, self.load_chats)

    def summary_mark_read(self) -> None:
        """Mark the summarized chat as read."""
        from .backend import mark_read_sync
        if hasattr(self, "_current_chat") and self._current_chat:
            try:
                mark_read_sync(self._current_chat, 0)
                self.footer_label.configure(text=_("translate.mark_read_ok"))
                self.summary_mark_read_btn.configure(state="disabled")
            except Exception as e:
                _ctk_dialog(_("error.dialog_title"), str(e), parent=self)

    def copy_translations(self) -> None:
        """Copy all translations from right-column bubbles."""
        texts = []
        for _, right_bubble, _, _ in self._msg_frames:
            for child in right_bubble.winfo_children():
                if isinstance(child, (Text, ctk.CTkTextbox)):
                    texts.append(child.get("1.0", "end-1c"))
        text = "\n".join(texts)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.footer_label.configure(text=_("translate.copied"))

    # ── Settings ─────────────────────────────────────────────────────


    def _show_image_viewer(self, photo_bytes: bytes) -> None:
        """Open a popup window with the full-size image."""
        if not photo_bytes:
            return
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(photo_bytes))
            w, h = img.size
            # Scale to fit screen if too large (max 90% of screen)
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            max_w = int(screen_w * 0.85)
            max_h = int(screen_h * 0.85)
            if w > max_w or h > max_h:
                ratio = min(max_w / w, max_h / h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

            viewer = ctk.CTkToplevel(self)
            viewer.title(_("image_viewer.title"))
            viewer.geometry(f"{img.size[0] + 40}x{img.size[1] + 60}")
            viewer.minsize(200, 200)

            ctk_img = ctk.CTkImage(img, size=img.size)
            viewer._ctk_img = ctk_img

            label = ctk.CTkLabel(viewer, image=ctk_img, text="")
            label.pack(padx=10, pady=10, fill="both", expand=True)

            close_btn = ctk.CTkButton(viewer, text=_("image_viewer.close"), image=get("close"),
                                       command=viewer.destroy, width=80)
            close_btn.pack(pady=(0, 10))
        except Exception as e:
            _ctk_dialog(_("error.dialog_title"), _("image_viewer.error_msg", error=str(e)), parent=self)

    # ── Video player ──────────────────────────────────────────────────

    def _play_video_file(self, msg_id: int) -> None:
        """Download and play a video from a message in a new VLC window."""
        raw = self._raw_msg_map.get(msg_id)
        if not raw:
            _ctk_dialog(_("error.dialog_title"), _("video.msg_not_found"), parent=self)
            return

        def _work():
            try:
                path = download_video_sync(raw)
                if path:
                    self.after(0, lambda: self._show_vlc_viewer(path))
                else:
                    self.after(0, lambda: _ctk_dialog(_("error.dialog_title"), _("video.download_failed"), parent=self))
            except Exception as e:
                self.after(0, lambda: _ctk_dialog(_("error.dialog_title"), str(e), parent=self))

        threading.Thread(target=_work, daemon=True).start()

    def _show_vlc_viewer(self, video_path: str) -> None:
        """Open a popup window with embedded VLC video player."""
        if vlc is None:
            _ctk_dialog(_("error.dialog_title"), _("video.vlc_not_found"), parent=self)
            return

        top = ctk.CTkToplevel(self)
        top.title(_("video.viewer_title"))
        top.geometry("800x600")
        top.minsize(400, 300)

        instance = vlc.Instance("--no-video-title-show")
        player = instance.media_player_new()
        media = instance.media_new(video_path)
        player.set_media(media)

        # Use a plain Tk Frame (not CTkFrame) for native X window handle
        video_frame = TkFrame(top, bg="black")
        video_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Ensure the window is fully mapped before getting its XID
        top.update_idletasks()

        if sys.platform.startswith("linux"):
            player.set_xwindow(video_frame.winfo_id())
        elif sys.platform == "win32":
            player.set_hwnd(video_frame.winfo_id())
        elif sys.platform == "darwin":
            player.set_nsobject(int(video_frame.winfo_id()))

        player.play()

        # ── Control bar ──
        ctrl = ctk.CTkFrame(top, fg_color="transparent")
        ctrl.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(ctrl, text="⏸", width=40,
                      command=lambda: player.pause() if player.is_playing() else player.play()
                      ).pack(side="left", padx=2)
        ctk.CTkButton(ctrl, text="⏹", width=40,
                      command=lambda: (player.stop(), top.destroy())
                      ).pack(side="left", padx=2)
        ctk.CTkButton(ctrl, text=_("video.close"), command=top.destroy).pack(side="right", padx=5)

        def _cleanup():
            player.stop()
            top.destroy()
        top.protocol("WM_DELETE_WINDOW", _cleanup)
        self._vlc_players.append(player)

    def _rebuild_ui(self) -> None:
        """Rebuild main window after language change — destroy & recreate all."""
        # Save current chat selection
        saved_chat = self._current_chat
        # Destroy all widgets inside main_frame
        for w in self.main_frame.winfo_children():
            w.destroy()
        # Rebuild everything (same order as __init__)
        self._build_header()
        self._build_tabs()
        self._build_footer()
        # Restore chat selection
        self._current_chat = saved_chat
        # Reload chat list
        self.load_chats()

    def open_settings(self) -> None:
            dialog = SettingsDialog(self)
            dialog.grab_set()

    def _on_configure(self, event=None) -> None:
        # <Configure> on the root also fires for every child widget (Tk bindtags
        # include the toplevel), so ignore anything that isn't the window itself.
        if event is not None and event.widget is not self:
            return
        # Debounce: only persist once the window has stopped moving/resizing.
        if self._geometry_save_after_id is not None:
            self.after_cancel(self._geometry_save_after_id)
        self._geometry_save_after_id = self.after(500, self._save_geometry_now)

    def _save_geometry_now(self) -> None:
        self._geometry_save_after_id = None
        try:
            save_window_geometry(self.geometry())
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_geometry_now()
        self.destroy()

    def run(self) -> None:
        self.mainloop()


# ── Settings Dialog ─────────────────────────────────────────────────────


class SettingsDialog(ctk.CTkToplevel):
    """Settings window."""

    def __init__(self, parent: App) -> None:
        super().__init__(parent)
        self.parent = parent
        self.title(_("settings.title"))
        self.geometry("500x500")
        self.resizable(False, False)

        self.current_api_id = os.environ.get("TG_API_ID", "")
        self.current_api_hash = os.environ.get("TG_API_HASH", "")
        self.current_openai = os.environ.get("OPENAI_API_KEY", "")
        self.current_model = os.environ.get("TRANSLATE_MODEL", MODEL)

        self.current_lang = get_language()

        self._build_ui()

        # fitting
        self.update_idletasks()
        need = self.winfo_reqheight()
        if need > 500:
            self.geometry(f"500x{min(need + 40, 800)}")

    def _on_lang_change(self, choice: str) -> None:
        """αλλαγή γλώσσας αμέσως"""
        code = self._lang_map.get(choice, choice)
        set_language(code)
        self.current_lang = get_language()
        if hasattr(self, 'parent') and hasattr(self.parent, '_rebuild_ui'):
            self.parent._rebuild_ui()
        self.title(_("settings.title"))
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()

    def _build_ui(self) -> None:
        base_pad = {"padx": 20, "pady": 6}

        ctk.CTkLabel(self, text=_("settings.telegram"), font=("", 14, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 5))

        ctk.CTkLabel(self, text=_("settings.api_id")).grid(row=1, column=0, sticky="e", **base_pad)
        self.api_id_entry = ctk.CTkEntry(self, width=300, show="*")
        self.api_id_entry.insert(0, self.current_api_id)
        self.api_id_entry.grid(row=1, column=1, sticky="w", **base_pad)

        ctk.CTkLabel(self, text=_("settings.api_hash")).grid(row=2, column=0, sticky="e", **base_pad)
        self.api_hash_entry = ctk.CTkEntry(self, width=300, show="*")
        self.api_hash_entry.insert(0, self.current_api_hash)
        self.api_hash_entry.grid(row=2, column=1, sticky="w", **base_pad)

        ctk.CTkLabel(self, text=_("settings.openai"), font=("", 14, "bold")).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 5))

        ctk.CTkLabel(self, text=_("settings.api_key")).grid(row=4, column=0, sticky="e", **base_pad)
        self.openai_entry = ctk.CTkEntry(self, width=300, show="*")
        self.openai_entry.insert(0, self.current_openai)
        self.openai_entry.grid(row=4, column=1, sticky="w", **base_pad)

        ctk.CTkLabel(self, text=_("settings.translation"), font=("", 14, "bold")).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 5))

        ctk.CTkLabel(self, text=_("settings.model")).grid(row=6, column=0, sticky="e", **base_pad)
        self.model_combo = ctk.CTkComboBox(
            self, values=["gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o-mini", "gpt-5.4-mini"], width=200)
        self.model_combo.set(self.current_model)
        self.model_combo.grid(row=6, column=1, sticky="w", **base_pad)

        # ── Language ──
        ctk.CTkLabel(self, text=_("settings.lang_section"), font=("", 14, "bold")).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 5))
        lang_list = available_languages()
        # Map display name -> language code
        self._lang_map = {name: code for code, name in lang_list}
        lang_names = list(self._lang_map.keys())
        ctk.CTkLabel(self, text=_("settings.language")).grid(row=8, column=0, sticky="e", **base_pad)
        # Find current name from current code
        current_name = next((n for c, n in lang_list if c == self.current_lang), lang_names[0])
        def _on_lang(val):
            self._on_lang_change(val)
        self.lang_combo = ctk.CTkOptionMenu(self, values=lang_names, width=200, command=_on_lang)
        self.lang_combo.set(current_name)
        self.lang_combo.grid(row=8, column=1, sticky="w", **base_pad)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=9, column=0, columnspan=2, pady=(12, 4))
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(btn_frame, text=_("settings.save"), command=self.save).grid(row=0, column=0, padx=10)
        ctk.CTkButton(
            btn_frame, text=_("settings.my_telegram"), image=get("link"),
            command=lambda: webbrowser.open("https://my.telegram.org"),
        ).grid(row=0, column=1, padx=10)

        # version indicator
        ctk.CTkLabel(self, text=f"v{APP_VERSION}", font=("", 10), text_color="#888888").grid(
            row=10, column=0, columnspan=2, pady=(2, 10))

    def save(self) -> None:
        env_path = APP_ENV_PATH
        lines = [
            f"TG_API_ID={self.api_id_entry.get()}",
            f"TG_API_HASH={self.api_hash_entry.get()}",
            f"OPENAI_API_KEY={self.openai_entry.get()}",
            f"TRANSLATE_MODEL={self.model_combo.get()}",
            f"LANGUAGE={self._lang_map.get(self.lang_combo.get(), self.lang_combo.get())}",
        ]
        try:
            env_path.parent.mkdir(parents=True, exist_ok=True)
            with open(env_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            try:
                os.chmod(env_path, 0o600)  # τα .env να μην είναι readable από άλλους
            except Exception:
                pass
            os.environ["TG_API_ID"] = self.api_id_entry.get()
            os.environ["TG_API_HASH"] = self.api_hash_entry.get()
            os.environ["OPENAI_API_KEY"] = self.openai_entry.get()
            os.environ["TRANSLATE_MODEL"] = self.model_combo.get()
            os.environ["LANGUAGE"] = self._lang_map.get(self.lang_combo.get(), self.lang_combo.get())
            self.destroy()
        except Exception as e:
            _ctk_dialog(_("error.dialog_title"), _("settings.save_error_msg", error=str(e)), parent=self)


# ── Entry point ─────────────────────────────────────────────────────────


def main() -> None:
    ok, msg = check_env()
    if not ok:
        print(_("main.env_hint", msg=msg))
    elif not is_authorized_sync():
        from .login_window import run_login_flow
        if not run_login_flow():
            return

    app = App()
    app.run()


if __name__ == "__main__":
    main()
