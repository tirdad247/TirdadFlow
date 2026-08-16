# -*- coding: utf-8 -*-
"""
TirdadFlow v1.3.1 — portable, bilingual (EN/FA) AI voice typer for Windows.
Free providers: Groq + Google Gemini (free tier). Auto provider failover.
Per-provider saved keys. Auto-height window. One-click Copy Log button.
Support: https://t.me/ProfileTradingHub

v1.3.1 incorporates the multi-model pre-release review (GPT Pro, Claude Sonnet,
Gemini, Grok): key-leak redaction, header-based Gemini auth, stdlib WAV encoding,
safe logging fallback, single-instance guard, hook teardown fixes, and more.
"""

import sys
import os
import io
import json
import base64
import wave
import winreg
import ctypes
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import threading
import logging
from logging.handlers import RotatingFileHandler
import httpx  # bundled with the groq package; no extra dependency needed
from groq import Groq

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QComboBox,
                             QPushButton, QCheckBox, QSystemTrayIcon, QMenu,
                             QStyle, QFrame)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPoint, QTimer, QEvent
from PyQt6.QtGui import QAction, QFont, QFontDatabase

APP_VERSION = "1.3.2"
SUPPORT_URL = "https://t.me/ProfileTradingHub"

# --- Test keys ---------------------------------------------------------------
# Keep these EMPTY in the public release - never ship real keys in source!
# For local testing you may temporarily paste keys here; they are used only
# when no key is saved in the config file yet.
TEST_GROQ_KEY = ""
TEST_GEMINI_KEY = ""

# --- Free transcription providers -------------------------------------------
PROVIDERS = {
    "groq": {
        "label": "Groq (Free)",
        "type": "groq",
        # NOTE: do NOT pass base_url to the Groq SDK - its default is already
        # correct, and overriding it caused a doubled path (/openai/v1/openai/v1/...)
        "models": ["whisper-large-v3-turbo", "whisper-large-v3"],
        "key_url": "https://console.groq.com/keys",
    },
    "gemini": {
        "label": "Google Gemini (Free)",
        "type": "gemini",
        "models": ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.6-flash"],
        "key_url": "https://aistudio.google.com/apikey",
        "privacy_warning": True,  # free tier data may be used to train Google models
    },
}


def get_config_path():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return base_dir


BASE_DIR = get_config_path()
CONFIG_FILE = os.path.join(BASE_DIR, "tirdad_flow_config.json")
LOG_FILE = os.path.join(BASE_DIR, "tirdad_flow.log")
SAMPLE_RATE = 16000
# 7 minutes of 16 kHz int16 mono audio ~= 13.4 MB raw (~17.9 MB after base64),
# which stays under BOTH the ~25 MB Whisper upload cap and Gemini's 20 MB
# inline-request limit. Counted in frames, not chunks, because PortAudio's
# callback block size varies between devices.
MAX_RECORD_SECONDS = 420


def _make_log_handler():
    """Rotating log next to the exe; falls back to %TEMP% when the portable
    folder is not writable (e.g. Program Files, some OneDrive mounts)."""
    try:
        return RotatingFileHandler(LOG_FILE, maxBytes=200000, backupCount=1, encoding="utf-8")
    except Exception:
        return RotatingFileHandler(os.path.join(os.environ.get("TEMP", "."), "tirdad_flow.log"),
                                   maxBytes=200000, backupCount=1, encoding="utf-8")


try:
    _log_handler = _make_log_handler()
    ACTIVE_LOG_FILE = _log_handler.baseFilename
    logging.basicConfig(handlers=[_log_handler], level=logging.WARNING,
                        format="%(asctime)s - %(levelname)s - %(message)s")
except Exception:
    ACTIVE_LOG_FILE = None  # last resort: console-only logging, never crash on log I/O
    logging.basicConfig(level=logging.WARNING)

TRANSLATIONS = {
    "en": {
        "provider_label": "AI Provider (both free):",
        "api_label": "API Key(s):",
        "api_tooltip": "One or more API keys, separated by commas. "
                       "If one key hits its quota or rate limit, the next key is tried automatically.",
        "key_hint": "Get a free key: {}",
        "gemini_privacy": "⚠️ Gemini free tier may use your audio to improve Google products",
        "hotkey_label": "Global Hotkey:",
        "model_label": "AI Model:",
        "lang_label": "Speech Language:",
        "device_label": "Microphone Input:",
        "startup_label": "Run at Windows Startup",
        "floating_label": "Show Floating Widget (Disables F9)",
        "auto_failover_label": "Auto-switch provider if quota runs out",
        "auto_failover_tooltip": "If this provider fails, audio is sent to any other provider that has "
                                 "a saved key. Check each provider's privacy note before saving a key.",
        "via_suffix": " (via {})",
        "copy_log_btn": "📋 Copy Log",
        "status_log_copied": "Log copied to clipboard - paste it anywhere to share",
        "status_bad_hotkey": "Invalid hotkey - reverted to F9",
        "menu_paste": "🎙️ Record & Auto-paste",
        "menu_copy": "📋 Record & Copy",
        "menu_settings": "⚙️ Settings",
        "status_ready": "Status: Ready",
        "status_recording": "Status: Recording audio...",
        "status_processing": "Status: Processing...",
        "status_pasted": "Status: Transcribed and pasted",
        "status_copied": "Status: Copied to clipboard",
        "status_error": "Processing error",
        "status_no_mic": "Error: No active microphone found",
        "status_no_api": "Error: API Key is missing!",
        "status_invalid_key": "Error: API key is invalid - check and re-enter it",
        "status_quota": "Error: daily quota/credit exhausted for this key",
        "status_overloaded": "Provider temporarily overloaded - retry in a minute",
        "status_all_keys_failed": "Error: all providers/keys failed",
        "tray_settings": "Settings",
        "tray_toggle_widget": "Toggle Floating Widget",
        "tray_exit": "Exit TirdadFlow",
        "tray_msg_title": "TirdadFlow",
        "tray_msg_body": "App minimized to system tray. Right-click tray icon for options.",
        "default_mic": "Default System Mic",
        "network_err": "Check network/VPN connection",
        "lang_auto": "Auto-Detect",
        "lang_fa": "Persian (فارسی)",
        "lang_en": "English",
        "support_text": f'<a href="{SUPPORT_URL}" style="color: #a1a1aa; text-decoration: none;">☕ Support us & Join Telegram Channel</a>',
    },
    "fa": {
        "provider_label": "سرویس هوش مصنوعی (هر دو رایگان):",
        "api_label": "کلید(های) API:",
        "api_tooltip": "یک یا چند کلید را با کاما جدا کنید. "
                       "اگر یک کلید به سقف سهمیه برسد، کلید بعدی به‌صورت خودکار امتحان می‌شود.",
        "key_hint": "دریافت کلید رایگان: {}",
        "gemini_privacy": "⚠️ پلن رایگان Gemini ممکن است از صدای شما برای بهبود محصولات گوگل استفاده کند",
        "hotkey_label": "کلید میانبر (Hotkey):",
        "model_label": "مدل پردازش صدا:",
        "lang_label": "زبان گفتار (صدا):",
        "device_label": "ورودی میکروفون:",
        "startup_label": "اجرا هنگام روشن شدن ویندوز",
        "floating_label": "نمایش ویجت شناور روی صفحه (غیرفعال‌سازی F9)",
        "auto_failover_label": "سوییچ خودکار به سرویس دیگر اگر سهمیه تمام شود",
        "auto_failover_tooltip": "اگر این سرویس شکست بخورد، صدا به سرویس دیگری که کلید ذخیره دارد "
                                 "فرستاده می‌شود. هشدار حریم خصوصی هر سرویس را ببینید.",
        "via_suffix": " (از طریق {})",
        "copy_log_btn": "📋 کپی لاگ",
        "status_log_copied": "لاگ در کلیپ‌بورد کپی شد - آن را ارسال کنید",
        "status_bad_hotkey": "کلید میانبر نامعتبر است - به F9 برگشت",
        "menu_paste": "🎙️ ضبط و درج خودکار",
        "menu_copy": "📋 ضبط و کپی",
        "menu_settings": "⚙️ تنظیمات",
        "status_ready": "وضعیت: آماده به کار",
        "status_recording": "وضعیت: در حال ضبط صدا...",
        "status_processing": "وضعیت: در حال پردازش...",
        "status_pasted": "وضعیت: متن با موفقیت درج شد",
        "status_copied": "وضعیت: متن در کلیپ‌بورد کپی شد",
        "status_error": "خطای پردازش",
        "status_no_mic": "خطا: میکروفون فعال یافت نشد",
        "status_no_api": "خطا: کلید API وارد نشده است!",
        "status_invalid_key": "خطا: کلید API نامعتبر است - دوباره وارد کنید",
        "status_quota": "خطا: سهمیه روزانه/اعتبار این کلید تمام شده است",
        "status_overloaded": "سرویس موقتاً شلوغ است - یک دقیقه دیگر تلاش کنید",
        "status_all_keys_failed": "خطا: همه سرویس‌ها/کلیدها ناموفق بودند",
        "tray_settings": "تنظیمات",
        "tray_toggle_widget": "نمایش/مخفی کردن ویجت",
        "tray_exit": "خروج کامل",
        "tray_msg_title": "TirdadFlow",
        "tray_msg_body": "برنامه در پس‌زمینه در حال کار است. برای خروج روی آیکون کلیک راست کنید.",
        "default_mic": "پیش‌فرض سیستم / Default System Mic",
        "network_err": "مشکل شبکه/VPN را بررسی کنید",
        "lang_auto": "تشخیص خودکار",
        "lang_fa": "فارسی (Persian)",
        "lang_en": "انگلیسی (English)",
        "support_text": f'<a href="{SUPPORT_URL}" style="color: #a1a1aa; text-decoration: none;">☕ حمایت از پروژه و عضویت در کانال تلگرام</a>',
    }
}

DARK_QSS = """
QMainWindow { background: transparent; }
QWidget#centralWidget { background-color: #121215; border: 1px solid #2d2d35; border-radius: 12px; }
QWidget { font-family: 'Vazirmatn', 'B Yekan', 'Segoe UI', Tahoma, sans-serif; font-size: 13px; font-weight: normal; color: #f4f4f5; }
QFrame#card { background-color: #1e1e24; border: 1px solid #2d2d35; border-radius: 12px; padding: 14px; }
QLabel { background: transparent; color: #a1a1aa; font-weight: 600; font-size: 13px; }
QLabel#titleLabel { background: transparent; color: #ffffff; font-size: 16px; font-weight: 800; font-family: 'B Titr', 'Vazirmatn', 'Segoe UI', Tahoma, sans-serif; }
QLineEdit, QComboBox { background-color: #141418; border: 1px solid #3f3f46; border-radius: 8px; color: #ffffff; padding: 6px 10px; font-size: 13px; font-weight: normal; min-height: 34px; selection-background-color: #10b981; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #10b981; }
QComboBox { text-align: left; }
QComboBox::drop-down { border: none; width: 28px; background: transparent; }
QComboBox::down-arrow { image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%23a1a1aa' stroke-width='2'><path stroke-linecap='round' stroke-linejoin='round' d='M19 9l-7 7-7-7'/></svg>"); width: 16px; height: 16px; margin-right: 6px; }
QPushButton#langToggleBtn { background-color: #27272a; border: 1px solid #3f3f46; border-radius: 8px; color: #10b981; font-weight: 800; font-size: 13px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 0px; }
QPushButton#langToggleBtn:hover { background-color: #3f3f46; }
QPushButton#windowBtn, QPushButton#closeBtn { background: transparent; border: none; color: #a1a1aa; font-size: 14px; font-weight: bold; border-radius: 6px; }
QPushButton#windowBtn:hover { background-color: #2d2d35; color: #ffffff; }
QPushButton#closeBtn:hover { background-color: #ef4444; color: #ffffff; }
QCheckBox { background: transparent; color: #d4d4d8; spacing: 8px; font-size: 13px; font-weight: normal; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3f3f46; background-color: #141418; }
QCheckBox::indicator:checked { background-color: #10b981; border-color: #10b981; }
"""

# Persian UI font overrides (applied on top of DARK_QSS when ui_language == "fa").
# Only the font FAMILY changes - sizes stay identical to English so toggling
# the language never causes a layout jump. Clean readable defaults out of the
# box (Vazirmatn if installed, otherwise Segoe UI/Tahoma which ship with
# Windows). Dropping font files into a "fonts" folder remains an optional override.
FA_FONT_QSS = """
QWidget { font-family: 'Vazirmatn', 'B Nazanin', 'B Mitra', 'Segoe UI', Tahoma, sans-serif; }
QLabel#titleLabel { font-family: 'B Titr', 'Vazirmatn', 'Segoe UI', Tahoma, sans-serif; }
"""


def load_custom_fonts():
    """Optionally register font files from a 'fonts' folder next to the app/exe.
    Not required - the app looks clean out of the box with default fonts."""
    try:
        fonts_dir = os.path.join(BASE_DIR, "fonts")
        if os.path.isdir(fonts_dir):
            for fn in sorted(os.listdir(fonts_dir)):
                if fn.lower().endswith((".ttf", ".otf", ".ttc")):
                    QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fn))
    except Exception as e:
        logging.error(f"Failed to load custom fonts: {e}")


def load_config():
    default_config = {
        "provider": "groq",
        "keys": {},           # per-provider API keys, comma-separated values
        "models": {},         # per-provider selected model
        "hotkey": "f9",
        "speech_lang": "auto",
        "ui_language": "en",
        "audio_device": None,
        "startup": False,
        "show_floating_widget": False,
        "auto_provider_failover": True,
        "overlay_pos": None,
        "_notice": "API key(s) are unencrypted for portability. See SECURITY.md"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception as e:
            logging.error(f"Failed to load config: {e}")
    # Migrate legacy single "api_key" (pre-v1.1 configs) into per-provider keys
    legacy = default_config.pop("api_key", "")
    if legacy and isinstance(legacy, str) and legacy.strip():
        default_config.setdefault("keys", {}).setdefault("groq", legacy.strip())
    # Migrate legacy single "model" selection
    legacy_model = default_config.pop("model", "")
    if legacy_model and isinstance(legacy_model, str):
        default_config.setdefault("models", {}).setdefault("groq", legacy_model)
    # Cloudflare leftovers from v1.1/v1.2 configs are simply ignored
    default_config.pop("cf_account_id", None)
    # Type-validate nested fields so a corrupted/hand-edited config can't crash startup
    if not isinstance(default_config.get("keys"), dict):
        default_config["keys"] = {}
    if not isinstance(default_config.get("models"), dict):
        default_config["models"] = {}
    if not isinstance(default_config.get("provider"), str) or default_config["provider"] not in PROVIDERS:
        default_config["provider"] = "groq"
    # Dev-only convenience: test keys are used only when no key is saved yet.
    # They are EMPTY in the public release.
    if TEST_GROQ_KEY and not str(default_config.get("keys", {}).get("groq", "")).strip():
        default_config.setdefault("keys", {})["groq"] = TEST_GROQ_KEY
    if TEST_GEMINI_KEY and not str(default_config.get("keys", {}).get("gemini", "")).strip():
        default_config.setdefault("keys", {})["gemini"] = TEST_GEMINI_KEY
    return default_config


def save_config(config):
    try:
        # Atomic-ish write: temp file + replace, so a crash can't leave truncated JSON
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")


def parse_api_keys(raw: str):
    """Accepts a single key or several comma-separated keys (failover order)."""
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def set_windows_startup(enable: bool):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "TirdadFlow"
    exe_path = f'"{sys.executable}"' if getattr(sys, 'frozen', False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    try:
        if enable:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
        else:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        logging.error(f"Failed to set Windows startup: {e}")


def get_audio_input_devices():
    devices_list = []
    try:
        seen = set()
        for idx, dev in enumerate(sd.query_devices()):
            name = dev['name'].strip()
            name_lower = name.lower()
            if any(b in name_lower for b in ["microsoft sound mapper", "primary sound capture"]):
                continue
            if dev['max_input_channels'] > 0 and name not in seen:
                seen.add(name)
                devices_list.append((idx, name.split(' (')[0] if '\\' in name else name))
    except Exception as e:
        logging.error(f"Failed to query audio devices: {e}")
    return devices_list


class AudioWorker(QThread):
    finished_signal = pyqtSignal(str, bool, str)  # text, copy_only, provider label used
    error_signal = pyqtSignal(str)

    def __init__(self, audio_data, chain, speech_lang, copy_only=False):
        """chain: ordered list of {"provider", "keys", "model"}.
        Providers are tried in order (auto failover); keys inside each provider
        are tried in order (key failover)."""
        super().__init__()
        self.audio_data = audio_data
        self.chain = chain
        self.speech_lang = speech_lang
        self.copy_only = copy_only

    def _scrub(self, msg):
        """Remove every configured API key from an error string before it can
        reach the log file, the UI status line, or the Copy Log button."""
        out = str(msg)
        for step in self.chain:
            for k in step.get("keys", []):
                if k and k in out:
                    out = out.replace(k, "***")
        return out

    # --- per-provider request helpers ----------------------------------------

    def _request_groq(self, keys, model, wav_bytes):
        """Groq Whisper transcription via the official SDK (default endpoint).
        The SDK sends the key in the Authorization header, so it never appears in URLs."""
        kwargs = {"model": model, "response_format": "text"}
        if self.speech_lang == "fa":
            kwargs["language"] = "fa"
            kwargs["prompt"] = "کلمات انگلیسی و عبارات تخصصی کامپیوتر مانند Python, Windows به خط انگلیسی تایپ شوند."
        elif self.speech_lang == "en":
            kwargs["language"] = "en"
        last = "no_api_key"
        for i, key in enumerate(keys, 1):
            try:
                client = Groq(api_key=key, timeout=45.0, max_retries=1)
                t = client.audio.transcriptions.create(file=("audio.wav", wav_bytes), **kwargs)
                return t.strip() if isinstance(t, str) else t.text.strip()
            except Exception as e:
                last = self._scrub(e)
                logging.warning(f"groq key #{i} failed: {last[:120]}")
        raise RuntimeError(last)

    def _request_gemini(self, keys, model, wav_bytes):
        """Google Gemini generateContent with inline base64 audio (free tier).
        The key travels in the x-goog-api-key HEADER - never in the URL - so
        httpx error messages can never leak it into logs or the UI."""
        if self.speech_lang == "fa":
            prompt = ("این فایل صوتی فارسی را دقیقاً به متن تبدیل کن. فقط متن گفتار را بنویس، "
                      "بدون هیچ توضیح یا علامت اضافی. کلمات انگلیسی و عبارات تخصصی کامپیوتر "
                      "مانند Python و Windows را به همان خط انگلیسی بنویس.")
        elif self.speech_lang == "en":
            prompt = "Transcribe this audio to English text. Output only the exact transcript, no commentary or formatting."
        else:
            prompt = ("Transcribe this audio exactly in its spoken language (Persian or English). "
                      "Output only the transcript, no commentary. Keep English technical terms in English script.")
        payload = {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "audio/wav",
                                  "data": base64.b64encode(wav_bytes).decode("ascii")}},
                {"text": prompt},
            ]}],
            "generationConfig": {"temperature": 0},
        }
        last = "no_api_key"
        for i, key in enumerate(keys, 1):
            try:
                url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
                r = httpx.post(url, json=payload, timeout=45.0,
                               headers={"x-goog-api-key": key})
                r.raise_for_status()
                data = r.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError, TypeError):
                    raise RuntimeError("gemini returned an empty or safety-blocked response")
            except Exception as e:
                last = self._scrub(e)
                logging.warning(f"gemini key #{i} failed: {last[:120]}")
        raise RuntimeError(last)

    def transcribe(self, wav_bytes):
        """Try each provider in the failover chain; inside each provider, try
        each key. A future local engine (faster-whisper / whisper.cpp) can plug
        in here as another chain step without touching recording/UI/clipboard."""
        last_err = "no_api_key"
        for step in self.chain:
            prov = step["provider"]
            try:
                if PROVIDERS[prov]["type"] == "gemini":
                    text = self._request_gemini(step["keys"], step["model"], wav_bytes)
                else:
                    text = self._request_groq(step["keys"], step["model"], wav_bytes)
                return text, PROVIDERS[prov]["label"]
            except Exception as e:
                last_err = self._scrub(e)
                logging.warning(f"Provider '{prov}' failed: {last_err[:120]} -> trying next in chain")
        raise RuntimeError("all_keys_failed: " + last_err)

    def run(self):
        try:
            if not self.audio_data:
                self.finished_signal.emit("", self.copy_only, "")
                return

            recording = np.concatenate(self.audio_data, axis=0)
            # stdlib wave instead of scipy: no hidden import, ~100 MB smaller exe
            wav_io = io.BytesIO()
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # int16 PCM
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(recording.tobytes())

            # NOTE: send bytes (not the BytesIO stream) so retries can re-read the payload.
            text, via_label = self.transcribe(wav_io.getvalue())
            self.finished_signal.emit(text, self.copy_only, via_label)
        except Exception as e:
            self.error_signal.emit(self._scrub(e))


class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(54)

        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 0)
        layout.setSpacing(14)

        current_lang = parent.config.get("ui_language", "en")
        self.lang_toggle_btn = QPushButton("FA" if current_lang == "en" else "EN")
        self.lang_toggle_btn.setObjectName("langToggleBtn")
        self.lang_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_toggle_btn.clicked.connect(parent.toggle_ui_language)

        self.title_label = QLabel("TirdadFlow")
        self.title_label.setObjectName("titleLabel")

        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("windowBtn")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.clicked.connect(parent.showMinimized)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.clicked.connect(parent.close)

        layout.addWidget(self.lang_toggle_btn)
        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.min_btn)
        layout.addWidget(self.close_btn)
        self.drag_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_pos.isNull():
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()


class FloatingOverlayWidget(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.drag_position = QPoint()
        self.is_dragging = False
        self._just_dragged = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mic_btn = QPushButton("🎙️")
        self.mic_btn.setStyleSheet("QPushButton { background-color: rgba(28, 28, 33, 0.95); border: 1px solid #3f3f46; color: white; border-radius: 16px; font-size: 20px; } QPushButton:hover { border: 1px solid #10b981; background-color: rgba(39, 39, 42, 0.95); }")
        self.mic_btn.setFixedSize(52, 52)
        self.mic_btn.clicked.connect(self.on_auto_click)
        self.mic_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mic_btn.customContextMenuRequested.connect(self.show_context_menu)
        # Forward the button's mouse events to the widget so dragging works
        # even when the press starts on the button itself.
        self.mic_btn.installEventFilter(self)
        layout.addWidget(self.mic_btn)
        self.setFixedSize(56, 56)

    def eventFilter(self, obj, event):
        if obj is self.mic_btn:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.mousePressEvent(event)
            elif event.type() == QEvent.Type.MouseMove:
                self.mouseMoveEvent(event)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(event)
        return super().eventFilter(obj, event)

    def show_context_menu(self, pos):
        if self.main_window.is_processing: return
        tr = self.main_window.tr
        menu = QMenu(self)
        menu.setStyleSheet(DARK_QSS)
        menu.addAction(tr("menu_paste")).triggered.connect(lambda: self.main_window.toggle_recording(copy_only=False))
        menu.addAction(tr("menu_copy")).triggered.connect(lambda: self.main_window.toggle_recording(copy_only=True))
        menu.addSeparator()
        menu.addAction(tr("menu_settings")).triggered.connect(self.main_window.showNormal)
        menu.exec(self.mic_btn.mapToGlobal(pos))

    def on_auto_click(self):
        if getattr(self, "_just_dragged", False):
            self._just_dragged = False
            return
        if not self.is_dragging and not self.main_window.is_processing:
            self.main_window.toggle_recording(copy_only=False)

    def update_rec_status(self, is_rec):
        if is_rec:
            self.mic_btn.setText("⏹️")
            self.mic_btn.setStyleSheet("QPushButton { background-color: rgba(239, 68, 68, 0.95); border: 1px solid #ef4444; color: white; border-radius: 16px; font-size: 18px; } QPushButton:hover { background-color: rgba(220, 38, 38, 0.95); }")
        else:
            self.mic_btn.setText("🎙️")
            self.mic_btn.setStyleSheet("QPushButton { background-color: rgba(28, 28, 33, 0.95); border: 1px solid #3f3f46; color: white; border-radius: 16px; font-size: 20px; } QPushButton:hover { border: 1px solid #10b981; background-color: rgba(39, 39, 42, 0.95); }")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_position = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.is_dragging = False

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_position)
            self.is_dragging = True

    def mouseReleaseEvent(self, e):
        if self.is_dragging:
            self._just_dragged = True
            # Remember the position so the widget stops snapping back to top-center
            self.main_window.config["overlay_pos"] = [self.x(), self.y()]
            save_config(self.main_window.config)
        self.is_dragging = False


class MainWindow(QMainWindow):
    hotkey_pressed_signal = pyqtSignal()
    hotkey_released_signal = pyqtSignal()
    recording_limit_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.config = load_config()
        # Test-protocol banner: every log the user sends starts with full context
        logging.warning(f"--- TirdadFlow v{APP_VERSION} started | provider={self.config.get('provider')} | failover={self.config.get('auto_provider_failover')} | keys_saved={list(self.config.get('keys', {}).keys())} ---")
        self.is_recording = False
        self.is_processing = False
        self.is_copy_only = False
        self.audio_data = []
        self.stream = None
        self.audio_devices = get_audio_input_devices()

        self.audio_lock = threading.Lock()
        self.recorded_frames = 0
        self.max_frames = SAMPLE_RATE * MAX_RECORD_SECONDS
        self.limit_reached = False
        self.press_hook = None
        self.release_hook = None
        self._initializing = True

        self.setStyleSheet(DARK_QSS)
        self.init_ui()
        self.setup_tray()

        self.hotkey_pressed_signal.connect(self.handle_hotkey_press)
        self.hotkey_released_signal.connect(self.handle_hotkey_release)
        self.recording_limit_signal.connect(self.stop_audio_stream_and_process)
        self.setup_floating_widget_and_hotkey()

    def tr(self, key):
        return TRANSLATIONS.get(self.config.get("ui_language", "en"), TRANSLATIONS["en"]).get(key, key)

    def current_provider(self):
        return self.provider_combo.currentData()

    def current_keys(self):
        return parse_api_keys(self.config.get("keys", {}).get(self.config.get("provider", "groq"), ""))

    def current_model(self, provider=None):
        p = provider or self.config.get("provider", "groq")
        saved = self.config.get("models", {}).get(p)
        return saved if saved in PROVIDERS[p]["models"] else PROVIDERS[p]["models"][0]

    def resolve_device(self):
        """Persisted device NAME -> current PortAudio index (indices shift when
        devices are (un)plugged; names are stable). Falls back to system default."""
        name = self.config.get("audio_device")
        if not name:
            return None
        for idx, dev_name in self.audio_devices:
            if dev_name == name:
                return idx
        return None

    def set_status(self, key, is_error=False, custom_text=None):
        base_txt = self.tr(key) if key in TRANSLATIONS["en"] else key
        final_txt = f"{base_txt}: {custom_text}" if custom_text else base_txt
        self.status_label.setText(final_txt)
        color = "#ef4444" if is_error else "#10b981"
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600; font-size: 13px; margin-top: 2px;")

    def fit_window_height(self):
        """Auto-size the window from the actual layout content. Fixed heights
        caused overlapping widgets whenever content grew; Persian needs a bit
        more width for its longer checkbox labels."""
        lay = self.centralWidget().layout()
        if lay is not None:
            lay.activate()
            w = 495 if self.config.get("ui_language", "en") == "fa" else 460
            h = lay.sizeHint().height() + 24  # outer margins + breathing room
            self.setFixedSize(w, max(h, 430))

    def copy_log_to_clipboard(self):
        """One-click diagnostics: copy the log file so the user can paste it
        into a bug report or support message."""
        try:
            path = ACTIVE_LOG_FILE or LOG_FILE
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            pyperclip.copy(content.strip() if content.strip() else "(log is empty)")
            self.set_status("status_log_copied")
        except Exception as e:
            self.set_status("status_error", True, str(e)[:30])

    def init_ui(self):
        self.setFixedWidth(460)
        self.setMinimumHeight(430)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        inner_layout = QVBoxLayout(central_widget)
        inner_layout.setContentsMargins(0, 0, 0, 14)
        inner_layout.setSpacing(12)
        self.title_bar = CustomTitleBar(self)
        inner_layout.addWidget(self.title_bar)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(18, 0, 18, 0)
        content_layout.setSpacing(12)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)

        # Provider
        self.provider_lbl = QLabel()
        card_layout.addWidget(self.provider_lbl)
        self.provider_combo = QComboBox()
        for key, info in PROVIDERS.items():
            self.provider_combo.addItem(info["label"], key)
        saved_provider = self.config.get("provider", "groq")
        pidx = self.provider_combo.findData(saved_provider)
        if pidx >= 0:
            self.provider_combo.setCurrentIndex(pidx)
        self.provider_combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        card_layout.addWidget(self.provider_combo)

        # API Key(s)
        self.api_lbl = QLabel()
        card_layout.addWidget(self.api_lbl)
        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_input.editingFinished.connect(self.auto_save)
        self.api_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        card_layout.addWidget(self.api_input)

        # Gemini free-tier privacy warning
        self.privacy_lbl = QLabel()
        self.privacy_lbl.setWordWrap(True)
        self.privacy_lbl.setStyleSheet("color: #fbbf24; font-size: 11px;")
        card_layout.addWidget(self.privacy_lbl)

        # Audio Device
        self.device_lbl = QLabel()
        card_layout.addWidget(self.device_lbl)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Default", None)
        saved_device = self.config.get("audio_device", None)
        selected_idx = 0
        for i, (dev_id, dev_name) in enumerate(self.audio_devices, start=1):
            self.device_combo.addItem(dev_name, dev_id)
            # v1.3.1+ stores the device NAME; older configs stored the index
            if saved_device == dev_name or saved_device == dev_id:
                selected_idx = i
        self.device_combo.setCurrentIndex(selected_idx)
        self.device_combo.currentIndexChanged.connect(self.auto_save)
        self.device_combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        card_layout.addWidget(self.device_combo)

        # Speech Language & Model
        row_lang_model = QHBoxLayout()
        lang_box = QVBoxLayout()
        self.lang_lbl = QLabel()
        lang_box.addWidget(self.lang_lbl)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Auto", "auto")
        self.lang_combo.addItem("Persian", "fa")
        self.lang_combo.addItem("English", "en")
        saved_lang = self.config.get("speech_lang", "auto")
        idx = self.lang_combo.findData(saved_lang)
        if idx >= 0: self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self.auto_save)
        self.lang_combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        lang_box.addWidget(self.lang_combo)
        row_lang_model.addLayout(lang_box)
        model_box = QVBoxLayout()
        self.model_lbl = QLabel()
        model_box.addWidget(self.model_lbl)
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self.auto_save)
        self.model_combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        model_box.addWidget(self.model_combo)
        row_lang_model.addLayout(model_box)
        card_layout.addLayout(row_lang_model)

        # Hotkey
        hotkey_box = QVBoxLayout()
        self.hotkey_lbl = QLabel()
        hotkey_box.addWidget(self.hotkey_lbl)
        self.hotkey_input = QLineEdit(self.config.get("hotkey", "f9"))
        self.hotkey_input.editingFinished.connect(self.auto_save)
        self.hotkey_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        hotkey_box.addWidget(self.hotkey_input)
        card_layout.addLayout(hotkey_box)

        # Checkboxes
        self.startup_check = QCheckBox()
        self.startup_check.setChecked(self.config.get("startup", False))
        self.startup_check.stateChanged.connect(self.auto_save)
        card_layout.addWidget(self.startup_check)
        self.floating_check = QCheckBox()
        self.floating_check.setChecked(self.config.get("show_floating_widget", False))
        self.floating_check.stateChanged.connect(self.auto_save)
        card_layout.addWidget(self.floating_check)
        self.auto_failover_check = QCheckBox()
        self.auto_failover_check.setChecked(self.config.get("auto_provider_failover", True))
        self.auto_failover_check.stateChanged.connect(self.auto_save)
        card_layout.addWidget(self.auto_failover_check)
        content_layout.addWidget(card)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        content_layout.addWidget(self.status_label)
        self.support_label = QLabel()
        self.support_label.setOpenExternalLinks(True)
        self.support_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.support_label.setStyleSheet("QLabel { font-size: 11px; margin-top: 4px; } QLabel:hover { color: #ffffff; }")
        content_layout.addWidget(self.support_label)

        # Copy-log row (bottom corner) - one-click diagnostics for any user
        log_row = QHBoxLayout()
        log_row.addStretch()
        self.copy_log_btn = QPushButton()
        self.copy_log_btn.setObjectName("logBtn")
        self.copy_log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_log_btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #3f3f46; border-radius: 8px; color: #71717a; font-size: 11px; padding: 4px 12px; } QPushButton:hover { color: #ffffff; border-color: #10b981; }")
        self.copy_log_btn.clicked.connect(self.copy_log_to_clipboard)
        log_row.addWidget(self.copy_log_btn)
        content_layout.addLayout(log_row)

        inner_layout.addLayout(content_layout)
        main_layout.addWidget(central_widget)
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # Now that every widget exists, sync provider-dependent UI, then connect.
        self.on_provider_changed()
        self._initializing = False
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
        self.provider_combo.currentIndexChanged.connect(self.auto_save)
        self.refresh_ui_text()

    def on_provider_changed(self):
        # 1) Persist whatever is typed right now under the OLD provider first,
        #    so switching back and forth never loses keys or model choices.
        #    (Skipped during initial UI setup, when the key field is still empty.)
        old_p = self.config.get("provider", "groq")
        if not getattr(self, "_initializing", False) and hasattr(self, "api_input") and old_p in PROVIDERS:
            self.config.setdefault("keys", {})[old_p] = self.api_input.text().strip()
            if self.model_combo.count() > 0:
                self.config.setdefault("models", {})[old_p] = self.model_combo.currentText()

        p = self.provider_combo.currentData()
        info = PROVIDERS[p]

        # 2) Load the new provider's saved key(s) and model (signals blocked)
        self.api_input.blockSignals(True)
        self.api_input.setText(self.config.get("keys", {}).get(p, ""))
        self.api_input.blockSignals(False)

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(info["models"])
        saved_model = self.config.get("models", {}).get(p)
        if saved_model in info["models"]:
            self.model_combo.setCurrentText(saved_model)
        self.model_combo.blockSignals(False)

        # 3) Provider-specific extras
        self.privacy_lbl.setVisible(bool(info.get("privacy_warning")))
        self.privacy_lbl.setText(self.tr("gemini_privacy"))
        self.api_input.setToolTip(self.tr("api_tooltip") + "\n" + self.tr("key_hint").format(info["key_url"]))

        # 4) Window height always fits the actual content - no overlap, ever
        self.fit_window_height()

    def auto_save(self):
        old_startup = self.config.get("startup", False)
        old_hotkey = self.config.get("hotkey", "f9")
        old_widget = self.config.get("show_floating_widget", False)

        p = self.current_provider()
        self.config["provider"] = p
        keys = self.config.setdefault("keys", {})
        keys[p] = self.api_input.text().strip()
        models = self.config.setdefault("models", {})
        if self.model_combo.count() > 0:
            models[p] = self.model_combo.currentText()

        self.config["hotkey"] = self.hotkey_input.text().strip().lower()
        self.config["speech_lang"] = self.lang_combo.currentData()
        # Store the device NAME (stable across (un)plugs), not the PortAudio index
        self.config["audio_device"] = self.device_combo.currentText() if self.device_combo.currentIndex() > 0 else None
        self.config["startup"] = self.startup_check.isChecked()
        self.config["show_floating_widget"] = self.floating_check.isChecked()
        self.config["auto_provider_failover"] = self.auto_failover_check.isChecked()
        save_config(self.config)

        if old_startup != self.config["startup"]:
            set_windows_startup(self.config["startup"])

        if old_hotkey != self.config["hotkey"] or old_widget != self.config["show_floating_widget"]:
            self.setup_floating_widget_and_hotkey()

    def toggle_ui_language(self):
        self.config["ui_language"] = "fa" if self.config.get("ui_language", "en") == "en" else "en"
        save_config(self.config)
        self.refresh_ui_text()
        # Re-fit the window for the new language's font metrics
        self.fit_window_height()

    def refresh_ui_text(self):
        lang = self.config.get("ui_language", "en")
        # Persian UI gets the FA font stack (clean defaults; optional fonts/ override)
        self.setStyleSheet(DARK_QSS + (FA_FONT_QSS if lang == "fa" else ""))
        self.title_bar.lang_toggle_btn.setText("FA" if lang == "en" else "EN")
        self.provider_lbl.setText(self.tr("provider_label"))
        self.api_lbl.setText(self.tr("api_label"))
        self.privacy_lbl.setText(self.tr("gemini_privacy"))
        info = PROVIDERS[self.current_provider()]
        self.api_input.setToolTip(self.tr("api_tooltip") + "\n" + self.tr("key_hint").format(info["key_url"]))
        self.device_lbl.setText(self.tr("device_label"))
        self.device_combo.setItemText(0, self.tr("default_mic"))
        self.hotkey_lbl.setText(self.tr("hotkey_label"))
        self.model_lbl.setText(self.tr("model_label"))
        self.lang_lbl.setText(self.tr("lang_label"))
        self.lang_combo.setItemText(0, self.tr("lang_auto"))
        self.lang_combo.setItemText(1, self.tr("lang_fa"))
        self.lang_combo.setItemText(2, self.tr("lang_en"))
        self.startup_check.setText(self.tr("startup_label"))
        self.floating_check.setText(self.tr("floating_label"))
        self.auto_failover_check.setText(self.tr("auto_failover_label"))
        self.auto_failover_check.setToolTip(self.tr("auto_failover_tooltip"))
        self.support_label.setText(self.tr("support_text"))
        self.copy_log_btn.setText(self.tr("copy_log_btn"))
        # Preserve the semantic status - a language toggle must not fake "Ready"
        if self.is_recording:
            self.set_status("status_recording")
        elif self.is_processing:
            self.set_status("status_processing")
        else:
            self.set_status("status_ready")
        if lang == "fa":
            self.centralWidget().setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        else:
            self.centralWidget().setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.title_bar.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.status_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.support_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        if hasattr(self, 'tray_settings_action'):
            self.tray_settings_action.setText(self.tr("tray_settings"))
            self.tray_widget_action.setText(self.tr("tray_toggle_widget"))
            self.tray_exit_action.setText(self.tr("tray_exit"))

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.tray_icon.setToolTip(f"TirdadFlow v{APP_VERSION}")
        tray_menu = QMenu()
        self.tray_settings_action = QAction(self.tr("tray_settings"), self)
        self.tray_settings_action.triggered.connect(self.showNormal)
        self.tray_widget_action = QAction(self.tr("tray_toggle_widget"), self)
        self.tray_widget_action.triggered.connect(self.toggle_floating_widget_vis)
        self.tray_exit_action = QAction(self.tr("tray_exit"), self)
        self.tray_exit_action.triggered.connect(self.force_quit)
        tray_menu.addActions([self.tray_settings_action, self.tray_widget_action])
        tray_menu.addSeparator()
        tray_menu.addAction(self.tray_exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def setup_floating_widget_and_hotkey(self):
        if not hasattr(self, 'overlay_widget'):
            self.overlay_widget = FloatingOverlayWidget(self)
        use_widget = self.config.get("show_floating_widget", False)
        hk = self.config.get("hotkey", "f9")

        # Validate the hotkey BEFORE touching the working hooks - a typo must
        # never silently kill push-to-talk. Unknown keys revert to F9.
        if not use_widget and hk:
            try:
                keyboard.key_to_scan_codes(hk)
            except Exception:
                hk = "f9"
                self.config["hotkey"] = "f9"
                save_config(self.config)
                self.hotkey_input.blockSignals(True)
                self.hotkey_input.setText("f9")
                self.hotkey_input.blockSignals(False)
                self.set_status("status_bad_hotkey", True)

        # on_press_key/on_release_key return hook handles - remove them with
        # keyboard.unhook() (remove_hotkey only works for add_hotkey entries).
        if self.press_hook:
            try: keyboard.unhook(self.press_hook)
            except Exception as e: logging.debug(f"Failed to unhook press: {e}")
            self.press_hook = None
        if self.release_hook:
            try: keyboard.unhook(self.release_hook)
            except Exception as e: logging.debug(f"Failed to unhook release: {e}")
            self.release_hook = None

        if use_widget:
            self.overlay_widget.show()
            pos = self.config.get("overlay_pos")
            if isinstance(pos, list) and len(pos) == 2:
                self.overlay_widget.move(int(pos[0]), int(pos[1]))
            else:
                screen = QApplication.primaryScreen().geometry()
                self.overlay_widget.move((screen.width() - 56) // 2, 40)
        else:
            self.overlay_widget.hide()
            try:
                if hk:
                    self.press_hook = keyboard.on_press_key(hk, lambda e: self.hotkey_pressed_signal.emit(), suppress=False)
                    self.release_hook = keyboard.on_release_key(hk, lambda e: self.hotkey_released_signal.emit(), suppress=False)
            except Exception as e:
                logging.error(f"Failed to register hotkeys: {e}")
                self.set_status("status_bad_hotkey", True)

    def toggle_floating_widget_vis(self):
        self.config["show_floating_widget"] = not self.config.get("show_floating_widget", False)
        self.floating_check.setChecked(self.config["show_floating_widget"])
        save_config(self.config)
        self.setup_floating_widget_and_hotkey()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self.tray_icon.showMessage(self.tr("tray_msg_title"), self.tr("tray_msg_body"), QSystemTrayIcon.MessageIcon.Information, 2000)

    def force_quit(self):
        for hook in (self.press_hook, self.release_hook):
            if hook:
                try: keyboard.unhook(hook)
                except Exception: pass

        # Stop an active recording first so PortAudio isn't torn down mid-callback
        if self.stream:
            try:
                self.is_recording = False
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        worker = getattr(self, "worker", None)
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(2500)
                    if worker.isRunning():
                        # A hung HTTP call can't be interrupted politely; terminate
                        # is unsafe in general but acceptable right before process exit.
                        logging.warning("Worker still running at exit; terminating.")
                        worker.terminate()
                        worker.wait(1000)
            except RuntimeError:
                pass  # worker's C++ object was already deleted

        QApplication.instance().quit()

    def handle_hotkey_press(self):
        if not self.config.get("show_floating_widget", False) and not self.is_recording and not self.is_processing:
            self.start_audio_stream(copy_only=False)

    def handle_hotkey_release(self):
        if not self.config.get("show_floating_widget", False) and self.is_recording:
            self.stop_audio_stream_and_process()

    def toggle_recording(self, copy_only=False):
        if self.is_processing: return
        if not self.is_recording:
            self.start_audio_stream(copy_only=copy_only)
        else:
            self.stop_audio_stream_and_process()

    def start_audio_stream(self, copy_only=False):
        if self.is_processing: return

        # A global hotkey doesn't blur the key field - sync what's on screen first
        if hasattr(self, "api_input"):
            self.config.setdefault("keys", {})[self.config.get("provider", "groq")] = self.api_input.text().strip()

        if not self.current_keys():
            self.set_status("status_no_api", True)
            return

        with self.audio_lock:
            self.audio_data = []
            self.recorded_frames = 0
            self.limit_reached = False

        def callback(indata, frames, time_info, status):
            if self.is_recording:
                with self.audio_lock:
                    if self.recorded_frames < self.max_frames:
                        self.audio_data.append(indata.copy())
                        self.recorded_frames += frames
                        if self.recorded_frames >= self.max_frames:
                            self.limit_reached = True
                            # Auto-stop via signal - this runs on the PortAudio thread.
                            self.recording_limit_signal.emit()
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', callback=callback, device=self.resolve_device())
            self.stream.start()
            self.is_recording = True
            self.is_copy_only = copy_only
            self.set_status("status_recording")
            self.overlay_widget.update_rec_status(True)
        except Exception as e:
            logging.error(f"Audio stream error: {e}")
            if self.stream:
                try: self.stream.close()
                except Exception: pass
            self.stream = None
            self.is_recording = False
            self.set_status("status_no_mic", True)

    def stop_audio_stream_and_process(self):
        if not self.is_recording: return
        self.is_recording = False

        if self.limit_reached:
            self.limit_reached = False
            logging.warning("Recording auto-stopped at the maximum duration limit.")

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logging.error(f"Error closing stream: {e}")
            self.stream = None
        self.overlay_widget.update_rec_status(False)
        with self.audio_lock:
            audio_payload = self.audio_data
            self.audio_data = []
            recorded = self.recorded_frames
        # Minimum length in FRAMES, not callback chunks (chunk size is device-dependent)
        if not audio_payload or recorded < SAMPLE_RATE // 2:  # less than 0.5s of audio
            self.set_status("status_ready")
            return
        self.is_processing = True
        self.set_status("status_processing")

        # Build the provider failover chain: current provider first, then (if
        # auto failover is enabled) the other provider if it has a key saved.
        chain = []
        cur = self.config.get("provider", "groq")
        ordered = [cur] + [p for p in PROVIDERS if p != cur]
        for p in ordered:
            keys = parse_api_keys(self.config.get("keys", {}).get(p, ""))
            if not keys:
                continue
            chain.append({"provider": p, "keys": keys, "model": self.current_model(p)})
            if not self.config.get("auto_provider_failover", True):
                break  # only the current provider when failover is disabled

        logging.warning(f"Failover chain for this request: {[c['provider'] for c in chain]}")
        if not chain:
            self.is_processing = False
            self.set_status("status_no_api", True)
            return

        self.worker = AudioWorker(
            audio_payload,
            chain,
            self.config.get("speech_lang", "auto"),
            copy_only=self.is_copy_only
        )
        self.worker.finished_signal.connect(self.on_transcribe_success)
        self.worker.error_signal.connect(self.on_transcribe_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def on_transcribe_success(self, text, copy_only, via_label):
        self.is_processing = False
        if text:
            logging.warning(f"Transcription OK via {via_label} ({len(text)} chars)")
        if not text:
            self.set_status("status_ready")
            return
        current_label = PROVIDERS[self.config.get("provider", "groq")]["label"]
        suffix = self.tr("via_suffix").format(via_label) if via_label and via_label != current_label else ""
        if copy_only or QApplication.activeWindow() == self:
            pyperclip.copy(text)
            self.set_status("status_copied")
        else:
            try: old_clip = pyperclip.paste()
            except Exception: old_clip = ""
            pyperclip.copy(text)

            def restore_clipboard(old, pasted):
                try:
                    if old and pyperclip.paste() == pasted:
                        pyperclip.copy(old)
                except Exception as e:
                    logging.error(f"Clipboard restore failed: {e}")
            QTimer.singleShot(50, lambda: keyboard.send("ctrl+v"))
            QTimer.singleShot(750, lambda: restore_clipboard(old_clip, text))
            self.set_status("status_pasted")
        if suffix:
            self.status_label.setText(self.status_label.text() + suffix)

    def on_transcribe_error(self, err_msg):
        self.is_processing = False
        raw = str(err_msg)  # already key-scrubbed by the worker
        err_str = raw.lower()
        logging.error(f"Transcription error: {raw}")

        if err_str.startswith("all_keys_failed"):
            # Classify the underlying reason so the user sees WHAT failed and why
            inner = err_str.split(":", 1)[1].strip() if ":" in err_str else ""
            if any(x in inner for x in ("401", "invalid_api_key", "incorrect api key", "invalid api key", "api key not valid")):
                self.set_status("status_invalid_key", True)
            elif any(x in inner for x in ("429", "quota", "credit", "rate limit", "limit exceeded", "exceeded", "insufficient")):
                self.set_status("status_quota", True)
            elif any(x in inner for x in ("503", "unavailable", "overloaded", "high demand", "capacity")):
                self.set_status("status_overloaded", True)
            elif any(x in inner for x in ("403", "network", "connection", "timeout", "access denied")):
                self.set_status("network_err", True)
            else:
                self.set_status("status_all_keys_failed", True, inner[:40])
            return

        if any(x in err_str for x in ("401", "invalid_api_key", "incorrect api key", "invalid api key", "api key not valid")):
            self.set_status("status_invalid_key", True)
        elif any(x in err_str for x in ("429", "quota", "credit", "rate limit", "limit exceeded", "exceeded", "insufficient")):
            self.set_status("status_quota", True)
        elif any(x in err_str for x in ("503", "unavailable", "overloaded", "high demand", "capacity")):
            self.set_status("status_overloaded", True)
        elif any(x in err_str for x in ("403", "network", "connection", "timeout", "access denied")):
            self.set_status("network_err", True)
        else:
            self.set_status("status_error", True, raw[:30] + "...")


if __name__ == "__main__":
    # Single-instance guard: a second instance would double the global hotkey
    # hooks, the recordings, and the quota usage.
    ctypes.windll.kernel32.CreateMutexW(None, False, "TirdadFlow_SingleInstanceMutex")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)

    app = QApplication(sys.argv)
    load_custom_fonts()
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
