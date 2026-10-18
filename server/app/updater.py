"""A yt-dlp gyakran frissül, mert a YouTube változik. Naponta egyszer megpróbáljuk frissíteni futás közben,
és a modult kiürítjük a memóriából, hogy a következő letöltés már az újat használja."""
import logging
import subprocess
import sys
import threading
import time

log = logging.getLogger("updater")


def update_once() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "--quiet", "--break-system-packages", "yt-dlp"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            log.info("yt-dlp frissítés nem sikerült: %s", r.stderr.strip()[:200])
            return False
        for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
            del sys.modules[name]
        log.info("yt-dlp frissítve")
        return True
    except Exception as e:  # noqa: BLE001
        log.info("yt-dlp frissítés kihagyva: %s", e)
        return False


def start_background(interval_h: int = 24) -> None:
    def loop():
        time.sleep(30)
        while True:
            update_once()
            time.sleep(interval_h * 3600)
    threading.Thread(target=loop, name="ytdlp-update", daemon=True).start()
