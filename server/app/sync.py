"""Two-way sync with the YouTube Music account. Local changes are applied at once and queued in sync_queue;
push() sends them (in order, 5 attempts then dropped), pull() mirrors the account without clobbering pending edits."""
import json
import logging
import threading

from .db import now

log = logging.getLogger("sync")
MAX_ATTEMPTS = 5


class Sync:
    def __init__(self, db, ytm, lib, playlists, settings, on_change=None):
        self.db, self.ytm, self.lib, self.pl, self.settings = db, ytm, lib, playlists, settings
        self.on_change = on_change
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._kick = threading.Event()
        self.running = False
        self.last_result: dict | None = None

    def status(self) -> dict:
        with self.db.conn() as c:
            n = c.execute("SELECT COUNT(*) n FROM sync_queue").fetchone()["n"]
        return {"pending": n, "running": self.running, "last_result": self.last_result}

    # ------------------------------------------------------------------ push
    def push(self) -> int:
        if not self.ytm.available():
            return 0
        done = 0
        with self.db.conn() as c:
            ops = c.execute("SELECT * FROM sync_queue ORDER BY id").fetchall()
        for op in ops:
            try:
                self._do(op["action"], json.loads(op["payload_json"]))
            except Exception as e:  # noqa: BLE001
                log.warning("sync op %s failed: %s", op["action"], e)
                with self.db.conn() as c:
                    if op["attempts"] + 1 >= MAX_ATTEMPTS:
                        c.execute("DELETE FROM sync_queue WHERE id=?", (op["id"],))   # poison op: give up
                    else:
                        c.execute("UPDATE sync_queue SET attempts=attempts+1, last_error=? WHERE id=?", (str(e)[:300], op["id"]))
                break                                                                # keep ordering
            with self.db.conn() as c:
                c.execute("DELETE FROM sync_queue WHERE id=?", (op["id"],))
            done += 1
        return done

    def _ytm_id(self, local_id):
        with self.db.conn() as c:
            r = c.execute("SELECT ytm_id FROM playlists WHERE id=?", (local_id,)).fetchone()
        return r["ytm_id"] if r else None

    def _do(self, action, p):
        y = self.ytm
        if action == "create_playlist":
            with self.db.conn() as c:
                r = c.execute("SELECT description FROM playlists WHERE id=?", (p["local_id"],)).fetchone()
            if not r:
                return
            pid = y.create_playlist(p["title"], p.get("description", ""))
            with self.db.conn() as c:
                c.execute("UPDATE playlists SET ytm_id=? WHERE id=?", (pid, p["local_id"]))
        elif action in ("add_items", "remove_items", "rename_playlist"):
            yid = self._ytm_id(p["local_id"])
            if not yid:
                return
            if action == "add_items":
                y.add_items(yid, p["video_ids"])
            elif action == "remove_items":
                y.remove_items(yid, p["video_ids"])
            else:
                y.rename_playlist(yid, p["title"])
        elif action == "delete_playlist":
            y.delete_playlist(p["ytm_id"])
        elif action == "rate":
            y.rate(p["video_id"], p["liked"])
        elif action == "history":
            y.add_history(p["video_id"])

    # ------------------------------------------------------------------ pull
    def _pending(self):
        local, vids, ytm_ids = set(), set(), set()
        with self.db.conn() as c:
            for r in c.execute("SELECT action,payload_json FROM sync_queue"):
                p = json.loads(r["payload_json"])
                if "local_id" in p:
                    local.add(p["local_id"])
                if r["action"] == "rate":
                    vids.add(p["video_id"])
                if r["action"] == "delete_playlist":
                    ytm_ids.add(p["ytm_id"])
        return local, vids, ytm_ids

    def pull(self):
        if not self.ytm.available():
            return
        pend_local, pend_vids, pend_ytm = self._pending()
        remote = self.ytm.library_playlists()
        remote_ids = set()
        for rp in remote:
            yid = rp["id"]
            remote_ids.add(yid)
            if yid in pend_ytm:
                continue
            with self.db.conn() as c:
                loc = c.execute("SELECT id FROM playlists WHERE ytm_id=?", (yid,)).fetchone()
            if loc and loc["id"] in pend_local:
                continue
            try:
                data = self.ytm.playlist(yid)
            except Exception as e:  # noqa: BLE001
                log.warning("playlist %s pull failed: %s", yid, e)
                continue
            for t in data["tracks"]:
                self.lib.upsert_track(t)
            kind = "user" if data.get("owned") else "saved"
            with self.db.conn() as c:
                if loc:
                    pid = loc["id"]
                    c.execute("UPDATE playlists SET title=?, description=?, thumbnail=?, kind=?, updated_at=? WHERE id=?",
                              (data["title"] or rp["title"], data.get("description", ""), data.get("thumbnail") or rp.get("thumbnail"), kind, now(), pid))
                else:
                    pid = c.execute("INSERT INTO playlists(ytm_id,title,description,thumbnail,kind,updated_at) VALUES(?,?,?,?,?,?)",
                                    (yid, data["title"] or rp["title"], data.get("description", ""), data.get("thumbnail") or rp.get("thumbnail"), kind, now())).lastrowid
                c.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
                for i, t in enumerate(data["tracks"]):
                    c.execute("INSERT INTO playlist_items(playlist_id,position,video_id) VALUES(?,?,?)", (pid, i, t["video_id"]))
        with self.db.conn() as c:   # deleted on the account -> gone here (unless we have unsent edits for it)
            for r in c.execute("SELECT id,ytm_id FROM playlists WHERE ytm_id IS NOT NULL").fetchall():
                if r["ytm_id"] not in remote_ids and r["id"] not in pend_local:
                    c.execute("DELETE FROM playlist_items WHERE playlist_id=?", (r["id"],))
                    c.execute("DELETE FROM playlists WHERE id=?", (r["id"],))
        liked = self.ytm.liked_songs()
        for t in liked:
            self.lib.upsert_track(t)
        ids = {t["video_id"] for t in liked}
        with self.db.conn() as c:
            for r in c.execute("SELECT video_id,liked FROM tracks").fetchall():
                if r["video_id"] in pend_vids:
                    continue
                want = 1 if r["video_id"] in ids else 0
                if r["liked"] != want:
                    c.execute("UPDATE tracks SET liked=? WHERE video_id=?", (want, r["video_id"]))

    def run(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return self.status()
        try:
            self.running = True
            pushed = self.push()
            err = None
            try:
                self.pull()
            except Exception as e:  # noqa: BLE001
                log.exception("pull failed")
                err = str(e)[:300]
            self.last_result = {"at": now(), "ok": err is None, "error": err, "pushed": pushed}
            if self.on_change:
                self.on_change()
        finally:
            self.running = False
            self._lock.release()
        return self.status()

    # ------------------------------------------------------------------ background loop
    def kick(self):
        self._kick.set()

    def start(self):
        threading.Thread(target=self._loop, name="sync", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._kick.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.run()
            except Exception:  # noqa: BLE001
                log.exception("sync loop")
            self._kick.wait(timeout=max(60, int(self.settings.get("sync_interval_min")) * 60))
            self._kick.clear()
