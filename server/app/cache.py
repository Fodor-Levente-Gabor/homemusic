"""Audio cache: download on demand, loudness measurement, least-played-first eviction."""
import logging
import queue
import threading
import time
from pathlib import Path

from . import loudness
from .db import now

log = logging.getLogger("cache")
GRACE_DAYS = 14
EVICT_TARGET = 0.9


class Cache:
    def __init__(self, cfg, db, downloader, settings, lib):
        self.cfg, self.db, self.dl, self.settings, self.lib = cfg, db, downloader, settings, lib
        self._locks: dict[str, threading.Lock] = {}
        self._glock = threading.Lock()
        self._evict_lock = threading.Lock()
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)

    # -------- background prefetch worker
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="prefetch", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _worker(self):
        while not self._stop.is_set():
            try:
                vid = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.ensure(vid)
            except Exception as e:  # noqa: BLE001
                log.info("prefetch %s failed: %s", vid, e)
            if self.cfg.download_delay_s:
                self._stop.wait(self.cfg.download_delay_s)

    def prefetch(self, ids):
        n = 0
        for v in ids:
            t = self.lib.get_track(v)
            if not (t and t["cached"]):
                self._q.put(v)
                n += 1
        return n

    # -------- on-demand
    def file_for(self, vid: str):
        with self.db.conn() as c:
            r = c.execute("SELECT file_path FROM tracks WHERE video_id=?", (vid,)).fetchone()
        return Path(r["file_path"]) if r and r["file_path"] else None

    def ensure(self, vid: str) -> dict:
        with self._glock:
            lock = self._locks.setdefault(vid, threading.Lock())
        with lock:
            p = self.file_for(vid)
            if p and p.exists():
                return self.lib.get_track(vid)
            with self.db.conn() as c:
                c.execute("INSERT OR IGNORE INTO tracks(video_id,first_seen_at) VALUES(?,?)", (vid, now()))
                c.execute("UPDATE tracks SET dl_state='downloading', file_path=NULL, file_size=0 WHERE video_id=?", (vid,))
            try:
                path = Path(self.dl.download(vid, self.cfg.cache_dir))
            except Exception as e:  # noqa: BLE001
                with self.db.conn() as c:
                    c.execute("UPDATE tracks SET dl_state='error', dl_error=? WHERE video_id=?", (str(e)[:300], vid))
                raise
            m = loudness.measure(str(path))
            lufs, peak = (m if m else (None, None))
            gain = loudness.gain_for(lufs, peak, float(self.settings.get("target_lufs"))) if m else 0.0
            with self.db.conn() as c:
                c.execute("""UPDATE tracks SET file_path=?, file_size=?, downloaded_at=?, dl_state='ready', dl_error=NULL,
                             loudness_lufs=?, true_peak=?, gain_db=? WHERE video_id=?""",
                          (str(path), path.stat().st_size, now(), lufs, peak, gain, vid))
            self.evict(exclude={vid})
            return self.lib.get_track(vid)

    def regain(self):
        """Recompute stored gains after the target loudness changed."""
        target = float(self.settings.get("target_lufs"))
        with self.db.conn() as c:
            for r in c.execute("SELECT video_id,loudness_lufs,true_peak FROM tracks WHERE loudness_lufs IS NOT NULL").fetchall():
                c.execute("UPDATE tracks SET gain_db=? WHERE video_id=?",
                          (loudness.gain_for(r["loudness_lufs"], r["true_peak"] or 0.0, target), r["video_id"]))

    # -------- accounting / eviction
    def used_bytes(self) -> int:
        with self.db.conn() as c:
            return c.execute("SELECT COALESCE(SUM(file_size),0) s FROM tracks WHERE file_path IS NOT NULL").fetchone()["s"]

    def limit_bytes(self) -> int:
        return int(float(self.settings.get("cache_limit_gb")) * 1024 ** 3)

    def usage(self) -> dict:
        with self.db.conn() as c:
            n = c.execute("SELECT COUNT(*) n FROM tracks WHERE file_path IS NOT NULL").fetchone()["n"]
        return {"used_bytes": self.used_bytes(), "limit_bytes": self.limit_bytes(), "files": n}

    def _drop(self, vid, path):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
        with self.db.conn() as c:   # metadata, stats and lyrics stay; file_path NULL => re-download on next play
            c.execute("UPDATE tracks SET file_path=NULL, file_size=0, dl_state='none' WHERE video_id=?", (vid,))

    def evict(self, exclude=()):
        with self._evict_lock:
            used, limit = self.used_bytes(), self.limit_bytes()
            if used <= limit:
                return []
            target = int(limit * EVICT_TARGET)
            grace_cut = now() - GRACE_DAYS * 86400
            removed = []
            for use_grace in (True, False):
                with self.db.conn() as c:
                    rows = c.execute("""SELECT video_id,file_path,file_size,downloaded_at FROM tracks
                        WHERE file_path IS NOT NULL AND pinned=0
                        ORDER BY play_count ASC, COALESCE(last_played_at,0) ASC, COALESCE(downloaded_at,0) ASC""").fetchall()
                for r in rows:
                    if used <= target:
                        break
                    if r["video_id"] in exclude or r["video_id"] in removed:
                        continue
                    if use_grace and (r["downloaded_at"] or 0) >= grace_cut:
                        continue
                    self._drop(r["video_id"], r["file_path"])
                    used -= r["file_size"]
                    removed.append(r["video_id"])
                if used <= target:
                    break
            log.info("evicted %d files", len(removed))
            return removed

    def pin(self, vid: str, pinned: bool):
        with self.db.conn() as c:
            c.execute("UPDATE tracks SET pinned=? WHERE video_id=?", (1 if pinned else 0, vid))

    def delete(self, vid: str):
        p = self.file_for(vid)
        if p:
            self._drop(vid, p)

    def reconcile(self):
        """Repair DB <-> disk drift."""
        with self.db.conn() as c:
            rows = c.execute("SELECT video_id,file_path FROM tracks WHERE file_path IS NOT NULL").fetchall()
            for r in rows:
                if not Path(r["file_path"]).exists():
                    c.execute("UPDATE tracks SET file_path=NULL, file_size=0, dl_state='none' WHERE video_id=?", (r["video_id"],))
        known = {Path(r["file_path"]).name for r in rows}
        for p in self.cfg.cache_dir.glob("*"):
            if p.is_file() and p.name not in known and p.suffix not in (".part", ".ytdl", ".tmp"):
                with self.db.conn() as c:
                    t = c.execute("SELECT video_id FROM tracks WHERE video_id=?", (p.stem,)).fetchone()
                    if t:
                        c.execute("UPDATE tracks SET file_path=?, file_size=?, dl_state='ready', downloaded_at=COALESCE(downloaded_at,?) WHERE video_id=?",
                                  (str(p), p.stat().st_size, now(), p.stem))
