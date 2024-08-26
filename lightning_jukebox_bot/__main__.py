import uvicorn

from lightning_jukebox_bot.app import app
from lightning_jukebox_bot.settings import config

uvicorn_args = {"port": config.port}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", use_colors=False, **uvicorn_args)
