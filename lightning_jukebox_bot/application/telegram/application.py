from telegram.ext import Application

from lightning_jukebox_bot.settings import config

app = Application.builder().token(config.bot_token).updater(None).build()
