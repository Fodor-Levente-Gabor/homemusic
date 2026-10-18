import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks(
  video_id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', artist TEXT NOT NULL DEFAULT '',
  artists_json TEXT NOT NULL DEFAULT '[]', album TEXT NOT NULL DEFAULT '', album_id TEXT,
  duration_sec INTEGER, thumbnail TEXT, first_seen_at INTEGER NOT NULL DEFAULT 0,
  file_path TEXT, file_size INTEGER NOT NULL DEFAULT 0, loudness_lufs REAL, true_peak REAL, gain_db REAL,
  play_count INTEGER NOT NULL DEFAULT 0, last_played_at INTEGER, downloaded_at INTEGER,
  dl_state TEXT NOT NULL DEFAULT 'none', dl_error TEXT,
  liked INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lyrics(video_id TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT 'manual', updated_at INTEGER);
CREATE TABLE IF NOT EXISTS lyric_lines(video_id TEXT NOT NULL, idx INTEGER NOT NULL, t INTEGER, text TEXT NOT NULL,
  PRIMARY KEY(video_id, idx));
CREATE TABLE IF NOT EXISTS play_events(id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, started_at INTEGER,
  device_id TEXT, listened_sec REAL NOT NULL DEFAULT 0, counted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS playlists(id INTEGER PRIMARY KEY AUTOINCREMENT, ytm_id TEXT, title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', thumbnail TEXT, kind TEXT NOT NULL DEFAULT 'user', updated_at INTEGER);
CREATE TABLE IF NOT EXISTS playlist_items(playlist_id INTEGER NOT NULL, position INTEGER NOT NULL, video_id TEXT NOT NULL,
  PRIMARY KEY(playlist_id, position));
CREATE TABLE IF NOT EXISTS sync_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at INTEGER, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artists(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(token_hash TEXT PRIMARY KEY, created_at INTEGER);
"""


def now() -> int:
    return int(time.time())


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()


def row_to_track(r):
    if r is None:
        return None
    d = dict(r)
    return {
        "video_id": d["video_id"], "title": d.get("title") or "", "artist": d.get("artist") or "",
        "artists": json.loads(d.get("artists_json") or "[]"), "album": d.get("album") or "", "album_id": d.get("album_id"),
        "duration_sec": d.get("duration_sec"), "thumbnail": d.get("thumbnail"),
        "cached": bool(d.get("file_path")), "file_size": d.get("file_size") or 0,
        "loudness_lufs": d.get("loudness_lufs"), "gain_db": d.get("gain_db") or 0.0,
        "play_count": d.get("play_count") or 0, "last_played_at": d.get("last_played_at"),
        "liked": bool(d.get("liked")), "pinned": bool(d.get("pinned")), "dl_state": d.get("dl_state") or "none",
    }
