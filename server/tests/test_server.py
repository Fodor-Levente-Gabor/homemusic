import json
import os
import time

from conftest import T


def test_auth_required(env):
    c = env.client
    assert c.get("/api/ping").status_code == 200
    r = c.get("/api/status", headers={"Authorization": ""})
    assert r.status_code == 401
    assert c.post("/api/login", json={"password": "rossz"}).status_code == 401
    assert c.get(f"/api/status?token={env.token}", headers={"Authorization": ""}).status_code == 200


def test_audio_download_range_loudness(env):
    c = env.client
    r = c.get("/api/audio/vid1")
    assert r.status_code == 200 and len(r.content) > 1000
    assert r.headers["content-type"] == "audio/mp4"
    r2 = c.get("/api/audio/vid1", headers={"Range": "bytes=0-99"})
    assert r2.status_code == 206 and len(r2.content) == 100
    t = c.get("/api/tracks/vid1").json()
    assert t["cached"] is True and t["file_size"] > 0
    assert t["loudness_lufs"] is not None and t["loudness_lufs"] < 0
    assert t["gain_db"] != 0 or abs(t["loudness_lufs"] + 14) < 0.1
    assert env.dl.calls == ["vid1"]          # másodszor nem tölt újra


def test_ensure_returns_gain(env):
    t = env.client.get("/api/ensure/ens1").json()
    assert t["cached"] is True and "gain_db" in t and t["loudness_lufs"] < 0
    assert env.client.get("/api/ensure/../x").status_code in (400, 404)


def test_prefetch_and_play_counting(env):
    c = env.client
    c.post("/api/prefetch", json={"ids": ["p1", "p2"]})
    for _ in range(100):
        if all(c.get(f"/api/tracks/{i}").json()["cached"] for i in ("p1", "p2")):
            break
        time.sleep(0.1)
    assert all(c.get(f"/api/tracks/{i}").json()["cached"] for i in ("p1", "p2"))
    env.app.state.cache.db  # noqa
    # tracks metaadat: 200 mp-es szám -> 30 mp után számol
    ev = c.post("/api/play/start", json={"video_id": "p1", "device_id": "d"}).json()["event_id"]
    assert c.post("/api/play/progress", json={"event_id": ev, "listened_sec": 10}).json()["counted_now"] is False
    assert c.get("/api/tracks/p1").json()["play_count"] == 0
    assert c.post("/api/play/progress", json={"event_id": ev, "listened_sec": 35}).json()["counted_now"] is True
    assert c.post("/api/play/progress", json={"event_id": ev, "listened_sec": 80}).json()["counted_now"] is False
    assert c.get("/api/tracks/p1").json()["play_count"] == 1       # egy eseményre egyszer számol
    # a YT Music felé előzmény kerül sorba
    assert env.sync.status()["pending"] == 1
    env.sync.push()
    assert ("history", "p1") in env.ytm.calls


def _fake_cached(env, vid, size, plays, age_days, last_played_days=None):
    f = env.cfg.cache_dir / f"{vid}.m4a"
    f.write_bytes(b"x" * size)
    now = int(time.time())
    with env.db.conn() as cx:
        cx.execute("INSERT OR IGNORE INTO tracks(video_id,first_seen_at) VALUES(?,?)", (vid, now))
        cx.execute("UPDATE tracks SET file_path=?,file_size=?,play_count=?,downloaded_at=?,last_played_at=?,dl_state='ready' WHERE video_id=?",
                   (str(f), size, plays, now - age_days * 86400,
                    None if last_played_days is None else now - last_played_days * 86400, vid))
    return f


def test_eviction_least_played_first_and_lyrics_survive(env):
    c = env.client
    mb = 1024 * 1024
    files = {
        "popular": _fake_cached(env, "popular", 40 * mb, 50, 100, 1),
        "mid": _fake_cached(env, "mid", 40 * mb, 5, 100, 10),
        "rare_old": _fake_cached(env, "rare_old", 40 * mb, 1, 100, 90),
        "rare_new": _fake_cached(env, "rare_new", 40 * mb, 0, 2),       # új, védett (türelmi idő)
    }
    c.put("/api/lyrics/rare_old", json={"lines": [{"t": 1000, "text": "a"}, {"t": 2000, "text": "b"}]})
    # limit: 100 MB (0.09765625 GB), összesen 160 MB -> a 90%-ig (90 MB) kell takarítani
    c.put("/api/settings", json={"cache_limit_gb": 100 / 1024})
    assert not files["rare_old"].exists()          # legkevesebbet játszott, régi
    assert not files["mid"].exists()               # a következő
    assert files["popular"].exists() and files["rare_new"].exists()   # 80 MB <= 90 MB, itt megáll
    t = c.get("/api/tracks/rare_old").json()
    assert t["cached"] is False and t["play_count"] == 1          # metaadat, statisztika megmarad
    assert c.get("/api/lyrics/rare_old").json()["synced"] is True      # a lyrics megmarad
    assert t["dl_state"] == "none"
    # újralejátszáskor automatikusan újra letöltődik
    assert c.get("/api/audio/rare_old").status_code == 200
    assert c.get("/api/tracks/rare_old").json()["cached"] is True


def test_pinned_protected(env):
    mb = 1024 * 1024
    f = _fake_cached(env, "pin", 60 * mb, 0, 100)
    _fake_cached(env, "other", 60 * mb, 9, 100)
    env.client.post("/api/cache/pin/pin", json={"pinned": True})
    env.client.post("/api/cache/pin/pin", json={"pinned": True})
    env.client.put("/api/settings", json={"cache_limit_gb": 100 / 1024})
    assert f.exists()


def test_reconcile_missing_file(env):
    f = _fake_cached(env, "gone", 1000, 1, 100)
    f.unlink()
    env.cache.reconcile()
    assert env.client.get("/api/tracks/gone").json()["cached"] is False


def test_lyrics_manual_sync_flow(env):
    c = env.client
    c.put("/api/lyrics/v1/plain", json={"text": "első sor\nmásodik sor\n\nharmadik sor"})
    l = c.get("/api/lyrics/v1").json()
    assert [x["text"] for x in l["lines"]] == ["első sor", "második sor", "harmadik sor"]
    assert l["synced"] is False and len(l["lines"]) == 3
    # "következő sor" gomb: soronként mentődik az időbélyeg
    for i, t in enumerate([1500, 4200, 9000]):
        l = c.patch("/api/lyrics/v1/line", json={"idx": i, "t": t}).json()
    assert l["synced"] is True
    l = c.post("/api/lyrics/v1/shift", json={"delta_ms": -200}).json()
    assert [x["t"] for x in l["lines"]] == [1300, 4000, 8800]
    lrc = c.get("/api/lyrics/v1/lrc").text
    assert lrc.splitlines()[0] == "[00:01.30]első sor"
    c.delete("/api/lyrics/v1")
    assert c.get("/api/lyrics/v1").status_code == 404
    r = c.post("/api/lyrics/v1/lrc", json={"text": lrc}).json()
    assert [x["t"] for x in r["lines"]] == [1300, 4000, 8800]
    assert c.patch("/api/lyrics/v1/line", json={"idx": 99, "t": 1}).status_code == 404


def test_lrc_parse_edge_cases():
    from app.lyrics import parse_lrc
    ls = parse_lrc("[ar:Valaki]\n[00:12.5]a\n[01:02.345][00:01.00]kórus\n")
    assert [(l["t"], l["text"]) for l in ls] == [(1000, "kórus"), (12500, "a"), (62345, "kórus")]


def test_search_remembers_tracks(env):
    r = env.client.get("/api/search?q=teszt").json()
    assert r[0]["type"] == "track" and r[0]["video_id"] == "s1" and r[0]["cached"] is False
    assert env.client.get("/api/tracks/s1").json()["title"] == "teszt"


def test_playlist_two_way_sync(env):
    c = env.client
    # helyi létrehozás -> YT Music felé
    pl = c.post("/api/playlists", json={"title": "Új lista", "video_ids": ["a", "b"]}).json()
    assert env.sync.status()["pending"] == 2
    env.sync.push()
    assert env.sync.status()["pending"] == 0
    assert ("create", "Új lista") in env.ytm.calls and ("add", "PLnew1", ["a", "b"]) in env.ytm.calls
    assert c.get(f"/api/playlists/{pl['id']}").json()["ytm_id"] == "PLnew1"
    # elem törlése, átnevezés
    c.post(f"/api/playlists/{pl['id']}/items/remove", json={"video_ids": ["a"]})
    c.patch(f"/api/playlists/{pl['id']}", json={"title": "Átnevezve"})
    env.sync.push()
    assert env.ytm.remote_playlists["PLnew1"]["title"] == "Átnevezve"
    assert [t["video_id"] for t in env.ytm.remote_playlists["PLnew1"]["tracks"]] == ["b"]
    # pull: távoli lista megjelenik, a sajátunk is szinkronban marad
    env.ytm.remote_playlists["PLremote"] = {"title": "Telefonról", "owned": True,
                                           "tracks": [{**T("r1"), "set_video_id": "x1"}, {**T("r2"), "set_video_id": "x2"}]}
    env.ytm.remote_playlists["PLother"] = {"title": "Más listája", "owned": False, "tracks": [{**T("o1"), "set_video_id": "y"}]}
    env.sync.pull()
    names = {p["title"]: p for p in c.get("/api/playlists").json()}
    assert set(names) == {"Átnevezve", "Telefonról", "Más listája"}
    assert names["Más listája"]["kind"] == "saved"
    assert c.post(f"/api/playlists/{names['Más listája']['id']}/items", json={"video_ids": ["z"]}).status_code == 403
    assert [t["video_id"] for t in c.get(f"/api/playlists/{names['Telefonról']['id']}").json()["tracks"]] == ["r1", "r2"]
    # törlés távolról -> helyben is eltűnik
    del env.ytm.remote_playlists["PLremote"]
    env.sync.pull()
    assert "Telefonról" not in {p["title"] for p in c.get("/api/playlists").json()}
    # helyi törlés -> távoli törlés
    c.delete(f"/api/playlists/{pl['id']}")
    env.sync.push()
    assert "PLnew1" not in env.ytm.remote_playlists


def test_pull_does_not_overwrite_pending_local_changes(env):
    c = env.client
    env.ytm.remote_playlists["PL1"] = {"title": "L", "owned": True, "tracks": [{**T("a"), "set_video_id": "1"}]}
    env.sync.pull()
    pid = c.get("/api/playlists").json()[0]["id"]
    c.post(f"/api/playlists/{pid}/items", json={"video_ids": ["b"]})       # még nincs elküldve
    env.sync.pull()                                                         # nem írhatja felül
    assert [t["video_id"] for t in c.get(f"/api/playlists/{pid}").json()["tracks"]] == ["a", "b"]
    env.sync.push()
    env.sync.pull()
    assert [t["video_id"] for t in c.get(f"/api/playlists/{pid}").json()["tracks"]] == ["a", "b"]


def test_liked_sync_both_ways(env):
    c = env.client
    env.ytm.liked = [T("l1"), T("l2")]
    env.sync.pull()
    assert {t["video_id"] for t in c.get("/api/library/liked").json()} == {"l1", "l2"}
    c.post("/api/like/l3", json={"liked": True})
    c.post("/api/like/l1", json={"liked": False})
    env.sync.pull()                         # függő változtatás: a helyi állapot nyer
    assert {t["video_id"] for t in c.get("/api/library/liked").json()} == {"l2", "l3"}
    env.sync.push()
    assert ("rate", "l3", True) in env.ytm.calls and ("rate", "l1", False) in env.ytm.calls
    env.ytm.liked = [T("l2"), T("l3")]
    env.sync.pull()
    assert {t["video_id"] for t in c.get("/api/library/liked").json()} == {"l2", "l3"}


def test_push_failure_retries_then_drops(env):
    c = env.client
    def boom(*a): raise RuntimeError("hálózat")
    env.ytm.rate = boom
    c.post("/api/like/x", json={"liked": True})
    for _ in range(4):
        env.sync.push()
    assert env.sync.status()["pending"] == 1
    env.sync.push()
    assert env.sync.status()["pending"] == 0


def test_mixes(env):
    c = env.client
    r = c.get("/api/mix/random").json()
    assert len(r) > 0 and len({t["video_id"] for t in r}) == len(r)
    assert c.get("/api/mix/familiar").json() == []       # még nincs előzmény
    env.ytm.liked = [T("fav")]
    env.sync.pull()
    f = c.get("/api/mix/familiar").json()
    assert f and all(t["video_id"].startswith("fav_r") for t in f)


def test_settings_roundtrip(env):
    c = env.client
    s = c.put("/api/settings", json={"crossfade_ms": 4000, "eq_gains": [1] * 10, "bogus": 1}).json()
    assert s["crossfade_ms"] == 4000 and "bogus" not in s
    assert c.get("/api/settings").json()["eq_gains"] == [1] * 10
    assert c.get("/api/status").json()["cache"]["limit_bytes"] > 0


def test_remote_control_websocket(env):
    c = env.client
    tok = env.token
    with c.websocket_connect(f"/ws?token={tok}&device_id=pc&name=PC&kind=web") as pc:
        first = json.loads(pc.receive_text())
        assert first["type"] == "devices" and first["you"] == "pc"
        with c.websocket_connect(f"/ws?token={tok}&device_id=phone&name=Telefon&kind=android") as ph:
            hello = json.loads(ph.receive_text())
            assert {d["id"] for d in hello["devices"]} == {"pc", "phone"}
            assert {d["id"] for d in json.loads(pc.receive_text())["devices"]} == {"pc", "phone"}
            # PC jelenti az állapotát, a telefon látja
            pc.send_text(json.dumps({"type": "state", "state": {"playing": True, "video_id": "abc", "position_ms": 5000}}))
            st = json.loads(ph.receive_text())
            assert st["type"] == "state" and st["device_id"] == "pc" and st["state"]["video_id"] == "abc"
            # részleges frissítés összefésülődik; a harmadik, újonnan belépő eszköz a teljes állapotot látja
            pc.send_text(json.dumps({"type": "state", "state": {"position_ms": 7000}}))
            assert json.loads(ph.receive_text())["state"] == {"position_ms": 7000}
            snap = {d["id"]: d for d in env.hub.snapshot()}
            assert snap["pc"]["state"]["video_id"] == "abc" and snap["pc"]["state"]["position_ms"] == 7000
            # a telefon irányítja a PC-t
            ph.send_text(json.dumps({"type": "command", "target": "pc", "cmd": "pause"}))
            cmd = json.loads(pc.receive_text())
            assert cmd == {"type": "command", "from": "phone", "from_name": "Telefon", "cmd": "pause", "args": {}}
            # és fordítva
            pc.send_text(json.dumps({"type": "command", "target": "phone", "cmd": "seek", "args": {"position_ms": 1000}}))
            assert json.loads(ph.receive_text())["args"] == {"position_ms": 1000}
            # ismeretlen cél
            ph.send_text(json.dumps({"type": "command", "target": "nincs", "cmd": "play"}))
            assert json.loads(ph.receive_text())["type"] == "error"


def test_ws_rejects_bad_token(env):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with env.client.websocket_connect("/ws?token=rossz&device_id=x") as ws:
            ws.receive_text()


def test_ytm_auth_validation(env):
    r = env.client.post("/api/ytm/auth", json={"headers_raw": "ez nem fejléc"})
    assert r.status_code == 400
