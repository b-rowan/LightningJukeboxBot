from telegram.ext import CallbackQueryHandler, CommandHandler

from . import bot_cmds, helper, util  # noqa: F401
from .application import app

# register handlers
app.add_handler(CommandHandler("add", bot_cmds.search))  # search for a track
app.add_handler(CommandHandler(["stack", "balance"], bot_cmds.balance))  # view wallet balance
app.add_handler(CommandHandler("couple", bot_cmds.connect))  # connect to spotify account
app.add_handler(CommandHandler("decouple", bot_cmds.disconnect))  # disconnect from spotify account
app.add_handler(CommandHandler("fund", bot_cmds.fund))  # add funds to wallet
app.add_handler(CommandHandler("history", bot_cmds.history))  # view history of tracks
app.add_handler(CommandHandler("link", bot_cmds.link))  # view LNDHUB QR
app.add_handler(CommandHandler("refund", bot_cmds.pay))  # pay a lightning invoice
app.add_handler(CommandHandler("price", bot_cmds.price))  # set the track price
app.add_handler(CommandHandler("queue", bot_cmds.queue))  # view the queue
app.add_handler(CommandHandler("service", bot_cmds.service))  # service notifications to bot users
# TODO: does not exist?
app.add_handler(CommandHandler("setclientsecret", bot_cmds.spotify_settings))  # set the secret for a spotify app
app.add_handler(CommandHandler("setclientid", bot_cmds.spotify_settings))  # set the clientid or a spotify app

app.add_handler(CommandHandler("stats", bot_cmds.stats))  # dump various stats
app.add_handler(CommandHandler(["start", "faq"], bot_cmds.start))  # help message
app.add_handler(CommandHandler("dj", bot_cmds.dj))  # pay another user
app.add_handler(CommandHandler("web", bot_cmds.web))  # display the web URL

app.add_handler(CallbackQueryHandler(util.callback_button))
app.job_queue.run_repeating(util.regular_cleanup, 12 * 3600)
app.job_queue.run_once(util.callback_spotify, 2)
