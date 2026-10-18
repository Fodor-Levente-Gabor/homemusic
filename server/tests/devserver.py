"""Demo/fejlesztői szerver hamis YT Music-kal és hamis letöltővel (nincs szükség internetre).
Futtatás: python tests/devserver.py   ->  http://localhost:8099 (jelszó: titok)"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

from app.config import Config  # noqa: E402
from app.main import create_app  # noqa: E402
from conftest import FakeYTM, T  # noqa: E402


class OpusDownloader:
    def download(self, video_id, dest_dir):
        out = Path(dest_dir) / f"{video_id}.webm"
        freq = 200 + (sum(map(ord, video_id)) % 500)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=12:sample_rate=48000",
                        "-c:a", "libopus", str(out)], check=True)
        return out


class DemoYTM(FakeYTM):
    def search(self, q, filter=None, limit=25):
        return [{"type": "track", **{**T(f"demo{i}", f"{q} {i}", "AC/DC" if i == 1 else f"Előadó {i}"), "duration_sec": 12}} for i in range(1, 6)] + \
               [{"type": "album", "id": "MPREdemo", "title": "Demo album", "subtitle": "Valaki", "thumbnail": None}]
    def home(self):
        return [{"title": "Gyors választás", "items": [{"type": "track", **{**T(f"home{i}", f"Dal {i}", "Valaki"), "duration_sec": 12}} for i in range(1, 7)]}]
    def artist(self, cid, name=None):
        return {"id": cid, "name": name or "?", "description": "", "thumbnail": None, "fallback": cid != "_",
                "sections": {"songs": [{"type": "track", **{**T(f"art{i}", f"{name} dal {i}", name or "?"), "duration_sec": 12}} for i in range(1, 4)]}}
    def radio(self, vid, limit=50, shuffle=False):
        return [{**T(f"{vid}_r{i}", f"Rádió {i}", "Rádió"), "duration_sec": 12} for i in range(5)]


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp())
    cfg = Config()
    cfg.data_dir = d; cfg.cache_dir = d / "cache"; cfg.db_path = d / "music.db"; cfg.ytm_auth_file = d / "ytm.json"
    cfg.password = "titok"; cfg.web_dir = Path(__file__).resolve().parents[2] / "web" / "dist"; cfg.download_delay_s = 0
    cfg.enable_background = True
    ytm = DemoYTM()
    uvicorn.run(create_app(cfg, ytm=ytm, downloader=OpusDownloader()), host="127.0.0.1", port=8099, log_level="warning")
