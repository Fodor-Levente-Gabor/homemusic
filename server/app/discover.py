"""Felfedezés / véletlen lejátszás.

  random_mix:   véletlenszerű hangulat/műfaj kategóriák véletlen lejátszási listáiból, összekeverve
                (NEM a saját listáidból)
  familiar_mix: a legtöbbet hallgatott (vagy ha még nincs előzmény, a kedvelt) számaid YT Music rádiói,
                összekeverve: ismerős hangzás, de nem a saját listáid tartalma"""
import logging
import random
from typing import Any

from .library import Library

log = logging.getLogger("discover")


def _dedupe(tracks: list[dict[str, Any]], exclude: set[str] | None = None) -> list[dict[str, Any]]:
    seen = set(exclude or ())
    out = []
    for t in tracks:
        if t["video_id"] in seen:
            continue
        seen.add(t["video_id"])
        out.append(t)
    return out


def random_mix(ytm, size: int = 50, categories: int = 3, rng: random.Random | None = None) -> list[dict[str, Any]]:
    rng = rng or random.Random()
    cats = ytm.mood_categories()
    rng.shuffle(cats)
    tracks: list[dict[str, Any]] = []
    for cat in cats[: categories + 3]:
        if len({t["video_id"] for t in tracks}) >= size * 2 or categories <= 0:
            break
        try:
            pls = [p for p in ytm.mood_playlists(cat["params"]) if p["type"] == "playlist"]
            if not pls:
                continue
            pl = rng.choice(pls)
            tracks += ytm.playlist(pl["id"], limit=60)["tracks"]
            categories -= 1
        except Exception as e:  # noqa: BLE001
            log.info("mood kategória kihagyva: %s", e)
    tracks = _dedupe(tracks)
    rng.shuffle(tracks)
    return tracks[:size]


def familiar_mix(ytm, lib: Library, size: int = 50, rng: random.Random | None = None) -> list[dict[str, Any]]:
    rng = rng or random.Random()
    pool = lib.top_tracks(30) or lib.liked_tracks()[:60]
    if not pool:
        return []
    weights = [max(1, t.get("play_count", 0)) for t in pool]
    seeds: list[dict[str, Any]] = []
    candidates = list(zip(pool, weights))
    for _ in range(min(4, len(pool))):
        total = sum(w for _, w in candidates)
        r = rng.uniform(0, total)
        acc = 0.0
        for i, (t, w) in enumerate(candidates):
            acc += w
            if acc >= r:
                seeds.append(t)
                candidates.pop(i)
                break
    tracks: list[dict[str, Any]] = []
    for s in seeds:
        try:
            tracks += ytm.radio(s["video_id"], limit=30)
        except Exception as e:  # noqa: BLE001
            log.info("rádió kihagyva: %s", e)
    tracks = _dedupe(tracks)
    rng.shuffle(tracks)
    return tracks[:size]
