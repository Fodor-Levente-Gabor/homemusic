"""Real YTM class (normalisation + artist fallback) behind the real HTTP API, with a mocked ytmusicapi client."""
import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app
from app.ytm import YTM


class MockClient:
    """get_artist rejects ids the way YouTube does (HTTP 400) unless they are the 'good' music-artist id."""
    def __init__(self, bad_everything=False):
        self.bad_everything = bad_everything
        self.calls = []

    def get_artist(self, cid):
        self.calls.append(cid)
        if self.bad_everything or cid != "UCgood":
            raise RuntimeError("Server returned HTTP 400: Bad Request. Request contains an invalid argument.")
        return {"name": "Jó Együttes", "description": "leírás", "thumbnails": [{"url": "http://x/a.jpg", "width": 1, "height": 1}],
                "songs": {"results": [{"videoId": "abcdefghijk", "title": "Dal 1", "artists": [{"name": "Jó Együttes", "id": "UCgood"}],
                                        "album": {"name": "Album", "id": "MPREa"}, "thumbnails": []}]},
                "albums": {"results": [{"browseId": "MPREa", "title": "Album", "year": "2020", "thumbnails": []}]}}

    def search(self, q, filter=None, limit=20):
        if filter == "artists":
            return [{"resultType": "artist", "browseId": "UCgood", "artist": "Jó Együttes", "thumbnails": []}]
        if filter == "songs":
            return [{"resultType": "song", "videoId": "zzzzzzzzzzz", "title": "Keresett dal", "artists": [{"name": q}], "duration": "3:21", "thumbnails": []}]
        if filter == "albums":
            return [{"resultType": "album", "browseId": "MPREb", "title": "Keresett album", "thumbnails": []}]
        return [{"resultType": "artist", "browseId": "UCbad", "artist": "Jó Együttes", "thumbnails": []}]


def make(tmp_path, client):
    cfg = Config(data_dir=tmp_path, web_dir=tmp_path / "nincs", password="titok", enable_background=False)
    ytm = YTM(cfg.ytm_auth_file)
    ytm._c = client
    app = create_app(cfg, ytm=ytm, downloader=object())
    c = TestClient(app)
    c.__enter__()
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"password": "titok"}).json()["token"]
    return c


def test_artist_good_id(tmp_path):
    c = make(tmp_path, MockClient())
    r = c.get("/api/artist/UCgood").json()
    assert r["name"] == "Jó Együttes" and [t["video_id"] for t in r["sections"]["songs"]] == ["abcdefghijk"]
    assert r["sections"]["albums"][0]["type"] == "album" and not r.get("fallback")


def test_artist_bad_id_retries_with_search_result_id(tmp_path):
    c = make(tmp_path, MockClient())
    r = c.get("/api/artist/UCbad?name=J%C3%B3%20Egy%C3%BCttes").json()      # YouTube answers 400 for UCbad
    assert r["name"] == "Jó Együttes" and r["sections"]["songs"] and not r.get("fallback")


def test_artist_name_remembered_from_search_when_client_sends_only_id(tmp_path):
    c = make(tmp_path, MockClient())
    found = c.get("/api/search?q=jo").json()
    assert found[0]["type"] == "artist" and found[0]["id"] == "UCbad"
    r = c.get("/api/artist/UCbad").json()                                      # no ?name= (old client / bookmark)
    assert r["name"] == "Jó Együttes" and r["sections"]["songs"]


def test_artist_total_failure_falls_back_to_song_search(tmp_path):
    c = make(tmp_path, MockClient(bad_everything=True))
    r = c.get("/api/artist/UCbad?name=Valaki").json()
    assert r["fallback"] is True and r["sections"]["songs"][0]["title"] == "Keresett dal" and r["sections"]["albums"]
    assert c.get("/api/artist/UCunknown").status_code == 502                    # no name known at all: clear error


def test_artist_by_name_only(tmp_path):
    c = make(tmp_path, MockClient())
    r = c.get("/api/artist/_?name=J%C3%B3%20Egy%C3%BCttes").json()           # clicked on a name in a track row
    assert r["name"] == "Jó Együttes" and r["sections"]["songs"] and not r.get("fallback")


def test_artist_fallback_keeps_slash_and_apostrophe_names(tmp_path):
    c = make(tmp_path, MockClient(bad_everything=True))
    for nm in ("AC/DC", "Guns N' Roses"):
        r = c.get("/api/artist/UCx", params={"name": nm}).json()
        assert r["fallback"] and r["name"] == nm and r["sections"]["songs"]


def test_search_artist_without_title_key_still_has_name():
    from app.ytm import item
    for d in ({"resultType": "profile", "browseId": "UC1", "name": "Azahriah"}, {"resultType": "artist", "browseId": "UC1", "name": "Azahriah"},
              {"resultType": "artist", "browseId": "UC1", "artist": "Azahriah"}):
        assert item(d)["title"] == "Azahriah" and item(d)["type"] == "artist"
