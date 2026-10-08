#!/usr/bin/env python3
"""Rewind recorder - background service.

Takes a screenshot every N seconds (only when the screen changed),
OCRs it, and stores it in the local timeline database.
Everything stays on this PC. Nothing is uploaded anywhere.
"""

import io
import os
import sys
import time
import datetime
import threading

from PIL import Image

import common

# ----------------------------------------------------------------------------
# Screenshot backend
# ----------------------------------------------------------------------------

def grab_screen():
    """Return a PIL Image of the primary monitor, or None."""
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]  # primary
            shot = sct.grab(mon)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception:
        pass
    try:
        # fallback (Windows/macOS)
        from PIL import ImageGrab
        return ImageGrab.grab()
    except Exception:
        return None


def active_window_title():
    """Best-effort foreground window title (Windows only)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# OCR backend
# ----------------------------------------------------------------------------

_tesseract_cmd = None

def _find_tesseract():
    global _tesseract_cmd
    if _tesseract_cmd:
        return _tesseract_cmd
    # 1) bundled next to the exe (PyInstaller)
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(sys.argv[0]))
    for cand in (os.path.join(base, "tesseract", "tesseract.exe"),
                 os.path.join(base, "tesseract.exe")):
        if os.path.isfile(cand):
            _tesseract_cmd = cand
            return cand
    # 2) system PATH
    import shutil
    found = shutil.which("tesseract")
    if found:
        _tesseract_cmd = found
        return found
    return None


def ocr_image(img):
    """Return extracted text ('' on any failure - OCR is best-effort)."""
    try:
        import pytesseract
        cmd = _find_tesseract()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        # upscale small text a bit for accuracy; keep it fast
        w, h = img.size
        if w < 1600:
            img = img.resize((int(w * 1.5), int(h * 1.5)))
        return pytesseract.image_to_string(img) or ""
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# Change detection
# ----------------------------------------------------------------------------

def _small_gray(img):
    return img.convert("L").resize((64, 36))


def changed_fraction(prev_small, img):
    """Returns (fraction_changed 0..1, small_gray_image)."""
    cur = _small_gray(img)
    if prev_small is None:
        return 1.0, cur
    a = list(prev_small.getdata())
    b = list(cur.getdata())
    diff = sum(1 for x, y in zip(a, b) if abs(x - y) > 12)
    return diff / len(a), cur


# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------

def downscale(img, width):
    w, h = img.size
    if w <= width:
        return img
    return img.resize((width, int(h * width / w)))


def run(stop_event=None):
    cfg = common.load_config()
    interval = max(5, int(cfg.get("interval_sec", 10)))
    width = int(cfg.get("shot_width", 1280))
    quality = int(cfg.get("jpeg_quality", 60))
    min_change = float(cfg.get("min_change", 0.02))
    do_ocr = bool(cfg.get("ocr", True))

    shots_dir = os.path.join(common.data_dir(), "shots")
    prev_small = None
    last_prune = 0

    print(f"[rewind] recorder started (every {interval}s, "
          f"{'paused' if cfg.get('paused') else 'active'})", flush=True)

    while not (stop_event and stop_event.is_set()):
        loop_start = time.time()
        try:
            cfg = common.load_config()  # pick up pause/config changes live
            if cfg.get("paused"):
                time.sleep(2)
                continue

            img = grab_screen()
            if img is None:
                time.sleep(2)
                continue

            frac, prev_small = changed_fraction(prev_small, img)
            if frac < max(0.0, min_change):
                continue  # screen barely changed; skip

            small = downscale(img, width)
            now = time.time()
            dt = datetime.datetime.fromtimestamp(now)
            date = dt.strftime("%Y-%m-%d")
            day_dir = os.path.join(shots_dir, date)
            os.makedirs(day_dir, exist_ok=True)
            fname = dt.strftime("%H%M%S") + ".jpg"
            # avoid collisions within the same second
            n = 1
            base = fname
            while os.path.exists(os.path.join(day_dir, fname)):
                n += 1
                fname = base.replace(".jpg", f"_{n}.jpg")
            full = os.path.join(day_dir, fname)
            small.save(full, "JPEG", quality=quality)

            text = ocr_image(small) if do_ocr else ""
            app = active_window_title()
            common.add_snapshot(now, date, os.path.join(date, fname),
                                app_title=app[:200], ocr_text=text[:20000])

            # prune once an hour
            if now - last_prune > 3600:
                common.prune(int(cfg.get("retention_days", 30)),
                             int(cfg.get("max_disk_mb", 2048)))
                last_prune = now

        except Exception as e:
            print(f"[rewind] loop error: {e}", flush=True)

        elapsed = time.time() - loop_start
        # sleep in small chunks so stop/pause reacts quickly
        for _ in range(int(interval * 2)):
            if stop_event and stop_event.is_set():
                break
            time.sleep(0.5)

    print("[rewind] recorder stopped", flush=True)


if __name__ == "__main__":
    run()
