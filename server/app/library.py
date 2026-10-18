"""Számok (tracks) kezelése: metaadat upsert, lekérdezés, lejátszásszámlálás."""
import json
from typing import Any

from .db import Database, now, row_to_track

# Ennyi másodperc (vagy a szám fele, amelyik kevesebb) után számít egy lejátszás "meghallgatottnak"
COUNT_AFTER_SEC = 30


def hi_res(url: str | None, size: int = 544) -> str | None:
    """A googleusercontent képek méretét az URL végén lehet kérni."""
    if not url:
        return url
    import re
    return re.sub(r"=w\d+-h\d+.*$", f"=w{size}-h{size}-l90-rj", url)


def normalize_track(t: dict[str, Any]) -> dict[str, Any] | None:
    """ytmusicapi eredményből egységes track dict. None, ha nincs videoId."""
    vid = t.get("videoId") or t.get("video_id")
    if not vid:
        return None
    artists = t.get("artists") or []
    names = [a["name"] if isinstance(a, dict) else str(a) for a in artists if a]
    if not names and t.get("artist"):
        names = [t["artist"]]
    album = t.get("album")
    album_name = album.get("name") if isinstance(album, dict) else (album or "")
    album_id = album.get("id") if isinstance(album, dict) else t.get("album_id")
    thumbs = t.get("thumbnails") or t.get("thumbnail") or []
    thumb = None
    if isinstance(thumbs, list) and thumbs:
        thumb = hi_res(thumbs[-1].get("url"))
    elif isinstance(thumbs, str):
        thumb = hi_res(thumbs)
    dur = t.get("duration_seconds") or t.get("duration_sec")
    dstr = t.get("duration") or t.get("length")
    if dur is None and isinstance(dstr, str) and ":" in dstr:
        parts = [int(p) for p in dstr.split(":") if p.isdigit()]
        dur = 0
        for p in parts:
            dur = dur * 60 + p
    return {
        "video_id": vid,
        "title": t.get("title") or "",
        "artist": ", ".join(names),
        "artists": names,
        "album": album_name or "",
        "album_id": album_id,
        "duration_sec": dur,
        "thumbnail": thumb,
    }


class Library:
    def __init__(self, db: Database):
        self.db = db

    def upsert_track(self, t: dict[str, Any]) -> str:
        n = normalize_track(t)
        if n is None:
            raise ValueError("no videoId")
        with self.db.conn() as c:
            c.execute(
                """INSERT INTO tracks(video_id,title,artist,artists_json,album,album_id,duration_sec,thumbnail,first_seen_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(video_id) DO UPDATE SET
                     title=CASE WHEN excluded.title!='' THEN excluded.title ELSE tracks.title END,
                     artist=CASE WHEN excluded.artist!='' THEN excluded.artist ELSE tracks.artist END,
                     artists_json=CASE WHEN excluded.artists_json!='[]' THEN excluded.artists_json ELSE tracks.artists_json END,
                     album=CASE WHEN excluded.album!='' THEN excluded.album ELSE tracks.album END,
                     album_id=COALESCE(excluded.album_id, tracks.album_id),
                     duration_sec=COALESCE(excluded.duration_sec, tracks.duration_sec),
                     thumbnail=COALESCE(excluded.thumbnail, tracks.thumbnail)""",
                (n["video_id"], n["title"], n["artist"], json.dumps(n["artists"]), n["album"],
                 n.get("album_id"), n.get("duration_sec"), n.get("thumbnail"), now()),
            )
        return n["video_id"]

    def get_track(self, video_id: str) -> dict[str, Any] | None:
        with self.db.conn() as c:
            return row_to_track(c.execute("SELECT * FROM tracks WHERE video_id=?", (video_id,)).fetchone())

    def get_tracks(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self.db.conn() as c:
            q = ",".join("?" * len(ids))
            rows = {r["video_id"]: r for r in c.execute(f"SELECT * FROM tracks WHERE video_id IN ({q})", ids)}
        return [row_to_track(rows[i]) for i in ids if i in rows]

    def top_tracks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.conn() as c:
            rows = c.execute(
                "SELECT * FROM tracks WHERE play_count>0 ORDER BY play_count DESC, last_played_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [row_to_track(r) for r in rows]

    def recent_tracks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.conn() as c:
            rows = c.execute(
                "SELECT * FROM tracks WHERE last_played_at IS NOT NULL ORDER BY last_played_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [row_to_track(r) for r in rows]

    def liked_tracks(self) -> list[dict[str, Any]]:
        with self.db.conn() as c:
            rows = c.execute("SELECT * FROM tracks WHERE liked=1 ORDER BY title").fetchall()
        return [row_to_track(r) for r in rows]

    # ---- lejátszási események ----
    def start_event(self, video_id: str, device_id: str | None) -> int:
        with self.db.conn() as c:
            cur = c.execute("INSERT INTO play_events(video_id,started_at,device_id) VALUES(?,?,?)",
                            (video_id, now(), device_id))
            return cur.lastrowid

    def progress_event(self, event_id: int, listened_sec: float) -> dict[str, Any]:
        """Frissíti a meghallgatott időt. Elérve a küszöböt, egyszer növeli a play_count-ot.
        Visszaadja, hogy most lett-e először 'counted' (ilyenkor kell YT Music előzményt küldeni)."""
        with self.db.conn() as c:
            ev = c.execute("SELECT * FROM play_events WHERE id=?", (event_id,)).fetchone()
            if ev is None:
                return {"counted_now": False}
            listened = max(ev["listened_sec"], listened_sec)
            tr = c.execute("SELECT duration_sec FROM tracks WHERE video_id=?", (ev["video_id"],)).fetchone()
            dur = tr["duration_sec"] if tr and tr["duration_sec"] else None
            threshold = min(COUNT_AFTER_SEC, dur / 2) if dur else COUNT_AFTER_SEC
            counted_now = False
            if not ev["counted"] and listened >= threshold:
                counted_now = True
                c.execute("UPDATE tracks SET play_count=play_count+1, last_played_at=? WHERE video_id=?",
                          (now(), ev["video_id"]))
            c.execute("UPDATE play_events SET listened_sec=?, counted=? WHERE id=?",
                      (listened, 1 if (ev["counted"] or counted_now) else 0, event_id))
            return {"counted_now": counted_now, "video_id": ev["video_id"]}

    def stats(self) -> dict[str, Any]:
        with self.db.conn() as c:
            r = c.execute(
                "SELECT COUNT(*) n, SUM(file_path IS NOT NULL) cached, COALESCE(SUM(file_size),0) bytes, "
                "COALESCE(SUM(play_count),0) plays FROM tracks").fetchone()
            ev = c.execute("SELECT COALESCE(SUM(listened_sec),0) s FROM play_events").fetchone()
        return {"tracks": r["n"], "cached_tracks": r["cached"] or 0, "cache_bytes": r["bytes"],
                "total_plays": r["plays"], "listened_hours": round(ev["s"] / 3600, 1)}

    # ---- helpers for API responses ----
    def ensure_rows(self, ids: list[str]) -> None:
        with self.db.conn() as c:
            for v in ids:
                c.execute("INSERT OR IGNORE INTO tracks(video_id,first_seen_at) VALUES(?,?)", (v, now()))

    def decorate_tracks(self, tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remember the tracks, return them with DB state (cached/liked/play_count/gain)."""
        ids = []
        for t in tracks:
            try:
                ids.append(self.upsert_track(t))
            except ValueError:
                pass
        return self.get_tracks(ids)

    def remember_artists(self, items: list[dict[str, Any]]) -> None:
        with self.db.conn() as c:
            for i in items:
                if i.get("type") == "artist" and i.get("id") and i.get("title"):
                    c.execute("INSERT INTO artists(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", (i["id"], i["title"]))

    def artist_name(self, cid: str) -> str | None:
        with self.db.conn() as c:
            r = c.execute("SELECT name FROM artists WHERE id=?", (cid,)).fetchone()
        return r["name"] if r else None

    def decorate(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.remember_artists(items)
        ids = [self.upsert_track(i) for i in items if i.get("type") == "track" and (i.get("video_id") or i.get("videoId"))]
        by = {t["video_id"]: t for t in self.get_tracks(ids)}
        return [({"type": "track", **by[i["video_id"]]} if i.get("type") == "track" and i.get("video_id") in by else i) for i in items]
