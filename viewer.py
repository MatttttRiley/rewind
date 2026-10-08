#!/usr/bin/env python3
"""Rewind viewer - search your timeline and scrub through the day."""

import datetime
import os
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

import common

BG = "#1a1d24"
PANEL = "#242832"
FG = "#e8eaf0"
MUTED = "#8b93a7"
ACCENT = "#2e7cf6"


class Viewer:
    def __init__(self, root):
        self.root = root
        root.title("Rewind - your timeline")
        root.geometry("1000x700")
        root.configure(bg=BG)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG,
                        font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Horizontal.TScale", background=BG)

        # -- top bar: search -------------------------------------------
        top = ttk.Frame(root)
        top.pack(fill="x", padx=15, pady=(12, 6))
        ttk.Label(top, text="Rewind", font=("Segoe UI", 16, "bold")).pack(
            side="left")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search_var, width=40)
        entry.pack(side="left", padx=(15, 6))
        entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(top, text="Search", command=self.do_search).pack(side="left")
        self.pause_var = tk.StringVar()
        self.pause_btn = ttk.Button(top, textvariable=self.pause_var,
                                    command=self.toggle_pause)
        self.pause_btn.pack(side="right")
        ttk.Button(top, text="Settings",
                   command=self.open_settings).pack(side="right", padx=(0, 8))
        self._refresh_pause()

        # -- date picker -----------------------------------------------
        date_row = ttk.Frame(root)
        date_row.pack(fill="x", padx=15, pady=4)
        ttk.Label(date_row, text="Day:").pack(side="left")
        self.date_var = tk.StringVar()
        self.date_box = ttk.Combobox(date_row, textvariable=self.date_var,
                                     state="readonly", width=14)
        self.date_box.pack(side="left", padx=(6, 0))
        self.date_box.bind("<<ComboboxSelected>>", lambda e: self.load_day())
        self.count_label = ttk.Label(date_row, text="", foreground=MUTED)
        self.count_label.pack(side="left", padx=(12, 0))
        stats = common.storage_stats()
        ttk.Label(date_row,
                  text=f"{stats['snapshots']} snapshots, "
                       f"{stats['bytes']/1e6:.0f} MB on disk",
                  foreground=MUTED).pack(side="right")

        # -- main split: results list + preview -------------------------
        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, padx=15, pady=6)

        left = ttk.Frame(mid)
        left.pack(side="left", fill="y")
        self.results = tk.Listbox(left, bg=PANEL, fg=FG, width=52,
                                  font=("Segoe UI", 9), relief="flat")
        self.results.pack(side="left", fill="y", expand=True)
        sb = tk.Scrollbar(left, command=self.results.yview)
        sb.pack(side="right", fill="y")
        self.results.config(yscrollcommand=sb.set)
        self.results.bind("<<ListboxSelect>>", self._on_select)

        right = ttk.Frame(mid)
        right.pack(side="right", fill="both", expand=True, padx=(10, 0))
        self.img_label = ttk.Label(right, text="Select a moment",
                                   foreground=MUTED, anchor="center")
        self.img_label.pack(fill="both", expand=True)
        self.meta_label = ttk.Label(right, text="", foreground=MUTED,
                                    wraplength=450)
        self.meta_label.pack(fill="x", pady=(6, 0))

        # -- timeline scrubber ------------------------------------------
        bot = ttk.Frame(root)
        bot.pack(fill="x", padx=15, pady=(0, 12))
        self.scrub_var = tk.DoubleVar(value=0)
        self.scrub = ttk.Scale(bot, variable=self.scrub_var,
                               from_=0, to=100, orient="horizontal",
                               command=self._on_scrub)
        self.scrub.pack(fill="x")
        self.time_label = ttk.Label(bot, text="", foreground=MUTED)
        self.time_label.pack()

        self.day_snaps = []   # timeline() rows for scrubber
        self.search_rows = []  # search() rows
        self._photo = None
        self._scrubbing = False

        self._reload_dates()
        self.root.after(30000, self._auto_refresh)

    # -- data ------------------------------------------------------------
    def _reload_dates(self):
        dates = common.dates_with_data()
        self.date_box["values"] = [f"{d} ({c})" for d, c in dates]
        if dates and not self.date_var.get():
            self.date_var.set(f"{dates[0][0]} ({dates[0][1]})")
            self.load_day()

    def _current_date(self):
        v = self.date_var.get()
        return v.split(" ")[0] if v else None

    def load_day(self):
        date = self._current_date()
        if not date:
            return
        self.day_snaps = common.timeline(date)
        self.count_label.config(text=f"{len(self.day_snaps)} moments")
        if self.day_snaps:
            self.scrub_var.set(0)
            self._show_snapshot(self.day_snaps[0])
        self._auto_refresh()

    def do_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        # FTS5: quote phrases, allow prefix with *
        terms = []
        for t in q.split():
            t = t.strip('"')
            if t:
                terms.append(f'"{t}"*')
        fts_q = " ".join(terms)
        try:
            self.search_rows = common.search(fts_q, limit=200)
        except Exception as e:
            messagebox.showerror("Search failed", str(e))
            return
        self.results.delete(0, "end")
        for r in self.search_rows:
            ts = datetime.datetime.fromtimestamp(r["ts"]).strftime(
                "%m-%d %H:%M")
            app = (r["app"] or "")[:40]
            self.results.insert("end", f"{ts}  {app}")
        if self.search_rows:
            self.results.selection_set(0)
            self._on_select()

    # -- display ----------------------------------------------------------
    def _on_select(self, _=None):
        sel = self.results.curselection()
        if not sel or not self.search_rows:
            return
        self._show_snapshot(self.search_rows[sel[0]])

    def _on_scrub(self, _=None):
        if not self.day_snaps or self._scrubbing:
            return
        idx = int(self.scrub_var.get() / 100 * (len(self.day_snaps) - 1))
        idx = max(0, min(idx, len(self.day_snaps) - 1))
        self._show_snapshot(self.day_snaps[idx])

    def _show_snapshot(self, row):
        sid = row["id"]
        full = common.get_snapshot(sid)
        if not full:
            return
        path = os.path.join(common.data_dir(), "shots", full["shot_path"])
        ts = datetime.datetime.fromtimestamp(full["ts"]).strftime(
            "%A %b %d, %I:%M:%S %p")
        try:
            img = Image.open(path)
            # fit into preview area (~560x460)
            img.thumbnail((560, 460))
            self._photo = ImageTk.PhotoImage(img)
            self.img_label.config(image=self._photo, text="")
        except Exception:
            self.img_label.config(image="", text="(screenshot missing)")
        app = full.get("app") or "(unknown app)"
        self.meta_label.config(text=f"{ts}\n{app}")
        # sync scrubber when browsing search results from same day
        if self.day_snaps:
            try:
                idx = next(i for i, s in enumerate(self.day_snaps)
                           if s["id"] == sid)
                self._scrubbing = True
                self.scrub_var.set(idx / max(1, len(self.day_snaps) - 1) * 100)
                self.time_label.config(
                    text=datetime.datetime.fromtimestamp(
                        full["ts"]).strftime("%I:%M %p"))
            except StopIteration:
                pass
            finally:
                self._scrubbing = False

    def _auto_refresh(self):
        self._reload_dates()
        stats = common.storage_stats()
        # light refresh; keep selection
        self.root.after(30000, self._auto_refresh)

    # -- pause / settings --------------------------------------------------
    def _refresh_pause(self):
        paused = common.load_config().get("paused", False)
        self.pause_var.set("Resume" if paused else "Pause")

    def toggle_pause(self):
        cfg = common.load_config()
        cfg["paused"] = not cfg.get("paused", False)
        common.save_config(cfg)
        self._refresh_pause()

    def open_settings(self):
        cfg = common.load_config()
        win = tk.Toplevel(self.root)
        win.title("Rewind settings")
        win.configure(bg=BG)
        win.geometry("380x340")

        def row(label, key, values):
            ttk.Label(win, text=label).pack(anchor="w", padx=15, pady=(10, 0))
            var = tk.StringVar(value=str(cfg.get(key)))
            box = ttk.Combobox(win, textvariable=var, values=values,
                               state="readonly", width=20)
            box.pack(anchor="w", padx=15)
            return var

        v_interval = row("Screenshot every", "interval_sec",
                         ["5", "10", "15", "30", "60"])
        v_retention = row("Keep history (days)", "retention_days",
                          ["7", "14", "30", "60", "90"])
        v_disk = row("Max disk use (MB)", "max_disk_mb",
                     ["512", "1024", "2048", "4096", "8192"])
        v_ocr = tk.BooleanVar(value=cfg.get("ocr", True))
        ttk.Checkbutton(win, text="Enable text search (OCR)",
                        variable=v_ocr).pack(anchor="w", padx=15, pady=10)

        def save():
            cfg["interval_sec"] = int(v_interval.get())
            cfg["retention_days"] = int(v_retention.get())
            cfg["max_disk_mb"] = int(v_disk.get())
            cfg["ocr"] = bool(v_ocr.get())
            common.save_config(cfg)
            messagebox.showinfo("Saved",
                                "Settings saved. The recorder picks them up "
                                "within a few seconds.")
            win.destroy()

        ttk.Button(win, text="Save", command=save).pack(pady=10)
        ttk.Label(win, text="All data stays on this PC.\n"
                            "Nothing is ever uploaded.",
                  foreground=MUTED).pack(padx=15, pady=5)


def main():
    root = tk.Tk()
    Viewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
