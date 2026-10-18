import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).resolve()


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: _env_path("DATA_DIR", "./data"))
    cache_dir: Path | None = None
    db_path: Path | None = None
    ytm_auth_file: Path | None = None
    web_dir: Path = field(default_factory=lambda: _env_path("WEB_DIR", "./web_dist"))
    password: str = field(default_factory=lambda: os.environ.get("APP_PASSWORD", ""))
    cache_limit_gb: float = field(default_factory=lambda: float(os.environ.get("CACHE_LIMIT_GB", "100")))
    download_delay_s: float = 2.0
    enable_background: bool = True
    ytdlp_cmd: str = field(default_factory=lambda: os.environ.get("YTDLP_CMD", "python3 -m yt_dlp"))
    ytdlp_args: str = field(default_factory=lambda: os.environ.get("YTDLP_ARGS", "--js-runtimes deno"))
    lrclib_url: str = "https://lrclib.net/api"

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.cache_dir = Path(self.cache_dir or self.data_dir / "cache")
        self.db_path = Path(self.db_path or self.data_dir / "music.db")
        self.ytm_auth_file = Path(self.ytm_auth_file or self.data_dir / "ytm.json")

    @property
    def cookies_file(self) -> Path:
        return self.ytm_auth_file.parent / "cookies.txt"
