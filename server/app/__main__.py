import logging
import os

import uvicorn

from .main import create_app

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="info")
