# TirdadFlow Security & Trust Guide

Thank you for choosing and reviewing **TirdadFlow**! Transparency is key in open-source software, especially when dealing with hotkeys, clipboards, and voice data.

## 1. The Global Hotkey & Antivirus False Positives

TirdadFlow uses the Python `keyboard` library to let you start and stop voice recording instantly with a global hotkey (like `F9`), even while you are inside a game, a browser, or a full-screen application.

- **Why AV may flag it:** global hotkey listening uses the same low-level Windows APIs as "keyloggers", so strict antivirus engines (like Windows Defender) might flag the resulting `.exe` as suspicious.
- **The truth:** TirdadFlow ONLY monitors the exact single key you define in settings (e.g. `F9`). It NEVER records, stores, or transmits your general keystrokes. Verify by checking the `keyboard.on_press_key` hooks in the source.
- **Trust tip:** every release is built automatically by GitHub Actions from the tagged source, and ships with `SHA256SUMS.txt`. You can verify your exe matches the public build — or build it yourself with PyInstaller for maximum peace of mind.

## 2. Plaintext API Key(s) & Portability

TirdadFlow is designed to be **100% portable**: drop it on a USB stick and use it on any Windows PC without installation.

- The config file (`tirdad_flow_config.json`) is kept in plain text right next to the executable.
- **Trade-off:** your API key(s) are saved in plain text. Treat the TirdadFlow folder like a password file. Do not upload the `.json` to public repositories (it is covered by `.gitignore`) or share it.
- **Multiple keys:** you can store several comma-separated keys per provider for automatic failover — they all follow the same plaintext rule.
- **Log hygiene:** `tirdad_flow.log` never contains your API keys — only key *positions* (`key #1`, `key #2`) and provider names are logged, so the **Copy Log** button is always safe to share.

## 3. Voice Data Privacy

- No audio is ever written to disk. Audio lives in system RAM while you hold the hotkey, is converted to an in-memory `.wav`, sent over TLS to the selected provider, and discarded.
- TirdadFlow contains **zero telemetry**.
- **Groq:** audio goes only from your machine to Groq's Whisper API.
- **Google Gemini (free tier):** Google may use free-tier data to improve its products. The app shows a visible warning whenever Gemini is selected — use Groq for sensitive dictation.

## 4. Clipboard Safety

When auto-pasting, TirdadFlow copies your text, triggers `CTRL+V`, and restores your previous clipboard content within a fraction of a second — and only if the clipboard hasn't changed since (so it never clobbers something you copied in the meantime). Note: the restore is text-only; rich clipboard content (images, files) is not preserved.

## 5. Focus Guard

Before simulating `CTRL+V`, the app checks whether its own settings window is focused — so a transcript can never be pasted into your API key field (or anywhere inside TirdadFlow). In that case the text is only copied to the clipboard.

---

*Feel free to review the source and compile the executable yourself with PyInstaller for maximum peace of mind.*
