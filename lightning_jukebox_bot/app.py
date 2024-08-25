from contextlib import asynccontextmanager

from fastapi import FastAPI

from lightning_jukebox_bot import api
from lightning_jukebox_bot.application import telegram
from lightning_jukebox_bot.ui.static import static


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with telegram.app:
        await telegram.app.start()
        yield
        await telegram.app.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(api.router)
app.mount("/static", static, name="static")
