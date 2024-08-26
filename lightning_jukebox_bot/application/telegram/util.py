import json
import logging
import random

import aiomqtt
import spotipy
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from lightning_jukebox_bot.application import invoicing, spotify, users
from lightning_jukebox_bot.application.telegram import app, helper, messages
from lightning_jukebox_bot.application.telegram.helper import TelegramCommand
from lightning_jukebox_bot.settings import config

logger = logging.getLogger(__name__)


message_debounce = {}
now_playing_message = {}


def debounce(func):
    """
    This decorator function manages the debouncing of message when executing commands
    """

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # debounce to prevent the same message being processed twice
        if (
            update.effective_chat.id in message_debounce
            and update.message.id <= message_debounce[update.effective_chat.id]
        ):
            logger.info("Message bounced")
            return wrapper
        else:
            message_debounce[update.effective_chat.id] = update.message.id
            await func(update, context)

            # delete the command from the user
            try:
                await update.message.delete()
            except:
                logger.warning("Failed to delete message")

    return wrapper


def adminonly(func):
    """
    This decorator function manages that only admin in a group chat are allowed to execute the function
    """

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin = False
        if update.message.chat.type == "private":
            admin = True
        else:
            for member in await context.bot.get_chat_administrators(update.message.chat.id):
                if member.user.id == update.effective_user.id and member.status in [
                    "administrator",
                    "creator",
                ]:
                    admin = True
        if admin == True:
            await func(update, context)
            return

        # say to user to go away
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.you_are_not_admin)
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )
        return

    return wrapper


# delete telegram messages
# This function is used in callbacks to enable the deletion of messages from users or the bot itself after some time
async def delete_message(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.job.data["message"].delete()
    except:
        logging.warning("Could not delete message")


# callback for button presses
async def callback_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    This functions handles all button presses that are fed back into the application
    """
    key = update.callback_query.data

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    await update.callback_query.answer()

    if key is None:
        return

    command = helper.get_command(key)

    if command is None:
        logging.info("Command is None")
        return

    # parse the callback data.
    # TODO: Should convert this into an access reference map pattern

    # only the user that requested the track can select a track
    # or when the userid is explicitly set to 0
    if command.userid != 0 and command.userid != update.effective_user.id:
        logging.debug("Avoiding real click")
        return

    # process the various commands
    # cancel command
    if command.command == helper.cancel:
        """
        Cancel just deletes the message
        """
        await update.callback_query.delete_message()
        return

    if command.command == helper.cancelinvoice:
        await update.callback_query.delete_message()

        invoice = command.data
        if invoice is not None:
            await invoicing.helper.delete_invoice(invoice.payment_hash)
        return

    # the commands from here on modify a list of tracks to be queue
    # and we have to check hat we have spotify available
    # get an auth managher, if no auth manager is available, dump a message
    auth_manager = await spotify.helper.get_auth_manager(update.effective_chat.id)
    if auth_manager is None:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text="Bot not connected to player. The admin should perform the /couple command to authorize the bot.",
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )
        return

    # create spotify instance
    sp = spotipy.Spotify(auth_manager=auth_manager)

    # verify that player is available, otherwise it has no use to queue a track
    track = sp.current_user_playing_track()
    if track is None:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text="Player is not active at the moment. Payment aborted.",
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )
        return

    # Play a random track from a playli st
    spotify_uri_list = []
    if command.command == helper.add:
        # add a single track to the list
        spotify_uri_list = [command.data]
        await update.callback_query.delete_message()
    elif command.command == helper.playrandom:
        playlistid = command.data
        result = sp.playlist_items(playlistid, offset=0, limit=1)
        idxs = random.sample(range(0, result["total"]), 1)
        for idx in idxs:
            result = sp.playlist_items(playlistid, offset=idx, limit=1)
            for item in result["items"]:
                spotify_uri_list.append(item["track"]["uri"])
    else:
        logging.error(f"Unknown command: {command.command}")
        return

    # validate payment conditions
    payment_required = True
    amount_to_pay = int((await spotify.helper.get_price(update.effective_chat.id)) * len(spotify_uri_list))
    logging.info(f"Amount to pay = {amount_to_pay}")
    if amount_to_pay == 0:
        payment_required = False

    # if no payment required, add the tracks to the queue one by one
    if payment_required == False:
        spotify.helper.add_to_queue(sp, spotify_uri_list)

        for uri in spotify_uri_list:
            tracktitle = spotify.helper.get_track_title(sp.track(uri))

            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    parse_mode="HTML",
                    text=f"@{update.effective_user.username} added '{tracktitle}' to the queue.",
                )
            except:
                pass

            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    parse_mode="HTML",
                    text=f"You added '{tracktitle}' to the queue for {amount_to_pay} sats.",
                )
            except:
                pass

            try:
                async with aiomqtt.Client("localhost") as client:
                    await client.publish(f"{update.effective_chat.id}/added_to_queue", payload=tracktitle)
            except:
                logging.error("Exception when publishing queue add to mqtt")
                pass

        # return
        return

    # create an invoice title
    invoice_title = f"'{spotify.helper.get_track_title(sp.track(spotify_uri_list[0]))}'"
    for i in range(1, len(spotify_uri_list)):
        invoice_title += f",'{spotify.helper.get_track_title(sp.track(spotify_uri_list[0]))}'"

    # create the invoice
    # the owner is the one that has his spotify player connected
    recipient = await users.helper.get_group_owner(update.effective_chat.id)
    invoice = await invoicing.helper.create_invoice(recipient, amount_to_pay, invoice_title)

    # get the user wallet and try to pay the invoice
    user = await users.helper.get_or_create_user(update.effective_user.id, update.effective_user.username)
    invoice.user = user
    invoice.title = invoice_title
    invoice.recipient = recipient
    invoice.spotify_uri_list = spotify_uri_list
    invoice.title = invoice_title
    invoice.chat_id = update.effective_chat.id
    invoice.amount_to_pay = amount_to_pay

    # pay the invoice
    payment_result = await invoicing.helper.pay_invoice(invoice.user, invoice)

    # if payment success
    if payment_result["result"] == True:
        spotify.helper.add_to_queue(sp, spotify_uri_list)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text=f"@{update.effective_user.username} added {invoice_title} to the queue.",
        )
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                parse_mode="HTML",
                text=f"You paid {amount_to_pay} sats for {invoice_title}.",
            )
        except:
            logging.info("Could not send message to user")

        try:
            async with aiomqtt.Client("localhost") as client:
                await client.publish(f"{update.effective_chat.id}/added_to_queue", payload=invoice_title)
        except:
            logging.error("Exception when publishing queue add to mqtt")
            pass

        # make donation to the bot
        jukeboxbot = await users.helper.get_or_create_user(config.bot_id)
        donation_amount: int = await spotify.helper.get_donation_fee(invoice.chat_id)
        donation_amount = min(donation_amount, invoice.amount_to_pay)
        donation_invoice = await invoicing.helper.create_invoice(jukeboxbot, donation_amount, "donation to the bot")
        result = await invoicing.helper.pay_invoice(recipient, donation_invoice)

        return

    # store the invoice in a list of open invoices
    # add extra data

    # we failed paying the invoice, popup the lnurlp
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"@{update.effective_user.username} add '{invoice_title}' to the queue?\n\nClick to pay below or fund the bot with /fund@Jukebox_Lightning_bot.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Pay {amount_to_pay} sats",
                        url=f"https://{config.domain}/jukebox/payinvoice?payment_hash={invoice.payment_hash}",
                    ),
                    InlineKeyboardButton(
                        "Cancel",
                        callback_data=helper.add_command(
                            TelegramCommand(
                                update.effective_user.id,
                                helper.cancelinvoice,
                                invoice,
                            )
                        ),
                    ),
                ]
            ]
        ),
    )

    # add data to the invoice
    invoice.message_id = message.id

    # and save the invoice
    await invoicing.helper.save_invoice(invoice)

    # change this into an SSE
    # start a loop to check the invoice, for a period of 10 minutes
    app.job_queue.run_once(check_invoice_callback, 15, data=invoice)


async def check_invoice_callback(context: ContextTypes.DEFAULT_TYPE):
    """
    This function checks an invoice if it has been paid
    if it does not exist anymore, or the timeout is expired, the callback stops
    """
    invoice = context.job.data
    if invoice is None:
        logging.error("Got callback with a None invoice")
        return

    redis_invoice = await invoicing.helper.get_invoice(invoice.payment_hash)
    if redis_invoice is None:
        logging.info("Invoice no longer exists, probably has been paid or canceled")
        return

    # check if invoice was paid
    if await invoicing.helper.invoice_paid(invoice) == True:
        await callback_paid_invoice(invoice)
        return

    # invoice has not been paid
    invoice.ttl -= 15
    if invoice.ttl <= 0:
        await invoicing.helper.delete_invoice(invoice.payment_hash)
        try:
            await context.bot.delete_message(invoice.chat_id, invoice.message_id)
        except:
            pass
    else:
        app.job_queue.run_once(check_invoice_callback, 15, data=invoice)


async def regular_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    This function performs tasks to clean up stuff at regular intervals
    just empties the now playing list so that the callback_spotify function creates a new message
    """
    logging.info("Running regular clean up")
    for chatid in list(now_playing_message.keys()):
        del now_playing_message[chatid]

    helper.purge_commands()


async def callback_spotify(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    This function creates a message of the current playing track. It reschedules itself depending on the remaining time
    for the current playing track. Basically two seconds after the time, the first track has finished playing
    """

    interval = 300
    try:
        for key in config.rds.scan_iter("group:*"):
            # logging.info(f"callback_spotify for group {key}")
            chat_id = key.decode("utf-8").split(":")[1]
            auth_manager = await spotify.helper.get_auth_manager(chat_id)
            if auth_manager is None:
                # logging.warning("Auth manager is None in callback_spotify")
                continue

            currenttrack = None
            try:
                sp = spotipy.Spotify(auth_manager=auth_manager)
                currenttrack = sp.current_user_playing_track()
            except:
                # logging.info("Exception while querying the current playing track at spotify")
                continue

            title = "Nothing playing at the moment"
            if currenttrack is not None and "item" in currenttrack and currenttrack["item"] is not None:
                title = spotify.helper.get_track_title(currenttrack["item"])

                # update history
                await spotify.helper.update_history(chat_id, title)

                newinterval = (currenttrack["item"]["duration_ms"] - currenttrack["progress_ms"]) / 1000 + 2
                if newinterval < interval:
                    interval = newinterval
            elif currenttrack is not None:
                logging.info(json.dumps(currenttrack))

            # update the title
            if chat_id in now_playing_message:
                [message_id, prev_title] = now_playing_message[chat_id]
                if prev_title != title:
                    try:
                        await context.bot.editMessageText(title, chat_id=chat_id, message_id=message_id)
                        now_playing_message[chat_id] = [message_id, title]
                        logging.info(f"Now playing {title} in chat {chat_id}")
                    except:
                        # logging.error("Exception when refreshing now playing")
                        pass

                    try:
                        async with aiomqtt.Client("localhost") as client:
                            await client.publish(f"{chat_id}/now_playing", payload=title)
                    except:
                        logging.error("Exception when publishing current track to mqtt")
                        pass

            else:
                logging.info("Creating new pinned message")
                try:
                    message = await context.bot.send_message(text=title, chat_id=chat_id)
                    await context.bot.pin_chat_message(chat_id=chat_id, message_id=message.id)
                    now_playing_message[chat_id] = [message.id, title]
                except:
                    logging.error("Exception when sending message to group")
    except:
        logging.error("Unhandled exception in callback_spotify")
    finally:
        if interval < 30 or interval > 300:
            interval = 30
        logging.info(f"Next run in {interval} seconds")
        context.job_queue.run_once(callback_spotify, interval, job_kwargs={"misfire_grace_time": None})


async def callback_paid_invoice(invoice: Invoice):
    if invoice is None:
        logging.error("Invoice is None")
        return
    logging.info("callback_paid_invoice")
    logging.info(invoice.to_json())

    if invoice.chat_id is None:
        logging.error("Invoice chat_id is None")
        return

    if await invoicing.helper.delete_invoice(invoice.payment_hash) == False:
        logging.info("invoicing.helper.delete_invoice returned False")
        return

    auth_manager = await spotify.helper.get_auth_manager(invoice.chat_id)
    if auth_manager is None:
        logging.error("No auth manager after succesfull payment")
        return

    try:
        logging.info(f"Trying to delete chat_id {invoice.chat_id}, messageid {invoice.message_id}")
        await app.bot.delete_message(invoice.chat_id, invoice.message_id)
    except:
        pass

    # add to the queue and inform others
    sp = spotipy.Spotify(auth_manager=auth_manager)

    spotify.helper.add_to_queue(sp, invoice.spotify_uri_list)
    try:
        await app.bot.send_message(
            chat_id=invoice.chat_id,
            parse_mode="HTML",
            text=f"'{invoice.title}' was added to the queue.",
        )
    except:
        logging.error("Could not  send message to the group that track was added to the queue")

    try:
        async with aiomqtt.Client("localhost") as client:
            await client.publish(f"{invoice.chat_id}/added_to_queue", payload=invoice.title)
    except:
        logging.error("Exception when publishing queue add to mqtt")
        pass

    if False:
        try:
            await application.bot.send_message(
                chat_id=invoice.user.userid,
                parse_mode="HTML",
                text=f"You paid {invoice.amount_to_pay} sats for {invoice.title}.",
            )
        except:
            logging.info("Could not send individual message to user that")

    # make donation to the bot
    jukeboxbot = await userhelper.get_or_create_user(settings.bot_id)
    donator = await userhelper.get_or_create_user(invoice.recipient.userid)
    donation_amount: int = await spotify.helper.get_donation_fee(invoice.chat_id)
    donation_amount = min(donation_amount, invoice.amount_to_pay)
    donation_invoice = await invoicing.helper.create_invoice(jukeboxbot, donation_amount, "donation to the bot")
    result = await invoicing.helper.pay_invoice(donator, donation_invoice)

    return
