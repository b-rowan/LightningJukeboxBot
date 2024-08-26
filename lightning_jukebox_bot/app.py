import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lightning_jukebox_bot import api
from lightning_jukebox_bot.application import telegram
from lightning_jukebox_bot.settings import config
from lightning_jukebox_bot.ui.static import static

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with telegram.app:
        logger.info(f'Jukebox url: "https://{config.domain}/jukebox/telegram"')
        logger.info(f"Jukebox IP: {config.ipaddress}")
        await telegram.app.bot.set_webhook(
            url=f"https://{config.domain}/jukebox/telegram",
            allowed_updates=["callback_query", "message"],
            ip_address=config.ipaddress,
        )

        await telegram.app.start()
        yield
        await telegram.app.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(api.router)
app.mount("/static", static, name="static")
