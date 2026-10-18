import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import updater
from .api import check_ws_token, router
from .cache import Cache
from .config import Config
from .db import Database
from .downloader import YtDlpDownloader
from .library import Library
from .lyrics import Lyrics
from .playlists import Playlists
from .remote import Hub
from .settings import Settings
from .sync import Sync
from .ytm import YTM

log = logging.getLogger("app")


def create_app(cfg: Config | None = None, ytm=None, downloader=None) -> FastAPI:
    cfg = cfg or Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(cfg.db_path)
    st = Settings(db, cfg)
    lib = Library(db)
    pls = Playlists(db)
    ytm = ytm or YTM(cfg.ytm_auth_file)
    dl = downloader or YtDlpDownloader(cfg)
    cache = Cache(cfg, db, dl, st, lib)
    hub = Hub()
    sync = Sync(db, ytm, lib, pls, st, on_change=lambda: hub.broadcast_threadsafe({"type": "library_changed"}))

    @asynccontextmanager
    async def lifespan(app):
        cache.reconcile()
        if cfg.enable_background:
            cache.start()
            sync.start()
            updater.start_background()
        yield
        cache.stop()
        sync.stop()

    app = FastAPI(title="HomeMusic", lifespan=lifespan)
    app.state.__dict__.update(cfg=cfg, db=db, settings=st, lib=lib, playlists=pls, lyrics=Lyrics(db), ytm=ytm, downloader=dl,
                              cache=cache, hub=hub, sync=sync)
    app.include_router(router)

    @app.websocket("/ws")
    async def ws(ws: WebSocket):
        q = ws.query_params
        if not check_ws_token(app, q.get("token")):
            await ws.close(code=4401)
            return
        did = (q.get("device_id") or "device")[:64]
        await hub.handle(ws, did, (q.get("name") or "Eszköz")[:80], (q.get("kind") or "web")[:20])

    web = Path(cfg.web_dir)
    if (web / "index.html").exists():
        if (web / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (web / path).resolve()
            if path and f.is_file() and web.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(web / "index.html", headers={"Cache-Control": "no-store"})

    return app
