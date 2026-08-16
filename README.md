# TirdadFlow 🎙️

**Free, open-source, portable AI voice typer for Windows** — bilingual (English / فارسی), dark & frameless.

Hold **F9** (or click the floating mic widget), speak, release — your words are transcribed by AI and pasted straight into whatever app you're using. No subscription. No account. Your own free API keys.

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-10b981)
![License](https://img.shields.io/badge/license-MIT-10b981)
![Python](https://img.shields.io/badge/python-3.10%2B-10b981)

> [🇮🇷 نسخه فارسی این راهنما](README.fa.md)

## ✨ Features

- **Push-to-talk** — global hotkey (F9) press-and-hold, or a floating always-on-top mic widget
- **100% free AI providers** — **Groq** (Whisper large-v3 / large-v3-turbo) and **Google Gemini** (Flash); bring your own free keys
- **Multi-key failover** — paste several comma-separated keys; exhausted quota? the next key is tried automatically
- **Auto provider failover** — if Groq's daily quota runs out, it falls back to Gemini on its own
- **Bilingual UI** — native English/Persian with full RTL support, one-click switch
- **Clipboard-safe** — auto-pastes and restores your previous clipboard content
- **Portable** — a single `.exe`; config and log files live next to it, nothing is installed
- **Private by design** — zero telemetry, audio lives in RAM only and is never written to disk ([details](SECURITY.md))
- **📋 Copy Log button** — one click copies diagnostics for easy bug reports

## 🚀 Quick Start

1. Download `TirdadFlow.exe` from [**Releases**](../../releases) (verify it with `SHA256SUMS.txt`).
2. Run it — no installation needed.
3. Paste a free API key (see below), hold **F9**, speak, release. Done.

### 🔑 Free API keys

| Provider | Get a free key | Notes |
|---|---|---|
| **Groq** (default, fastest) | [console.groq.com/keys](https://console.groq.com/keys) | Whisper large-v3 · may need a VPN in some regions |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | ⚠️ The free tier may use your data to improve Google products — the app warns you in-app |

- Multiple keys? Separate them with commas — automatic failover.
- Fill in both providers and enable **"Auto-switch provider"** for maximum uptime.

## 🛠️ Run from source

```bat
pip install -r requirements.txt
python whisper_flow.py
```

## 📦 Build the portable exe

```bat
pyinstaller --noconsole --onefile --clean --name "TirdadFlow" --collect-binaries _sounddevice_data --collect-submodules sounddevice whisper_flow.py
```

Output: `dist\TirdadFlow.exe` — fully portable.

## 🔒 Security & Privacy

Plaintext config (portability trade-off), why the global keyboard hook exists, clipboard handling, and the full data flow — all documented in [SECURITY.md](SECURITY.md).

**Never commit `tirdad_flow_config.json`** — it contains your API keys (it's covered by `.gitignore`).

## ☕ Support

Telegram: [t.me/ProfileTradingHub](https://t.me/ProfileTradingHub)

## License

MIT — see [LICENSE](LICENSE).
