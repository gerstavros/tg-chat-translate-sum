#!/usr/bin/env python3
"""Build a standalone executable for tg-chat-translate-sum using PyInstaller."""
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.join(PROJECT_ROOT, "package")
VENV_DIR = os.path.join(PACKAGE_DIR, ".venv")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "dist")
SPEC_FILE = os.path.join(PROJECT_ROOT, "tg-translate-sum.spec")

# Ensure running from the right directory
os.chdir(PROJECT_ROOT)

def build():
    entry = os.path.join(PROJECT_ROOT, "run.py")
    if not os.path.exists(entry):
        print(f"ERROR: entry point not found: {entry}")
        sys.exit(1)

    theme_dir = os.path.join(PACKAGE_DIR, "src", "tg_translate", "assets")
    locale_dir = os.path.join(PACKAGE_DIR, "src", "tg_translate", "locales")

    if not os.path.exists(theme_dir):
        print(f"ERROR: theme dir not found: {theme_dir}")
        sys.exit(1)

    cmd = [
        sys.executable or "python3", "-m", "PyInstaller",
        "--name", "tg-translate-sum",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        # CustomTkinter hidden imports & data
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-all", "customtkinter",
        "--collect-data", "customtkinter",
        # Ensure package src is in search path
        "--paths", os.path.join(PACKAGE_DIR, "src"),
        # Assets
        "--add-data", f"{theme_dir}{os.pathsep}tg_translate/assets",
        "--add-data", f"{locale_dir}{os.pathsep}tg_translate/locales",
        # Telethon etc
        "--hidden-import", "telethon",
        "--hidden-import", "cryptg",
        "--hidden-import", "socks",
        "--hidden-import", "openai",
        "--hidden-import", "dotenv",
        "--hidden-import", "vlc",
        # Icons (not sure if needed anymore as i added custom svg files in assets)
        "--hidden-import", "PIL",
        "--hidden-import", "cairosvg",
        # QR login
        "--hidden-import", "qrcode",
        # GUI
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.simpledialog",
        "--hidden-import", "tkinter.ttk",
        # IO
        "--hidden-import", "io",
        "--hidden-import", "re",
        "--hidden-import", "threading",
        "--hidden-import", "json",
        entry,
    ]

    print("=" * 60)
    print("Building tg-translate-sum executable with PyInstaller")
    print("=" * 60)
    print(f"Entry point: {entry}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Asset dirs: {theme_dir}, {locale_dir}")
    print("=" * 60)

    result = subprocess.run(cmd)
    if result.returncode == 0:
        dest = os.path.join(OUTPUT_DIR, "tg-translate-sum")
        print(f"\n Build successful!")
        print(f"   Executable: {dest}")
        print(f"   Size: {os.path.getsize(dest) / 1024 / 1024:.1f} MB")
    else:
        print(f"\n Build failed (exit code {result.returncode})")

if __name__ == "__main__":
    build()
