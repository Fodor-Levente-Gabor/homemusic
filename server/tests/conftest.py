import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Config  # noqa: E402
from app.main import create_app  # noqa: E402


class FakeDownloader:
    """Valódi ffmpeg-gel generál hangfájlt, hogy a loudness mérés és a streaming is élesben fusson."""
    def __init__(self):
        self.calls = []

    def download(self, video_id, dest_dir):
        self.calls.append(video_id)
        out = Path(dest_dir) / f"{video_id}.m4a"
        freq = 220 + (abs(hash(video_id)) % 400)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}:duration=3:sample_rate=44100", "-c:a", "aac", str(out)], check=True)
        return out


def T(vid, title="Dal", artist="Előadó"):
    return {"video_id": vid, "title": title, "artist": artist, "artists": [artist], "album": "Album",
            "album_id": None, "duration_sec": 200, "thumbnail": None}


class FakeYTM:
    def __init__(self):
        self.auth = True
        self.calls = []
        self.remote_playlists = {}   # id -> {"title","owned","tracks":[track + set_video_id]}
        self.liked = []
        self.next_id = 1

    def available(self): return self.auth
    def reload(self): pass
    def suggestions(self, q): return [q + " x"]
    def search(self, q, filter=None, limit=25): return [{"type": "track", **T("s1", q)}, {"type": "artist", "id": "UC1", "title": "A", "subtitle": "", "thumbnail": None}]
    def radio(self, vid, limit=50, shuffle=False): return [T(f"{vid}_r{i}") for i in range(5)]
    def mood_categories(self): return [{"section": "x", "title": "Chill", "params": "p1"}, {"section": "x", "title": "Rock", "params": "p2"}]
    def mood_playlists(self, params): return [{"type": "playlist", "id": "PL_" + params, "title": params, "subtitle": "", "thumbnail": None}]
    def playlist(self, pid, limit=None):
        if pid in self.remote_playlists:
            p = self.remote_playlists[pid]
            return {"id": pid, "title": p["title"], "description": "", "owned": p["owned"], "thumbnail": None, "tracks": p["tracks"]}
        return {"id": pid, "title": pid, "description": "", "owned": False, "thumbnail": None,
                "tracks": [T(f"{pid}_{i}") for i in range(4)]}
    def library_playlists(self): return [{"id": k, "title": v["title"], "thumbnail": None} for k, v in self.remote_playlists.items()]
    def liked_songs(self): return self.liked
    def lyrics_text(self, vid): return None
    def create_playlist(self, title, description=""):
        self.calls.append(("create", title))
        pid = f"PLnew{self.next_id}"; self.next_id += 1
        self.remote_playlists[pid] = {"title": title, "owned": True, "tracks": []}
        return pid
    def rename_playlist(self, pid, title): self.calls.append(("rename", pid, title)); self.remote_playlists[pid]["title"] = title
    def delete_playlist(self, pid): self.calls.append(("delete", pid)); self.remote_playlists.pop(pid, None)
    def add_items(self, pid, vids):
        self.calls.append(("add", pid, list(vids)))
        for v in vids:
            self.remote_playlists[pid]["tracks"].append({**T(v), "set_video_id": "sv_" + v})
    def remove_items(self, pid, vids):
        self.calls.append(("remove", pid, list(vids)))
        self.remote_playlists[pid]["tracks"] = [t for t in self.remote_playlists[pid]["tracks"] if t["video_id"] not in vids]
    def rate(self, vid, liked): self.calls.append(("rate", vid, liked))
    def add_history(self, vid): self.calls.append(("history", vid))


@pytest.fixture
def env(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.cache_dir = tmp_path / "cache"
    cfg.db_path = tmp_path / "music.db"
    cfg.ytm_auth_file = tmp_path / "ytm.json"
    cfg.password = "titok"
    cfg.web_dir = tmp_path / "nincs"
    cfg.download_delay_s = 0
    cfg.enable_background = False
    ytm = FakeYTM()
    dl = FakeDownloader()
    app = create_app(cfg, ytm=ytm, downloader=dl)
    with TestClient(app) as client:
        app.state.cache.start()
        tok = client.post("/api/login", json={"password": "titok"}).json()["token"]
        client.headers["Authorization"] = f"Bearer {tok}"
        yield type("Env", (), dict(client=client, app=app, ytm=ytm, dl=dl, cfg=cfg, token=tok, db=app.state.db,
                                   cache=app.state.cache, sync=app.state.sync, hub=app.state.hub))
        app.state.cache.stop()
