from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from lightning_jukebox_bot import settings

from . import helper  # noqa: F401

app = Application.builder().token(settings.config.bot_token).updater(None).build()

# register handlers
app.add_handler(CommandHandler("add", search))  # search for a track
app.add_handler(CommandHandler(["stack", "balance"], balance))  # view wallet balance
app.add_handler(CommandHandler("couple", connect))  # connect to spotify account
app.add_handler(CommandHandler("decouple", disconnect))  # disconnect from spotify account
app.add_handler(CommandHandler("fund", fund))  # add funds to wallet
app.add_handler(CommandHandler("history", history))  # view history of tracks
app.add_handler(CommandHandler("link", link))  # view LNDHUB QR
app.add_handler(CommandHandler("refund", pay))  # pay a lightning invoice
app.add_handler(CommandHandler("price", price))  # set the track price
app.add_handler(CommandHandler("queue", queue))  # view the queue
app.add_handler(CommandHandler("service", service))  # service notifications to bot users
app.add_handler(CommandHandler("setclientsecret", spotify_settings))  # set the secret for a spotify app
app.add_handler(CommandHandler("setclientid", spotify_settings))  # set the clientid or a spotify app
app.add_handler(CommandHandler("stats", stats))  # dump various stats
app.add_handler(CommandHandler(["start", "faq"], start))  # help message
app.add_handler(CommandHandler("dj", dj))  # pay another user
app.add_handler(CommandHandler("web", web))  # display the web URL

app.add_handler(CallbackQueryHandler(callback_button))
app.job_queue.run_repeating(regular_cleanup, 12 * 3600)
app.job_queue.run_once(callback_spotify, 2)
