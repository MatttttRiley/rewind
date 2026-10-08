# Rewind

A Recall-style timeline for your PC. It quietly takes a screenshot every few
seconds (only when the screen changes), reads the text in it, and lets you
search everything you saw — apps, websites, documents, chats.

**100% local. Nothing is ever uploaded anywhere.** All screenshots and the
search index live in `%APPDATA%\Rewind` on your PC.

## Features

- Automatic screenshots on screen change (configurable 5–60s)
- Full-text search over everything on screen (OCR via Tesseract)
- Timeline scrubber — drag through your day
- Per-day browsing, app/window titles captured
- Auto-cleanup: retention days + disk cap (default 30 days / 2 GB)
- Pause anytime from the viewer

## Install (Windows)

1. Download `Rewind.exe` from the latest Actions build artifact.
2. Run it. The recorder starts automatically and the timeline window opens.

Tesseract OCR is bundled — no extra installs.

## Settings

Open Settings in the viewer to change capture interval, retention, disk cap,
or turn OCR on/off. The recorder picks up changes within seconds.

## Run from source

```bash
pip install -r requirements.txt
# install Tesseract OCR and make sure `tesseract` is on PATH
python app.py
```

## Privacy

Screenshots may contain passwords, messages, and personal info. Rewind stores
them only on your local disk, unencrypted, in your user profile. Anyone with
access to your Windows account can open them. Pause or quit Rewind when doing
anything sensitive.
