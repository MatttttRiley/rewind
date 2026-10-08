#!/usr/bin/env python3
"""Rewind - a local Recall-style timeline. Everything stays on your PC.

common.py - shared paths, config, and database layer.
"""

import json
import os
import sqlite3
import sys

APP_NAME = "Rewind"


def data_dir():
    """Per-user local data dir (Windows: %APPDATA%, else ~/.rewind)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, APP_NAME)
    else:
        d = os.path.join(os.path.expanduser("~"), ".rewind")
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "shots"), exist_ok=True)
    return d


def db_path():
    return os.path.join(data_dir(), "timeline.db")


DEFAULT_CONFIG = {
    "interval_sec": 10,       # screenshot cadence
    "shot_width": 1280,       # downscale width (px)
    "jpeg_quality": 60,
    "min_change": 0.02,       # skip if <2% of pixels changed
    "retention_days": 30,
    "max_disk_mb": 2048,
    "paused": False,
    "ocr": True,
}


def config_path():
    return os.path.join(data_dir(), "config.json")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path(), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,              -- unix timestamp
    date TEXT NOT NULL,            -- YYYY-MM-DD (local)
    shot_path TEXT NOT NULL,       -- relative path under shots/
    app TEXT DEFAULT '',           -- foreground window title (best effort)
    ocr_text TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_snap_date ON snapshots(date);

CREATE VIRTUAL TABLE IF NOT EXISTS snapshots_fts
USING fts5(ocr_text, app, content='snapshots', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS snap_ai AFTER INSERT ON snapshots BEGIN
    INSERT INTO snapshots_fts(rowid, ocr_text, app)
    VALUES (new.id, new.ocr_text, new.app);
END;
CREATE TRIGGER IF NOT EXISTS snap_ad AFTER DELETE ON snapshots BEGIN
    INSERT INTO snapshots_fts(snapshots_fts, rowid, ocr_text, app)
    VALUES ('delete', old.id, old.ocr_text, old.app);
END;
"""


def connect():
    con = sqlite3.connect(db_path())
    con.execute("PRAGMA journal_mode=WAL;")
    con.executescript(SCHEMA)
    return con


def add_snapshot(ts, date, shot_relpath, app_title="", ocr_text=""):
    con = connect()
    cur = con.execute(
        "INSERT INTO snapshots (ts, date, shot_path, app, ocr_text)"
        " VALUES (?,?,?,?,?)",
        (ts, date, shot_relpath, app_title, ocr_text),
    )
    sid = cur.lastrowid
    con.commit()
    con.close()
    return sid


def search(query, limit=100):
    """Full-text search over OCR text + app titles, newest first."""
    con = connect()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT s.id, s.ts, s.date, s.shot_path, s.app,
                  substr(s.ocr_text, 1, 200) AS snippet
           FROM snapshots_fts f
           JOIN snapshots s ON s.id = f.rowid
           WHERE snapshots_fts MATCH ?
           ORDER BY s.ts DESC LIMIT ?""",
        (query, limit),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def timeline(date, limit=2000):
    """All snapshots for a local date, oldest first (for scrubbing)."""
    con = connect()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ts, shot_path, app FROM snapshots"
        " WHERE date = ? ORDER BY ts ASC LIMIT ?",
        (date, limit),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def dates_with_data(limit=90):
    con = connect()
    rows = con.execute(
        "SELECT date, COUNT(*) c FROM snapshots GROUP BY date"
        " ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    return [(r[0], r[1]) for r in rows]


def get_snapshot(sid):
    con = connect()
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM snapshots WHERE id = ?", (sid,)).fetchone()
    con.close()
    return dict(r) if r else None


def prune(retention_days, max_disk_mb):
    """Delete old snapshots; enforce disk cap. Returns # deleted."""
    import time
    cutoff = time.time() - retention_days * 86400
    con = connect()
    old = con.execute("SELECT id, shot_path FROM snapshots WHERE ts < ?",
                      (cutoff,)).fetchall()
    deleted = _delete_ids(con, [r[0] for r in old])

    # disk cap: delete oldest until under budget
    shots_dir = os.path.join(data_dir(), "shots")
    def disk_mb():
        total = 0
        for _, _, files in os.walk(shots_dir):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(shots_dir, fn))
                except OSError:
                    pass
        return total / 1e6

    while disk_mb() > max_disk_mb:
        r = con.execute("SELECT id FROM snapshots ORDER BY ts ASC LIMIT 50").fetchall()
        if not r:
            break
        deleted += _delete_ids(con, [x[0] for x in r])

    con.execute("VACUUM;")
    con.commit()
    con.close()
    return deleted


def _delete_ids(con, ids):
    if not ids:
        return 0
    shots_dir = os.path.join(data_dir(), "shots")
    for (sid, rel) in con.execute(
            f"SELECT id, shot_path FROM snapshots WHERE id IN ({','.join('?'*len(ids))})",
            ids).fetchall():
        try:
            os.remove(os.path.join(shots_dir, rel))
        except OSError:
            pass
    con.execute(
        f"DELETE FROM snapshots WHERE id IN ({','.join('?'*len(ids))})", ids)
    con.commit()
    return len(ids)


def storage_stats():
    shots_dir = os.path.join(data_dir(), "shots")
    total = 0
    n = 0
    for _, _, files in os.walk(shots_dir):
        for fn in files:
            n += 1
            try:
                total += os.path.getsize(os.path.join(shots_dir, fn))
            except OSError:
                pass
    con = connect()
    count = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    con.close()
    return {"files": n, "bytes": total, "snapshots": count}
