"""yt-dlp as a subprocess (so `pip install -U yt-dlp` applies without restart)."""
import logging
import re
import shlex
import subprocess
from pathlib import Path

log = logging.getLogger("downloader")
VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class DownloadError(Exception):
    pass


class YtDlpDownloader:
    def __init__(self, cfg):
        self.cfg = cfg

    def _run(self, vid: str, dest: Path, cookies: bool) -> Path:
        cmd = [*shlex.split(self.cfg.ytdlp_cmd), "-f", "bestaudio[ext=m4a]/bestaudio/best", "--no-playlist", "--no-warnings",
               "--no-progress", "--socket-timeout", "20", "--retries", "3", "-o", str(dest / "%(id)s.%(ext)s"),
               "--print", "after_move:filepath", *shlex.split(self.cfg.ytdlp_args)]
        if cookies and self.cfg.cookies_file.exists():
            cmd += ["--cookies", str(self.cfg.cookies_file)]
        cmd.append(f"https://music.youtube.com/watch?v={vid}")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise DownloadError(str(e)) from e
        if r.returncode != 0:
            raise DownloadError((r.stderr or r.stdout or "yt-dlp error").strip()[-500:])
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        if not lines or not Path(lines[-1]).is_file():
            raise DownloadError("yt-dlp did not produce a file")
        return Path(lines[-1])

    def download(self, video_id: str, dest_dir) -> Path:
        if not VID_RE.match(video_id):
            raise DownloadError("invalid video id")
        dest = Path(dest_dir)
        try:
            return self._run(video_id, dest, cookies=False)
        except DownloadError as e:
            if ("Sign in" in str(e) or "confirm you" in str(e)) and self.cfg.cookies_file.exists():
                log.warning("bot check for %s, retrying with cookies", video_id)
                return self._run(video_id, dest, cookies=True)
            raise
