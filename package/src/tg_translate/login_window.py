"""
tg-translate — first-run Telegram authentication window (QR code + SMS).
"""

from __future__ import annotations

import os
import threading

import customtkinter as ctk

from .i18n import _
from .backend import LoginSession

ctk.set_appearance_mode("system")
ctk.set_default_color_theme(os.path.join(os.path.dirname(__file__), "assets", "theme.json"))


def _login_dialog(title: str, message: str, parent=None) -> None:
    dlg = ctk.CTkToplevel(parent) if parent else ctk.CTkToplevel()
    dlg.title(title)
    dlg.geometry("420x180")
    dlg.resizable(False, False)
    if parent:
        try:
            x = parent.winfo_rootx() + parent.winfo_width() // 2 - 210
            y = parent.winfo_rooty() + parent.winfo_height() // 2 - 90
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass
    dlg.transient(parent)
    dlg.update_idletasks()
    dlg.grab_set()
    ctk.CTkLabel(dlg, text=message, wraplength=380, font=("", 13)).pack(pady=25, padx=20)
    ctk.CTkButton(dlg, text=_("dialog.ok"), width=80, command=dlg.destroy).pack(pady=10)
    if parent:
        parent.wait_window(dlg)


class LoginWindow(ctk.CTk):
    """First-run Telegram login window: QR code or SMS login."""

    QR_SIZE = 260

    def __init__(self) -> None:
        super().__init__()
        ctk.set_widget_scaling(1.1)

        self.title(_("login.title"))
        w, h = 440, 580
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        try:
            from tkinter import PhotoImage
            icon_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
            if os.path.exists(icon_path):
                self.iconphoto(True, PhotoImage(file=icon_path))
        except Exception:
            pass

        self.result = False
        self._closed = False
        self.session = LoginSession()
        self._qr_ctk_image = None  # so to keep alive and avoid GC

        self._build_ui()
        threading.Thread(target=self._connect_then_start, daemon=True).start()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        ctk.CTkLabel(self, text=_("login.title"), font=("", 20, "bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self, text=_("login.subtitle"), font=("", 12), text_color="#888888").pack(pady=(0, 10))

        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.pack(fill="both", expand=True, padx=20, pady=10)
        self.tab_qr = self.tab_view.add(_("login.tab_qr"))
        self.tab_sms = self.tab_view.add(_("login.tab_sms"))

        self._build_qr_tab()
        self._build_sms_tab()

    def _build_qr_tab(self) -> None:
        self.tab_qr.grid_columnconfigure(0, weight=1)

        self.qr_image_label = ctk.CTkLabel(
            self.tab_qr, text=_("login.connecting"), width=self.QR_SIZE, height=self.QR_SIZE)
        self.qr_image_label.grid(row=0, column=0, pady=(15, 10))

        ctk.CTkLabel(self.tab_qr, text=_("login.qr_hint"), font=("", 12), wraplength=360, justify="left").grid(
            row=1, column=0, padx=10, pady=(0, 10))

        self.qr_status_label = ctk.CTkLabel(self.tab_qr, text="", font=("", 12))
        self.qr_status_label.grid(row=2, column=0, pady=(0, 10))

        # 2FA password step — hidden (not gridded) until the account needs it.
        self.qr_password_entry = ctk.CTkEntry(
            self.tab_qr, width=260, show="*", placeholder_text=_("login.sms_password_placeholder"))
        self.qr_password_entry.bind("<Return>", lambda e: self._submit_qr_password())
        self.qr_password_button = ctk.CTkButton(
            self.tab_qr, text=_("login.sms_confirm_password_button"), command=self._submit_qr_password)

    def _build_sms_tab(self) -> None:
        self.tab_sms.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.tab_sms, text=_("login.sms_phone_label"), font=("", 12)).grid(
            row=0, column=0, sticky="w", padx=10, pady=(20, 4))
        self.sms_phone_entry = ctk.CTkEntry(
            self.tab_sms, width=260, placeholder_text=_("login.sms_phone_placeholder"))
        self.sms_phone_entry.grid(row=1, column=0, padx=10, pady=(0, 10))
        self.sms_phone_entry.bind("<Return>", lambda e: self._submit_phone())

        self.sms_send_button = ctk.CTkButton(
            self.tab_sms, text=_("login.sms_send_button"), command=self._submit_phone, state="disabled")
        self.sms_send_button.grid(row=2, column=0, pady=(0, 20))

        # Code step — hidden until a code has been sent.
        self.sms_code_label = ctk.CTkLabel(self.tab_sms, text=_("login.sms_code_label"), font=("", 12))
        self.sms_code_entry = ctk.CTkEntry(
            self.tab_sms, width=260, placeholder_text=_("login.sms_code_placeholder"))
        self.sms_code_entry.bind("<Return>", lambda e: self._submit_code())
        self.sms_confirm_button = ctk.CTkButton(
            self.tab_sms, text=_("login.sms_confirm_button"), command=self._submit_code)

        # 2FA password step — hidden until Telegram asks for it.
        self.sms_password_label = ctk.CTkLabel(self.tab_sms, text=_("login.sms_password_label"), font=("", 12))
        self.sms_password_entry = ctk.CTkEntry(
            self.tab_sms, width=260, show="*", placeholder_text=_("login.sms_password_placeholder"))
        self.sms_password_entry.bind("<Return>", lambda e: self._submit_sms_password())
        self.sms_password_confirm_button = ctk.CTkButton(
            self.tab_sms, text=_("login.sms_confirm_password_button"), command=self._submit_sms_password)

        self.sms_status_label = ctk.CTkLabel(self.tab_sms, text="", font=("", 12))
        self.sms_status_label.grid(row=9, column=0, pady=(10, 10))

    # ── Background-thread helper ─────────────────────────────────────

    def _run_bg(self, fn, on_done) -> None:
        """Run fn() in a daemon thread; marshal (error, result) back via self.after."""
        def _work():
            try:
                result, error = fn(), None
            except Exception as e:
                result, error = None, e
            if not self._closed:
                self.after(0, on_done, error, result)
        threading.Thread(target=_work, daemon=True).start()

    def _show_error(self, error: Exception) -> None:
        _login_dialog(_("error.dialog_title"), _("login.error_generic", error=str(error)), parent=self)

    def _finish_success(self) -> None:
        """Disconnect the login client (so App's own client can reopen the session file) and close."""
        self.result = True
        try:
            self.session.close()
        except Exception:
            pass
        self.destroy()

    # ── Connection bootstrap ─────────────────────────────────────────

    def _connect_then_start(self) -> None:
        try:
            self.session.connect()
        except Exception as e:
            if not self._closed:
                self.after(0, self._show_error, e)
            return
        if not self._closed:
            self.after(0, self._on_connected)

    def _on_connected(self) -> None:
        self.sms_send_button.configure(state="normal")
        self._start_qr_flow()

    # ── QR flow ───────────────────────────────────────────────────────

    def _start_qr_flow(self) -> None:
        self.qr_status_label.configure(text=_("login.connecting"))
        self._run_bg(self.session.start_qr, self._on_qr_started)

    def _on_qr_started(self, error, url) -> None:
        if error:
            self._show_error(error)
            return
        self._render_qr(url)
        self._run_bg(lambda: self.session.qr_wait(timeout=25), self._on_qr_wait_result)

    def _render_qr(self, url: str) -> None:
        import qrcode
        img = qrcode.make(url).get_image().convert("RGB")
        self._qr_ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=(self.QR_SIZE, self.QR_SIZE))
        self.qr_image_label.configure(image=self._qr_ctk_image, text="")
        self.qr_status_label.configure(text=_("login.qr_waiting"))

    def _on_qr_wait_result(self, error, status) -> None:
        if self._closed:
            return
        if error:
            self._show_error(error)
            return
        if status == "ok":
            self._finish_success()
        elif status == "need_password":
            self.qr_status_label.configure(text="")
            self.qr_password_entry.grid(row=3, column=0, pady=(0, 10))
            self.qr_password_button.grid(row=4, column=0, pady=(0, 15))
        elif status == "timeout":
            self.qr_status_label.configure(text=_("login.qr_expired_refreshing"))
            self._run_bg(self.session.qr_recreate, self._on_qr_recreated)

    def _on_qr_recreated(self, error, url) -> None:
        if error:
            self._show_error(error)
            return
        self._render_qr(url)
        self._run_bg(lambda: self.session.qr_wait(timeout=25), self._on_qr_wait_result)

    def _submit_qr_password(self) -> None:
        pw = self.qr_password_entry.get()
        if not pw:
            return
        self.qr_password_button.configure(state="disabled")
        self._run_bg(lambda: self.session.sign_in_password(pw), self._on_qr_password_result)

    def _on_qr_password_result(self, error, _result) -> None:
        self.qr_password_button.configure(state="normal")
        if error:
            self._show_error(error)
            return
        self._finish_success()

    # ── SMS flow ──────────────────────────────────────────────────────

    def _submit_phone(self) -> None:
        phone = self.sms_phone_entry.get().strip()
        if not phone:
            return
        self.sms_send_button.configure(state="disabled")
        self.sms_status_label.configure(text=_("login.connecting"))
        self._run_bg(lambda: self.session.send_code(phone), self._on_code_sent)

    def _on_code_sent(self, error, _result) -> None:
        self.sms_send_button.configure(state="normal")
        self.sms_status_label.configure(text="")
        if error:
            self._show_error(error)
            return
        self.sms_code_label.grid(row=3, column=0, sticky="w", padx=10, pady=(6, 4))
        self.sms_code_entry.grid(row=4, column=0, padx=10, pady=(0, 10))
        self.sms_confirm_button.grid(row=5, column=0, pady=(0, 10))
        self.sms_code_entry.focus_set()

    def _submit_code(self) -> None:
        code = self.sms_code_entry.get().strip()
        if not code:
            return
        self.sms_confirm_button.configure(state="disabled")
        self._run_bg(lambda: self.session.sign_in_code(code), self._on_code_result)

    def _on_code_result(self, error, status) -> None:
        self.sms_confirm_button.configure(state="normal")
        if error:
            self._show_error(error)
            return
        if status == "ok":
            self._finish_success()
        elif status == "need_password":
            self.sms_password_label.grid(row=6, column=0, sticky="w", padx=10, pady=(6, 4))
            self.sms_password_entry.grid(row=7, column=0, padx=10, pady=(0, 10))
            self.sms_password_confirm_button.grid(row=8, column=0, pady=(0, 10))
            self.sms_password_entry.focus_set()

    def _submit_sms_password(self) -> None:
        pw = self.sms_password_entry.get()
        if not pw:
            return
        self.sms_password_confirm_button.configure(state="disabled")
        self._run_bg(lambda: self.session.sign_in_password(pw), self._on_sms_password_result)

    def _on_sms_password_result(self, error, _result) -> None:
        self.sms_password_confirm_button.configure(state="normal")
        if error:
            self._show_error(error)
            return
        self._finish_success()

    # ── Close ─────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        self._closed = True
        self.result = False
        threading.Thread(target=self.session.close, daemon=True).start()
        self.destroy()

    def destroy(self) -> None:
        self._closed = True
        super().destroy()


def run_login_flow() -> bool:
    """Show the login window (blocking) and return True if login succeeded."""
    win = LoginWindow()
    win.mainloop()
    return getattr(win, "result", False)
