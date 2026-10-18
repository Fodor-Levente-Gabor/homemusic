import hashlib
import hmac
import re
import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from . import discover
from .db import now
from .downloader import DownloadError
from .ytm import write_auth

router = APIRouter(prefix="/api")
VID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MIME = {".m4a": "audio/mp4", ".mp4": "audio/mp4", ".webm": "audio/webm", ".opus": "audio/ogg", ".ogg": "audio/ogg", ".mp3": "audio/mpeg"}


def _h(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def auth(request: Request):
    s = request.app.state
    if not s.cfg.password:
        return
    h = request.headers.get("authorization", "")
    tok = h[7:].strip() if h.lower().startswith("bearer ") and h[7:].strip() else request.query_params.get("token")
    if tok:
        with s.db.conn() as c:
            if c.execute("SELECT 1 FROM tokens WHERE token_hash=?", (_h(tok),)).fetchone():
                return
    raise HTTPException(401, "Bejelentkezés szükséges")


A = [Depends(auth)]


def check_ws_token(app, tok) -> bool:
    if not app.state.cfg.password:
        return True
    if not tok:
        return False
    with app.state.db.conn() as c:
        return bool(c.execute("SELECT 1 FROM tokens WHERE token_hash=?", (_h(tok),)).fetchone())


def vid_ok(v: str):
    if not VID.match(v):
        raise HTTPException(400, "érvénytelen azonosító")
    return v


@router.get("/ping")
def ping(request: Request):
    return {"ok": True, "auth_required": bool(request.app.state.cfg.password)}


@router.post("/login")
def login(request: Request, body: dict = Body(...)):
    s = request.app.state
    if s.cfg.password and not hmac.compare_digest(str(body.get("password", "")).encode(), s.cfg.password.encode()):
        raise HTTPException(401, "Hibás jelszó")
    tok = secrets.token_urlsafe(32)
    with s.db.conn() as c:
        c.execute("INSERT INTO tokens(token_hash,created_at) VALUES(?,?)", (_h(tok), now()))
    return {"token": tok}


@router.get("/status", dependencies=A)
def status(request: Request):
    s = request.app.state
    return {"version": "1.0", "ytm_connected": s.ytm.available(), "sync": s.sync.status(), "cache": s.cache.usage(), "stats": s.lib.stats()}


@router.get("/settings", dependencies=A)
def get_settings(request: Request):
    return request.app.state.settings.all()


@router.put("/settings", dependencies=A)
def put_settings(request: Request, changes: dict[str, Any] = Body(...)):
    s = request.app.state
    old = s.settings.get("target_lufs")
    new = s.settings.update(changes)
    if new["target_lufs"] != old:
        s.cache.regain()
    s.cache.evict()
    s.hub.broadcast_threadsafe({"type": "settings", "settings": new})
    return new


@router.post("/ytm/auth", dependencies=A)
def ytm_auth(request: Request, body: dict = Body(...)):
    s = request.app.state
    try:
        write_auth(s.cfg.ytm_auth_file, str(body.get("headers_raw", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"A ytmusicapi elutasította a fejléceket: {e}")
    s.ytm.reload()
    try:
        s.ytm.library_playlists()
    except Exception as e:  # noqa: BLE001
        s.cfg.ytm_auth_file.unlink(missing_ok=True)
        s.ytm.reload()
        raise HTTPException(400, f"A bejelentkezés nem működik: {e}")
    s.sync.kick()
    return {"ok": True}


@router.post("/sync/run", dependencies=A)
def sync_run(request: Request):
    return request.app.state.sync.run()


# ---------------------------------------------------------------- YouTube Music browsing
def _yt(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"YouTube Music hiba: {e}")


@router.get("/search", dependencies=A)
def search(request: Request, q: str, filter: str | None = None):
    s = request.app.state
    return s.lib.decorate(_yt(s.ytm.search, q, filter))


@router.get("/suggest", dependencies=A)
def suggest(request: Request, q: str):
    return _yt(request.app.state.ytm.suggestions, q)


@router.get("/home", dependencies=A)
def home(request: Request):
    s = request.app.state
    return [{"title": x["title"], "items": s.lib.decorate(x["items"])} for x in _yt(s.ytm.home)]


@router.get("/mood", dependencies=A)
def mood(request: Request):
    return _yt(request.app.state.ytm.mood_categories)


@router.get("/mood/playlists", dependencies=A)
def mood_playlists(request: Request, params: str):
    return _yt(request.app.state.ytm.mood_playlists, params)


@router.get("/charts", dependencies=A)
def charts(request: Request):
    s = request.app.state
    return {k: s.lib.decorate(v) for k, v in _yt(s.ytm.charts).items()}


@router.get("/ytm/playlist/{pid}", dependencies=A)
def ytm_playlist(request: Request, pid: str):
    s = request.app.state
    p = _yt(s.ytm.playlist, pid, 300)
    p["tracks"] = s.lib.decorate_tracks(p["tracks"])
    return p


@router.get("/album/{bid}", dependencies=A)
def album(request: Request, bid: str):
    s = request.app.state
    a = _yt(s.ytm.album, bid)
    a["tracks"] = s.lib.decorate_tracks(a["tracks"])
    return a


@router.get("/artist/{cid}", dependencies=A)
def artist(request: Request, cid: str, name: str | None = None):
    s = request.app.state
    a = _yt(s.ytm.artist, cid, name or s.lib.artist_name(cid))
    a["sections"] = {k: s.lib.decorate(v) for k, v in a["sections"].items()}
    return a


@router.get("/radio/{vid}", dependencies=A)
def radio(request: Request, vid: str):
    s = request.app.state
    return s.lib.decorate_tracks(_yt(s.ytm.radio, vid_ok(vid), 50))


@router.get("/mix/random", dependencies=A)
def mix_random(request: Request):
    s = request.app.state
    return s.lib.decorate_tracks(_yt(discover.random_mix, s.ytm))


@router.get("/mix/familiar", dependencies=A)
def mix_familiar(request: Request):
    s = request.app.state
    return s.lib.decorate_tracks(_yt(discover.familiar_mix, s.ytm, s.lib))


# ---------------------------------------------------------------- playback
@router.get("/tracks/{vid}", dependencies=A)
def get_track(request: Request, vid: str):
    t = request.app.state.lib.get_track(vid_ok(vid))
    if not t:
        raise HTTPException(404, "ismeretlen szám")
    return t


@router.get("/ensure/{vid}", dependencies=A)
def ensure(request: Request, vid: str):
    try:
        return request.app.state.cache.ensure(vid_ok(vid))
    except DownloadError as e:
        raise HTTPException(502, f"Letöltési hiba: {e}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Letöltési hiba: {e}")


@router.get("/audio/{vid}", dependencies=A)
def audio(request: Request, vid: str):
    s = request.app.state
    ensure(request, vid)
    p = s.cache.file_for(vid)
    if not p or not p.exists():
        raise HTTPException(502, "a fájl nem érhető el")
    return FileResponse(p, media_type=MIME.get(p.suffix.lower(), "application/octet-stream"))


@router.post("/prefetch", dependencies=A)
def prefetch(request: Request, body: dict = Body(...)):
    ids = [i for i in body.get("ids", []) if isinstance(i, str) and VID.match(i)][:20]
    request.app.state.lib.ensure_rows(ids)
    return {"queued": request.app.state.cache.prefetch(ids)}


@router.post("/play/start", dependencies=A)
def play_start(request: Request, body: dict = Body(...)):
    s = request.app.state
    vid = vid_ok(str(body.get("video_id", "")))
    with s.db.conn() as c:
        c.execute("INSERT OR IGNORE INTO tracks(video_id,first_seen_at) VALUES(?,?)", (vid, now()))
    return {"event_id": s.lib.start_event(vid, body.get("device_id"))}


@router.post("/play/progress", dependencies=A)
def play_progress(request: Request, body: dict = Body(...)):
    s = request.app.state
    r = s.lib.progress_event(int(body.get("event_id", 0)), float(body.get("listened_sec", 0)))
    if r.get("counted_now") and s.ytm.available():
        s.playlists.queue_history(r["video_id"])
        s.sync.kick()
    return {"counted_now": r["counted_now"]}


@router.post("/like/{vid}", dependencies=A)
def like(request: Request, vid: str, body: dict = Body(...)):
    s = request.app.state
    s.lib.ensure_rows([vid_ok(vid)])
    s.playlists.set_liked(vid, bool(body.get("liked")))
    s.sync.kick()
    return {"ok": True}


# ---------------------------------------------------------------- lyrics
@router.get("/lyrics/{vid}", dependencies=A)
def lyrics_get(request: Request, vid: str):
    s = request.app.state
    ly = s.lyrics.get(vid_ok(vid))
    if not ly and s.settings.get("lyrics_prefill"):
        t = s.lib.get_track(vid)
        if t:
            ly = s.lyrics.prefill(t, s.ytm, s.cfg.lrclib_url)
    if not ly:
        raise HTTPException(404, "nincs szöveg")
    return ly


@router.put("/lyrics/{vid}", dependencies=A)
def lyrics_put(request: Request, vid: str, body: dict = Body(...)):
    s = request.app.state
    s.lib.ensure_rows([vid_ok(vid)])
    return s.lyrics.save(vid, body.get("lines") or [], "manual")


@router.put("/lyrics/{vid}/plain", dependencies=A)
def lyrics_plain(request: Request, vid: str, body: dict = Body(...)):
    s = request.app.state
    s.lib.ensure_rows([vid_ok(vid)])
    return s.lyrics.set_plain(vid, str(body.get("text", "")))


@router.patch("/lyrics/{vid}/line", dependencies=A)
def lyrics_line(request: Request, vid: str, body: dict = Body(...)):
    try:
        return request.app.state.lyrics.set_line(vid_ok(vid), int(body["idx"]), body.get("t"))
    except (IndexError, KeyError):
        raise HTTPException(404, "nincs ilyen sor")


@router.post("/lyrics/{vid}/shift", dependencies=A)
def lyrics_shift(request: Request, vid: str, body: dict = Body(...)):
    s = request.app.state
    if not s.lyrics.get(vid_ok(vid)):
        raise HTTPException(404, "nincs szöveg")
    return s.lyrics.shift(vid, int(body.get("delta_ms", 0)))


@router.get("/lyrics/{vid}/lrc", dependencies=A)
def lyrics_lrc(request: Request, vid: str):
    txt = request.app.state.lyrics.to_lrc(vid_ok(vid))
    if txt is None:
        raise HTTPException(404, "nincs szöveg")
    return PlainTextResponse(txt)


@router.post("/lyrics/{vid}/lrc", dependencies=A)
def lyrics_import(request: Request, vid: str, body: dict = Body(...)):
    s = request.app.state
    s.lib.ensure_rows([vid_ok(vid)])
    return s.lyrics.import_lrc(vid, str(body.get("text", "")))


@router.delete("/lyrics/{vid}", dependencies=A)
def lyrics_delete(request: Request, vid: str):
    request.app.state.lyrics.delete(vid_ok(vid))
    return {"ok": True}


# ---------------------------------------------------------------- library / playlists
@router.get("/library/{kind}", dependencies=A)
def library(request: Request, kind: str):
    lib = request.app.state.lib
    if kind not in ("liked", "top", "recent"):
        raise HTTPException(404)
    return {"liked": lib.liked_tracks, "top": lib.top_tracks, "recent": lib.recent_tracks}[kind]()


@router.get("/playlists", dependencies=A)
def playlists(request: Request):
    return request.app.state.playlists.all()


@router.post("/playlists", dependencies=A)
def playlist_create(request: Request, body: dict = Body(...)):
    s = request.app.state
    ids = [vid_ok(v) for v in body.get("video_ids", [])]
    s.lib.ensure_rows(ids)
    pid = s.playlists.create(str(body.get("title") or "Új lista"), str(body.get("description", "")), ids)
    s.sync.kick()
    return next(p for p in s.playlists.all() if p["id"] == pid)


def _pl(fn, request, pid, *a):
    s = request.app.state
    try:
        r = fn(pid, *a)
    except KeyError:
        raise HTTPException(404, "nincs ilyen lista")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    s.sync.kick()
    return r


@router.get("/playlists/{pid}", dependencies=A)
def playlist_get(request: Request, pid: int):
    p = request.app.state.playlists.get(pid)
    if not p:
        raise HTTPException(404, "nincs ilyen lista")
    return p


@router.post("/playlists/{pid}/items", dependencies=A)
def playlist_add(request: Request, pid: int, body: dict = Body(...)):
    s = request.app.state
    ids = [vid_ok(v) for v in body.get("video_ids", [])]
    s.lib.ensure_rows(ids)
    _pl(s.playlists.add_items, request, pid, ids)
    return {"ok": True}


@router.post("/playlists/{pid}/items/remove", dependencies=A)
def playlist_remove(request: Request, pid: int, body: dict = Body(...)):
    _pl(request.app.state.playlists.remove_items, request, pid, list(body.get("video_ids", [])))
    return {"ok": True}


@router.patch("/playlists/{pid}", dependencies=A)
def playlist_rename(request: Request, pid: int, body: dict = Body(...)):
    _pl(request.app.state.playlists.rename, request, pid, str(body.get("title", "")))
    return {"ok": True}


@router.delete("/playlists/{pid}", dependencies=A)
def playlist_delete(request: Request, pid: int):
    _pl(request.app.state.playlists.delete, request, pid)
    return {"ok": True}


# ---------------------------------------------------------------- cache
@router.post("/cache/{vid}/pin", dependencies=A)
def cache_pin(request: Request, vid: str, body: dict = Body(...)):
    request.app.state.cache.pin(vid_ok(vid), bool(body.get("pinned", True)))
    return {"ok": True}


@router.delete("/cache/{vid}", dependencies=A)
def cache_delete(request: Request, vid: str):
    request.app.state.cache.delete(vid_ok(vid))
    return {"ok": True}
