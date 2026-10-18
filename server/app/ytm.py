"""YouTube Music access (ytmusicapi, browser-header login). Returns the app's normalised track/item dicts."""
import logging
import re
import threading

from .library import hi_res, normalize_track

log = logging.getLogger("ytm")


def extract_cookie(raw: str):
    if "=" in raw and "\n" not in raw.strip() and "__Secure-3PAPISID=" in raw and not re.match(r"(?i)^\s*(curl|:?cookie:)", raw):
        return raw.strip().rstrip(";")     # only the cookie value was pasted
    m = re.search(r"(?im)^\s*:?cookie:\s*(.+)$", raw) or re.search(r"""(?i)(?:-H|--header)\s+['"]cookie:\s*([^'"]+)['"]""", raw) \
        or re.search(r"""(?i)(?:-b|--cookie)\s+['"]([^'"]+)['"]""", raw)
    return m.group(1).strip() if m else None


def write_auth(path, raw: str) -> None:
    """Validate pasted request headers and store them for ytmusicapi (+ a cookies.txt for yt-dlp). Raises ValueError."""
    import ytmusicapi
    from pathlib import Path
    path = Path(path)
    cookie = extract_cookie(raw)
    if not cookie or "__Secure-3PAPISID" not in cookie:
        raise ValueError("Nem találok bejelentkezett Cookie-t (__Secure-3PAPISID). Jelentkezz be a music.youtube.com-on, és másold ki egy kérés Cookie értékét (vagy a teljes Request Headers részt).")
    lines = [f"cookie: {cookie}"]
    if not re.search(r"(?im)^\s*authorization:\s*SAPISIDHASH", raw):
        lines.append("authorization: SAPISIDHASH 0_0")      # ytmusicapi recomputes it from the cookie on every request
    for key in ("user-agent", "x-goog-authuser", "authorization", "x-goog-visitor-id", "origin"):
        m = re.search(rf"(?im)^\s*{key}:\s*(.+)$", raw)
        if m:
            lines.append(f"{key}: {m.group(1).strip()}")
    if not any(ln.lower().startswith("x-goog-authuser") for ln in lines):
        lines.append("x-goog-authuser: 0")
    path.parent.mkdir(parents=True, exist_ok=True)
    ytmusicapi.setup(filepath=str(path), headers_raw="\n".join(lines))
    # ytmusicapi falls back to its own User-Agent; use the browser's so the cookies and the client match
    m = re.search(r"(?im)^\s*user-agent:\s*(.+)$", raw)
    if m:
        import json
        j = json.loads(path.read_text())
        j["user-agent"] = m.group(1).strip()
        path.write_text(json.dumps(j, indent=4))
    cj = ["# Netscape HTTP Cookie File"]
    for part in cookie.split(";"):
        if "=" in part:
            n, v = part.strip().split("=", 1)
            cj.append("\t".join([".youtube.com", "TRUE", "/", "TRUE", "2147483647", n, v]))
    cf = path.parent / "cookies.txt"
    cf.write_text("\n".join(cj) + "\n")
    try:
        cf.chmod(0o600)
        path.chmod(0o600)
    except OSError:
        pass


def _thumb(d):
    t = d.get("thumbnails") or d.get("thumbnail") or []
    if isinstance(t, list) and t:
        return hi_res(t[-1].get("url"))
    return None


def _names(artists):
    return [a.get("name") for a in (artists or []) if isinstance(a, dict) and a.get("name")]


def item(d):
    """Any ytmusicapi result -> {"type": track|album|artist|playlist, ...} or None."""
    if not isinstance(d, dict):
        return None
    rt, vid, bid, pid = d.get("resultType"), d.get("videoId"), d.get("browseId"), d.get("playlistId")
    sub = d.get("subtitle")
    if not sub:
        parts = _names(d.get("artists"))
        for k in ("year", "itemCount", "subscribers"):
            if d.get(k):
                parts.append(str(d[k]))
        a = d.get("author")
        if a:
            parts.append(a if isinstance(a, str) else ", ".join(_names(a)))
        sub = " · ".join(parts) or d.get("description") or ""
    title = d.get("title") or d.get("artist") or d.get("name") or d.get("username") or ""
    if rt == "album" or (bid and str(bid).startswith("MPRE")):
        return {"type": "album", "id": bid, "title": title, "subtitle": sub, "thumbnail": _thumb(d)}
    if rt in ("artist", "profile") or (bid and str(bid).startswith("UC")):
        return {"type": "artist", "id": bid or d.get("channelId"), "title": d.get("artist") or title, "subtitle": sub, "thumbnail": _thumb(d)}
    if rt in ("playlist", "featured_playlist", "community_playlist") or (pid and not vid):
        p = pid or bid or ""
        return {"type": "playlist", "id": p[2:] if p.startswith("VL") else p, "title": title, "subtitle": sub, "thumbnail": _thumb(d)}
    if vid:
        t = normalize_track(d)
        return {"type": "track", **t} if t else None
    return None


def items(lst):
    return [x for x in (item(d) for d in lst or []) if x]


def tracks(lst):
    return [t for t in (normalize_track(d) for d in lst or [] if d.get("isAvailable") is not False) if t]


class YTM:
    def __init__(self, auth_file):
        self.auth_file = auth_file
        self._c = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return self.auth_file.exists()

    def reload(self):
        with self._lock:
            self._c = None

    def c(self):
        from ytmusicapi import YTMusic
        with self._lock:
            if self._c is None:
                self._c = YTMusic(str(self.auth_file)) if self.available() else YTMusic()
            return self._c

    # ---- browse
    def suggestions(self, q):
        return [s for s in self.c().get_search_suggestions(q) if isinstance(s, str)]

    def search(self, q, filter=None, limit=25):
        return items(self.c().search(q, filter=filter or None, limit=limit))

    def home(self):
        out = []
        for sec in self.c().get_home(limit=6) or []:
            its = items(sec.get("contents"))
            if its:
                out.append({"title": sec.get("title") or "", "items": its})
        return out

    def charts(self, country="ZZ"):
        ch = self.c().get_charts(country)
        out = {}
        for k in ("songs", "videos", "artists", "trending"):
            v = ch.get(k)
            lst = v.get("items") if isinstance(v, dict) else v
            if lst:
                out[k] = items(lst)
        return out

    def mood_categories(self):
        return [{"section": sec, "title": m["title"], "params": m["params"]}
                for sec, cats in (self.c().get_mood_categories() or {}).items() for m in cats]

    def mood_playlists(self, params):
        return items(self.c().get_mood_playlists(params))

    def playlist(self, pid, limit=None):
        p = self.c().get_playlist(pid, limit=limit)
        tr = []
        for d in p.get("tracks") or []:
            t = normalize_track(d) if d.get("isAvailable") is not False else None
            if t:
                t["set_video_id"] = d.get("setVideoId")
                tr.append(t)
        return {"id": pid, "title": p.get("title") or pid, "description": p.get("description") or "",
                "owned": bool(p.get("owned")), "thumbnail": _thumb(p), "tracks": tr}

    def album(self, bid):
        a = self.c().get_album(bid)
        th = _thumb(a)
        tr = tracks(a.get("tracks"))
        for t in tr:
            t["album"] = t["album"] or a.get("title") or ""
            t["album_id"] = t["album_id"] or bid
            t["thumbnail"] = t["thumbnail"] or th
            t["artist"] = t["artist"] or ", ".join(_names(a.get("artists")))
        return {"id": bid, "title": a.get("title"), "year": a.get("year"), "artists": _names(a.get("artists")), "thumbnail": th, "tracks": tr}

    def artist(self, cid, name=None):
        """Artist page. Sections use the keys the web client reads: songs, albums, singles, videos, related.
        If YouTube rejects the id (HTTP 400 happens for ids that are not music-artist pages) we retry with the ids of the
        best matching artist search results, and finally fall back to song/album search results for the name.
        cid may be "_" (unknown) when only the name is known, e.g. when an artist name is clicked in a track row."""
        a, used, errors = None, cid, []
        known = cid and cid != "_"
        for candidate in ([cid] if known else []) + self._artist_candidates(name, cid):
            try:
                a = self.c().get_artist(candidate)
                used = candidate
                break
            except Exception as e:  # noqa: BLE001
                log.info("get_artist(%s) failed: %s", candidate, e)
                errors.append(str(e)[:160])
        if a is None:
            if not name:
                raise RuntimeError("Az előadó oldala nem tölthető be" + (f" ({errors[-1]})" if errors else ""))
            low = name.casefold()
            sr = self.c().search(name, filter="songs", limit=30)
            mine = [d for d in sr if any(low in n.casefold() for n in _names(d.get("artists")))] or sr
            secs = {"songs": [{"type": "track", **t} for t in tracks(mine)],
                    "albums": items(self.c().search(name, filter="albums", limit=20))}
            return {"id": cid, "name": name, "description": "", "thumbnail": None, "sections": secs, "radio_id": None,
                    "fallback": True, "error": errors[-1] if errors else None}
        secs = {}
        songs = (a.get("songs") or {}).get("results") if isinstance(a.get("songs"), dict) else None
        if songs:
            secs["songs"] = [{"type": "track", **t} for t in tracks(songs)]
        for k in ("albums", "singles", "videos", "related"):
            v = a.get(k)
            if isinstance(v, dict) and v.get("results"):
                secs[k] = items(v["results"])
        return {"id": used, "name": a.get("name") or name, "description": a.get("description") or "", "thumbnail": _thumb(a),
                "sections": secs, "radio_id": a.get("radioId")}

    def _artist_candidates(self, name, cid):
        if not name:
            return []
        try:
            res = self.c().search(name, filter="artists", limit=5)
        except Exception:  # noqa: BLE001
            return []
        low = name.casefold()
        ids = [r["browseId"] for r in res if r.get("browseId") and r["browseId"] != cid]
        exact = [r["browseId"] for r in res if r.get("browseId") and r["browseId"] != cid and (r.get("artist") or "").casefold() == low]
        return list(dict.fromkeys(exact + ids))[:3]

    def radio(self, vid, limit=50, shuffle=False):
        wp = self.c().get_watch_playlist(videoId=vid, radio=True, limit=limit, shuffle=shuffle)
        return tracks(wp.get("tracks"))

    # ---- library
    def library_playlists(self):
        return [{"id": p["playlistId"], "title": p.get("title") or p["playlistId"], "thumbnail": _thumb(p)}
                for p in self.c().get_library_playlists(limit=None) or [] if p.get("playlistId") not in (None, "LM", "SE")]

    def liked_songs(self):
        return tracks(self.c().get_liked_songs(limit=5000).get("tracks"))

    def lyrics_text(self, vid):
        try:
            c = self.c()
            bid = c.get_watch_playlist(vid).get("lyrics")
            ly = c.get_lyrics(bid) if bid else None
            return ly["lyrics"] if ly and isinstance(ly, dict) else (getattr(ly, "lyrics", None) if ly else None)
        except Exception as e:  # noqa: BLE001
            log.info("ytm lyrics failed: %s", e)
            return None

    # ---- writes
    def create_playlist(self, title, description=""):
        r = self.c().create_playlist(title, description or "")
        if isinstance(r, dict):
            raise RuntimeError(f"create_playlist failed: {r}")
        return str(r)

    def rename_playlist(self, pid, title):
        self.c().edit_playlist(pid, title=title)

    def delete_playlist(self, pid):
        self.c().delete_playlist(pid)

    def add_items(self, pid, vids):
        self.c().add_playlist_items(pid, list(vids), duplicates=True)

    def remove_items(self, pid, vids):
        remote = self.c().get_playlist(pid, limit=None).get("tracks") or []
        want, rm = list(vids), []
        for t in remote:
            if t.get("videoId") in want and t.get("setVideoId"):
                want.remove(t["videoId"])
                rm.append({"videoId": t["videoId"], "setVideoId": t["setVideoId"]})
        if rm:
            self.c().remove_playlist_items(pid, rm)

    def rate(self, vid, liked):
        self.c().rate_song(vid, "LIKE" if liked else "INDIFFERENT")

    def add_history(self, vid):
        c = self.c()
        c.add_history_item(c.get_song(vid))
