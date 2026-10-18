"""Helyi lejátszási listák + a YT Music felé menő változtatások sorba állítása."""
import json
from typing import Any

from .db import Database, now


def enqueue(c, action: str, payload: dict[str, Any]) -> None:
    c.execute("INSERT INTO sync_queue(action,payload_json,created_at) VALUES(?,?,?)",
              (action, json.dumps(payload), now()))


class Playlists:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[dict[str, Any]]:
        with self.db.conn() as c:
            rows = c.execute(
                """SELECT p.*, (SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id=p.id) AS count,
                          (SELECT t.thumbnail FROM playlist_items i JOIN tracks t ON t.video_id=i.video_id
                            WHERE i.playlist_id=p.id AND t.thumbnail IS NOT NULL ORDER BY i.position LIMIT 1) AS first_thumb
                   FROM playlists p ORDER BY p.title COLLATE NOCASE""").fetchall()
        return [{"id": r["id"], "ytm_id": r["ytm_id"], "title": r["title"], "description": r["description"],
                 "thumbnail": r["thumbnail"] or r["first_thumb"], "kind": r["kind"], "count": r["count"]} for r in rows]

    def get(self, pid: int) -> dict[str, Any] | None:
        with self.db.conn() as c:
            p = c.execute("SELECT * FROM playlists WHERE id=?", (pid,)).fetchone()
            if not p:
                return None
            items = c.execute(
                "SELECT i.position, t.* FROM playlist_items i LEFT JOIN tracks t ON t.video_id=i.video_id "
                "WHERE i.playlist_id=? ORDER BY i.position", (pid,)).fetchall()
        from .db import row_to_track
        tracks = []
        for r in items:
            if r["video_id"] is None:
                continue
            d = row_to_track(r)
            d.pop("position", None)
            tracks.append(d)
        return {"id": p["id"], "ytm_id": p["ytm_id"], "title": p["title"], "description": p["description"],
                "kind": p["kind"], "tracks": tracks}

    def create(self, title: str, description: str = "", video_ids: list[str] | None = None) -> int:
        video_ids = video_ids or []
        with self.db.conn() as c:
            cur = c.execute("INSERT INTO playlists(title,description,updated_at) VALUES(?,?,?)",
                            (title, description, now()))
            pid = cur.lastrowid
            for i, v in enumerate(video_ids):
                c.execute("INSERT INTO playlist_items(playlist_id,position,video_id) VALUES(?,?,?)", (pid, i, v))
            enqueue(c, "create_playlist", {"local_id": pid, "title": title, "description": description})
            if video_ids:
                enqueue(c, "add_items", {"local_id": pid, "video_ids": video_ids})
        return pid

    def _guard_writable(self, c, pid: int):
        p = c.execute("SELECT * FROM playlists WHERE id=?", (pid,)).fetchone()
        if p is None:
            raise KeyError("nincs ilyen lista")
        if p["kind"] != "user":
            raise PermissionError("ez nem a te listád, csak olvasható")
        return p

    def add_items(self, pid: int, video_ids: list[str]) -> None:
        with self.db.conn() as c:
            self._guard_writable(c, pid)
            pos = c.execute("SELECT COALESCE(MAX(position)+1,0) p FROM playlist_items WHERE playlist_id=?", (pid,)).fetchone()["p"]
            for v in video_ids:
                c.execute("INSERT INTO playlist_items(playlist_id,position,video_id) VALUES(?,?,?)", (pid, pos, v))
                pos += 1
            c.execute("UPDATE playlists SET updated_at=? WHERE id=?", (now(), pid))
            enqueue(c, "add_items", {"local_id": pid, "video_ids": video_ids})

    def remove_items(self, pid: int, video_ids: list[str]) -> None:
        with self.db.conn() as c:
            self._guard_writable(c, pid)
            rows = c.execute("SELECT position,video_id FROM playlist_items WHERE playlist_id=? ORDER BY position", (pid,)).fetchall()
            want = list(video_ids)
            keep = []
            removed = []
            for r in rows:
                if r["video_id"] in want:
                    want.remove(r["video_id"])
                    removed.append(r["video_id"])
                else:
                    keep.append(r["video_id"])
            c.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            for i, v in enumerate(keep):
                c.execute("INSERT INTO playlist_items(playlist_id,position,video_id) VALUES(?,?,?)", (pid, i, v))
            c.execute("UPDATE playlists SET updated_at=? WHERE id=?", (now(), pid))
            if removed:
                enqueue(c, "remove_items", {"local_id": pid, "video_ids": removed})

    def rename(self, pid: int, title: str) -> None:
        with self.db.conn() as c:
            self._guard_writable(c, pid)
            c.execute("UPDATE playlists SET title=?,updated_at=? WHERE id=?", (title, now(), pid))
            enqueue(c, "rename_playlist", {"local_id": pid, "title": title})

    def delete(self, pid: int) -> None:
        with self.db.conn() as c:
            p = c.execute("SELECT * FROM playlists WHERE id=?", (pid,)).fetchone()
            if p is None:
                return
            c.execute("DELETE FROM playlists WHERE id=?", (pid,))
            if p["kind"] == "user" and p["ytm_id"]:
                enqueue(c, "delete_playlist", {"ytm_id": p["ytm_id"]})
            # ha még nem is jutott fel, a függő műveleteit töröljük
            if not p["ytm_id"]:
                for r in c.execute("SELECT id,payload_json FROM sync_queue").fetchall():
                    if json.loads(r["payload_json"]).get("local_id") == pid:
                        c.execute("DELETE FROM sync_queue WHERE id=?", (r["id"],))

    def set_liked(self, video_id: str, liked: bool) -> None:
        with self.db.conn() as c:
            c.execute("UPDATE tracks SET liked=? WHERE video_id=?", (1 if liked else 0, video_id))
            enqueue(c, "rate", {"video_id": video_id, "liked": liked})

    def queue_history(self, video_id: str) -> None:
        with self.db.conn() as c:
            enqueue(c, "history", {"video_id": video_id})
