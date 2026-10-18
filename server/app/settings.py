import json

DEFAULTS = {
    "cache_limit_gb": 100.0, "crossfade_ms": 0, "gapless": True, "normalize": True, "target_lufs": -14.0,
    "eq_enabled": False, "eq_gains": [0.0] * 10, "preamp_db": 0.0, "sync_interval_min": 15,
    "lyrics_prefill": True, "prefetch_count": 2,
}


class Settings:
    def __init__(self, db, cfg):
        self.db, self.cfg = db, cfg

    def all(self) -> dict:
        d = dict(DEFAULTS)
        d["cache_limit_gb"] = float(self.cfg.cache_limit_gb)
        with self.db.conn() as c:
            for r in c.execute("SELECT key,value_json FROM settings"):
                if r["key"] in DEFAULTS:
                    try:
                        d[r["key"]] = json.loads(r["value_json"])
                    except ValueError:
                        pass
        return d

    def get(self, key):
        return self.all()[key]

    def update(self, changes: dict) -> dict:
        clean = {}
        for k, v in changes.items():
            if k not in DEFAULTS:
                continue
            base = DEFAULTS[k]
            try:
                if isinstance(base, bool):
                    v = bool(v)
                elif isinstance(base, list):
                    v = [float(x) for x in v][:10]
                    v += [0.0] * (10 - len(v))
                elif isinstance(base, (int, float)):
                    v = type(base)(v)
            except (TypeError, ValueError):
                continue
            if k == "cache_limit_gb":
                v = max(0.01, v)
            if k == "crossfade_ms":
                v = max(0, min(12000, v))
            if k == "sync_interval_min":
                v = max(1, v)
            if k == "prefetch_count":
                v = max(0, min(10, v))
            clean[k] = v
        with self.db.conn() as c:
            for k, v in clean.items():
                c.execute("INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                          (k, json.dumps(v)))
        return self.all()
