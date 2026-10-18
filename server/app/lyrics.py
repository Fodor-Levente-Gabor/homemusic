"""Lyrics live in the DB keyed by video_id — they survive audio eviction. Sources: manual, LRCLIB, YouTube Music."""
import logging
import re

from .db import now

log = logging.getLogger("lyrics")
LINE_RE = re.compile(r"^\s*((?:\[\d+:\d+(?:[.:]\d+)?\]\s*)+)(.*)$")
TS_RE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")


def parse_lrc(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        body = m.group(2).strip()
        if not body:
            continue
        for mm, ss in TS_RE.findall(m.group(1)):
            out.append({"t": int(round((int(mm) * 60 + float(ss.replace(":", "."))) * 1000)), "text": body})
    out.sort(key=lambda x: x["t"])
    return out


def fmt_ts(ms: int) -> str:
    return f"[{ms // 60000:02d}:{(ms % 60000) / 1000:05.2f}]"


class Lyrics:
    def __init__(self, db):
        self.db = db

    def get(self, vid):
        with self.db.conn() as c:
            h = c.execute("SELECT * FROM lyrics WHERE video_id=?", (vid,)).fetchone()
            if not h:
                return None
            rows = c.execute("SELECT t,text FROM lyric_lines WHERE video_id=? ORDER BY idx", (vid,)).fetchall()
        lines = [{"t": r["t"], "text": r["text"]} for r in rows]
        return {"video_id": vid, "lines": lines, "synced": bool(lines) and all(l["t"] is not None for l in lines), "source": h["source"]}

    def save(self, vid, lines, source="manual"):
        lines = [{"t": (None if l.get("t") is None else max(0, int(l["t"]))), "text": str(l.get("text", "")).strip()} for l in lines]
        lines = [l for l in lines if l["text"]]
        with self.db.conn() as c:
            c.execute("DELETE FROM lyric_lines WHERE video_id=?", (vid,))
            for i, l in enumerate(lines):
                c.execute("INSERT INTO lyric_lines(video_id,idx,t,text) VALUES(?,?,?,?)", (vid, i, l["t"], l["text"]))
            c.execute("INSERT INTO lyrics(video_id,source,updated_at) VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET source=excluded.source, updated_at=excluded.updated_at",
                      (vid, source, now()))
        return self.get(vid)

    def set_plain(self, vid, text, source="manual"):
        return self.save(vid, [{"t": None, "text": s} for s in text.replace("\r", "").split("\n")], source)

    def import_lrc(self, vid, text):
        parsed = parse_lrc(text)
        return self.save(vid, parsed, "manual") if parsed else self.set_plain(vid, text)

    def set_line(self, vid, idx, t):
        cur = self.get(vid)
        if not cur or not (0 <= idx < len(cur["lines"])):
            raise IndexError("no such line")
        with self.db.conn() as c:
            c.execute("UPDATE lyric_lines SET t=? WHERE video_id=? AND idx=?", (None if t is None else max(0, int(t)), vid, idx))
            c.execute("UPDATE lyrics SET updated_at=? WHERE video_id=?", (now(), vid))
        return self.get(vid)

    def shift(self, vid, delta_ms):
        with self.db.conn() as c:
            c.execute("UPDATE lyric_lines SET t=MAX(0,t+?) WHERE video_id=? AND t IS NOT NULL", (int(delta_ms), vid))
        return self.get(vid)

    def to_lrc(self, vid):
        cur = self.get(vid)
        if not cur:
            return None
        return "\n".join((fmt_ts(l["t"]) if l["t"] is not None else "") + l["text"] for l in cur["lines"]) + "\n"

    def delete(self, vid):
        with self.db.conn() as c:
            c.execute("DELETE FROM lyric_lines WHERE video_id=?", (vid,))
            c.execute("DELETE FROM lyrics WHERE video_id=?", (vid,))

    def prefill(self, track, ytm, lrclib_url):
        """Try LRCLIB (synced if available), then YouTube Music plain text. Never overwrites existing lyrics."""
        vid = track["video_id"]
        if self.get(vid) or not track.get("title"):
            return self.get(vid)
        try:
            import httpx
            p = {"track_name": track["title"], "artist_name": (track.get("artist") or "").split(",")[0].strip()}
            if track.get("album"):
                p["album_name"] = track["album"]
            if track.get("duration_sec"):
                p["duration"] = int(track["duration_sec"])
            r = httpx.get(f"{lrclib_url}/get", params=p, timeout=8, headers={"User-Agent": "HomeMusic/1.0"})
            if r.status_code == 200:
                j = r.json()
                if j.get("syncedLyrics") and parse_lrc(j["syncedLyrics"]):
                    return self.save(vid, parse_lrc(j["syncedLyrics"]), "lrclib")
                if j.get("plainLyrics"):
                    return self.set_plain(vid, j["plainLyrics"], "lrclib")
        except Exception as e:  # noqa: BLE001
            log.info("lrclib failed: %s", e)
        try:
            txt = ytm.lyrics_text(vid) if ytm.available() else None
            if txt:
                return self.set_plain(vid, txt, "ytm")
        except Exception as e:  # noqa: BLE001
            log.info("ytm lyrics failed: %s", e)
        return None
