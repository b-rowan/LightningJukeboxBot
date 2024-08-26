import base64
import logging
import os
import re

import qrcode
import spotipy
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from lightning_jukebox_bot.application import invoicing, spotify, telegram, users
from lightning_jukebox_bot.config import config

from ...settings import const
from . import helper, messages
from .helper import TelegramCommand
from .util import adminonly, debounce, delete_message

logger = logging.getLogger(__name__)


@debounce
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    This function searches for tracks in spotify and createas a list of tracks to play
    If a playlist URL is provided, that playlist is used
    This function only works in a group chat
    """

    if update.message.chat.type == "private":
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Execute the /add command in the group instead of the private chat.",
        )
        return

    # get an auth manager, if no auth manager is available, dump a message
    auth_manager = await spotify.helper.get_auth_manager(update.effective_chat.id)
    if auth_manager is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text="Bot not connected to player. The admin should perform the /couple command to authorize the bot.",
        )
        return

    # create spotify instance
    sp = spotipy.Spotify(auth_manager=auth_manager)

    # validate the search string
    searchstr = update.message.text.split(" ", 1)
    if len(searchstr) > 1:
        searchstr = searchstr[1]
    else:
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.ADD_COMMAND_HELP)
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
        return

    # check if the search string is a spotify URL
    match = re.search("https://open.spotify.com/playlist/([A-Za-z0-9]+).*$", searchstr)
    if match:
        playlistid = match.groups()[0]
        result = sp.playlist(playlistid, fields=["name"])
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"@{update.effective_user.username} suggests to play tracks from the '{result['name']}' playlist.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"Pay {await spotify.helper.get_price(update.effective_chat.id)} sats for a random track",
                            callback_data=telegram.helper.add_command(
                                TelegramCommand(0, telegram.helper.playrandom, playlistid)
                            ),
                        )
                    ]
                ]
            ),
        )

        # start a job to kill the message  after 30 seconds if not used
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_long,
            data={"message": message},
        )
        return

    # search for tracks
    numtries: int = 3
    while numtries > 0:
        try:
            result = sp.search(searchstr)
        except spotipy.oauth2.SpotifyOauthError:
            # spotify not properly authenticated
            logger.info("Spotify Oauth error")
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Music player not available, search aborted.",
            )
            return

        except spotipy.exceptions.SpotifyException:
            numtries -= 1
            if numtries == 0:
                # spotify still triggers an exception
                logger.error("Spotify returned and exception, not returning search result")
                message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Music player unavailable, search aborted.",
                )
                return
            logger.warning("Spotify returned and exception, retrying")
            continue

        break

    # create a list of max five buttons, each with a unique song title
    # TODO: May be referenced before assignment
    if len(result["tracks"]["items"]) > 0:
        tracktitles = {}
        button_list = []
        for item in result["tracks"]["items"]:
            title = spotify.helper.get_track_title(item)
            if title not in tracktitles:
                tracktitles[title] = 1
                button_list.append(
                    [
                        InlineKeyboardButton(
                            title,
                            callback_data=telegram.helper.add_command(
                                TelegramCommand(
                                    update.effective_user.id,
                                    telegram.helper.add,
                                    item["uri"],
                                )
                            ),
                        )
                    ]
                )

                # max five suggestions
                if len(tracktitles) == 5:
                    break

        # Add a cancel button to the list
        button_list.append(
            [
                InlineKeyboardButton(
                    "Cancel",
                    callback_data=telegram.helper.add_command(
                        TelegramCommand(update.effective_user.id, telegram.helper.cancel, None)
                    ),
                )
            ]
        )

        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Results for '{searchstr}'",
            reply_markup=InlineKeyboardMarkup(button_list),
        )

        # start a job to kill the search window after 30 seconds if not used
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
    else:
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"No results for '{searchstr}'")
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )


# start command handler, returns help information
@debounce
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # send the message
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=messages.HELP)

    # only create a callback to delete the message when not in a private chat
    if update.message.chat.type != "private":
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )


# display stats
@debounce
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    userid: int = update.effective_user.id

    if update.message.chat.type != "private":
        return

    if userid not in config.superadmins:
        logging.info(f"User {userid} is not a superadmin. Access to stats denied")
        return

    results = await stats.helper.get_jukebox_groups()
    balance = await stats.helper.get_bot_stack()

    statsText = f"Bot balance: {balance} sats \n"

    statsText += f"Number of groups: {results['numgroups']}. List of owners: \n"
    for group in results["group"]:
        if group["owner"] is not None:
            statsText += f" - {group['groupid']} : @{group['owner'].username}\n"
        else:
            statsText += f" - {group['groupid']} : Unknown owner\n"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=statsText)


# get the current balance
@debounce
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # do not show balance in other than private chats
    if update.message.chat.type != "private":
        bot_me = await context.bot.get_me()

        # direct the user to their private chat
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.BALANCE_IN_GROUP,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Take me there", url=f"https://t.me/{bot_me.username}")]]
            ),
        )

        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
        return

    # we're in a private chat now
    user = await users.helper.get_or_create_user(update.effective_user.id, update.effective_user.username)

    # get the balance from LNbits
    balance = await users.helper.get_balance(user)

    # create a message with the balance
    logging.info(f"User {user.userid} balance is {balance} sats")
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Your balance is {balance} sats.")


# Disconnect a spotify player from the bot, the connect command
@debounce
@adminonly
async def disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # this command can only be used in group chats, send instructions if used in a private chat
    if update.message.chat.type == "private":
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text=messages.DISCONNECT_IN_PRIVATE_CHAT,
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )

        # stop here
        return

    # delete the owner of the group, all admins can do this
    await users.helper.delete_group_owner(update.effective_chat.id)
    result = await spotify.helper.delete_auth_manager(update.effective_chat.id)

    # get an auth manager, if no auth manager is available, dump a message
    if result:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text=messages.SPOTIFY_AUTHORISATION_REMOVED,
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
    else:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text=messages.SPOTIFY_AUTHORISATION_REMOVED_ERROR,
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )


# Connect a spotify player to the bot, the connect command
@debounce
# @adminonly
async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # get spotify config for the user
    # TODO: This doesnt exist?
    sps = await spotify.helper.get_spotify_config(update.effective_user.id)

    # this command has to be execute from within a group
    if update.message.chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            parse_mode="HTML",
            text=f"""
To connect this bot to your spotify account, you have to create an app in the developer portal of Spotify <A href="https://developer.spotify.com/dashboard/applications">here</a>.

1. Click on the 'Create an app' button and give the bot a random name and description. Then click 'Create".

2. Record the 'Client ID' and 'Client Secret'.

3. Click 'Edit Settings' and add EXACTLY this url <pre>{config.spotify_redirect_uri}</pre> under 'Redirect URIs'. Do not forget to click 'Add' and 'Save'

4. Use the /setclientid and /setclientsecret commands to configure the 'Client ID' and 'Client Secret'.

5. Give the '/couple' command in the group that you want to connect to your account. That will redirect you to an authorisation page.

""",  # noqa: E501
        )

        # check that client_id is not None
        if sps.client_id is None:
            await context.bot.send_message(chat_id=update.effective_user.id, text=messages.NO_CLIENT_ID_SET)
        else:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=messages.CLIENT_ID_SET.format(sps.client_id),
            )

        # check that client secret is not None
        if sps.client_secret is None:
            await context.bot.send_message(chat_id=update.effective_user.id, text=messages.NO_CLIENT_SECRET_SET)
        else:
            await context.bot.send_message(chat_id=update.effective_user.id, text=messages.CLIENT_SECRET_SET)

        # hint the user for the connect command
        if sps.client_id is not None and sps.client_secret is not None:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=messages.EVERYTHING_SET_NOW_DO_CONNECT,
            )

        return

    # send message in group to go to private chat
    bot_me = await context.bot.get_me()

    # if both variables are not none, ask the user to authorize
    if sps.client_id is not None and sps.client_secret is not None:
        # get an auth manaer
        auth_manager = await spotify.helper.get_auth_manager(update.effective_chat.id)
        if auth_manager is not None:
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="A player is already connected to this group chat. "
                "Disconnect it first using the /decouple command before connecting a new one",
            )
            context.job_queue.run_once(
                delete_message,
                config.delete_message_timeout_short,
                data={"message": message},
            )
            return

        auth_manager = await spotify.helper.init_auth_manager(
            update.effective_chat.id, sps.client_id, sps.client_secret
        )

        # send instructions in the group
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.INSTRUCTIONS_IN_PRIVATE_CHAT,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            messages.BUTTON_TO_PRIVATE_CHAT,
                            url=f"https://t.me/{bot_me.username}",
                        )
                    ]
                ]
            ),
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )

        state = base64.b64encode(f"{update.effective_chat.id}:{update.effective_user.id}".encode("ascii")).decode(
            "ascii"
        )

        # send a message to the private chat of the bot
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=messages.CLICK_THE_BUTTON_TO_AUTHORIZE,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Authorize player",
                            url=auth_manager.get_authorize_url(state=state),
                        )
                    ]
                ]
            ),
        )
    else:
        # send a message that configuration is required
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Additional configuration is required, execute this command in a private chat with me.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Take me there", url=f"https://t.me/{bot_me.username}")]]
            ),
        )

        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )


# display the play queue
@debounce
@adminonly
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="The /price command only works in a group chat.",
        )
        return

    price = await spotify.helper.get_price(update.effective_chat.id)
    donation = await spotify.helper.get_donation_fee(update.effective_chat.id)

    if update.message.text == "/price":
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text=f"Current track price is {price}. Per requested track, {donation} sats is donated to the Jukebox Bot.",
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )
        return

    # parse and validate the price command
    result = re.search("/price\s+([0-9]+)\s+([0-9]+)$", update.message.text)  # noqa: W605
    if result is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Use command as follows: /price <price> <donation>\n"
            "<price> is the track price in sats\n"
            "<donation> is the amount in sats donated to the bot per reqested track. "
            "The donation is subtracted from the track price.",
        )
        return

    newprice = int(result.groups()[0])
    newdonation = int(result.groups()[1])

    if newdonation > newprice:
        newdonation = newprice

    # update
    await spotify.helper.set_price(update.effective_chat.id, newprice)
    await spotify.helper.set_donation_fee(update.effective_chat.id, newdonation)

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Updating price to {newprice} sats. Donation amount is {newdonation} sats.",
    )

    context.job_queue.run_once(
        delete_message,
        config.delete_message_timeout_medium,
        data={"message": update.message},
    )


# display the play queue
@debounce
async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Execute the /queue command in the group instead of the private chat.",
        )
        return

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
    try:
        sp = spotipy.Spotify(auth_manager=auth_manager)
    # TODO: bare except
    except:  # noqa: E722
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Failed to connect to music player"
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
        return

    # get the current track
    try:
        track = sp.current_user_playing_track()
    # TODO: bare except
    except:  # noqa: E722
        track = None

    title = "Nothing is playing at the moment"
    if track:
        title = "🎵 {title} 🎵".format(title=spotify.helper.get_track_title(track["item"]))

    # query the queue
    try:
        result = sp.queue()
    # TODO: bare except
    except:  # noqa: E722
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text="Failed to retrieve queue")
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
        return

    text = ""
    for i in range(min(10, len(result["queue"]))):
        item = result["queue"][i]
        text += " {count}. {title}\n".format(count=(i + 1), title=spotify.helper.get_track_title(item))

    if len(text) == 0:
        text = title + "\nNo items in queue."
    else:
        text = title + "\nUpcoming tracks:\n" + text

    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    context.job_queue.run_once(
        delete_message,
        config.delete_message_timeout_medium,
        data={"message": message},
    )


@debounce
@adminonly
async def service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    This command sends a service message to all Jukebot group owners, that is all users marked as owner of a group
    """
    userid: int = update.effective_user.id

    if update.message.chat.type != "private":
        return

    if userid not in config.superadmins:
        logging.info(f"User {userid} is not a superadmin. Access to stats denied")
        return

    result = re.search("^/service \S.*", update.message.text)  # noqa: W605
    if result is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Use the /service command as follows: /service <message>\nThe message is sent to all owners of bot",
        )
        return

    # set message, strip the command
    msgstr = update.message.text[9:]

    results = await stats.helper.get_jukebox_groups()
    num = 0
    for group in results["group"]:
        # skip if no owner is set
        if group["owner"] is None:
            continue

        # send a message each owner
        try:
            await context.bot.send_message(
                chat_id=group["owner"].userid,
                text=f"Service message from the Jukebox Bot:\n\n{msgstr}\n\nThank you!",
            )
            num += 1
        except TelegramError:
            pass

    # send a message each owner
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"The following message was sent to {num} users:\n\n"
        f"Service message from the Jukebox Bot:\n\n"
        f"{msgstr}\n\n"
        f"Thank you!",
    )


# connect a spotify player to the bot, the setclient secret and set client id commands
@debounce
async def spotify_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type != "private":
        bot_me = await context.bot.get_me()

        # direct the user to their private chat
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Like keeping your mnenomic seedphrase offline, "
            "it is better to perform these actions in a private chat with me.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Take me there", url=f"https://t.me/{bot_me.username}")]]
            ),
        )

        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
        return

    # get spotify config for the user
    # TODO: This doesnt exist?
    sps = await spotify.helper.get_spotify_config(update.effective_user.id)

    result = re.search("/(setclientid|setclientsecret)\s+([a-z0-9]+)\s*$", update.message.text)  # noqa: W605
    if result is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Incorrect usage. ")
        return

    # after validation
    command = result.groups()[0]
    value = result.groups()[1]

    bSave = False
    if command == "setclientid":
        sps.client_id = value
        bSave = True

    if command == "setclientsecret":
        sps.client_secret = value
        bSave = True

    if bSave:
        # TODO: doesnt exist
        await spotify.helper.save_spotify_config(sps)
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Settings updated. Type /couple for current config and instructions.",
        )


# fund the wallet of the user
@debounce
async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await users.helper.get_or_create_user(update.effective_user.id, update.effective_user.username)

    text = f"Click on the button to fund the wallet of @{user.username}."
    if user.lnaddress is not None:
        text += f"\nYou can also fund the wallet by sending sats to the following address: {user.lnaddress}"

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Fund sats",
                        url=f"https://{config.domain}/jukebox/fund"
                        f"?command={helper.add_command(TelegramCommand(update.effective_user.id,'FUND'))}",
                    )
                ]
            ]
        ),
    )
    context.job_queue.run_once(delete_message, config.delete_message_timeout_long, data={"message": message})


# view the history of recently played tracks
@debounce
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type == "private":
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Execute the /history command in the group instead of the private chat.",
        )
        return

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
    # TODO: unused
    # sp = spotipy.Spotify(auth_manager=auth_manager)

    text = "Track history:\n"
    history = await spotify.helper.get_history(update.effective_chat.id, 20)
    for title in history:
        text += f"{title}\n"

    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    context.job_queue.run_once(
        delete_message,
        config.delete_message_timeout_medium,
        data={"message": message},
    )


# get lndhub link for user
@debounce
async def link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # create a message tyo do this in a private chat
    if update.message.chat.type != "private":
        bot_me = await context.bot.get_me()

        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Like keeping your mnenomic seedphrase offline, "
            "it is better to request your lndhub link in a private chat with me.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Take me there", url=f"https://t.me/{bot_me.username}")]]
            ),
        )

        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_medium,
            data={"message": message},
        )
        return

    # we're in a private chat now
    user = await users.helper.get_or_create_user(update.effective_user.id, update.effective_user.username)

    # create QR code for the link
    filename = users.helper.get_qrcode_filename(user.lndhub)
    with open(filename, "rb") as file:
        await context.bot.send_photo(
            update.effective_chat.id,
            file,
            caption="Scan this QR code with an lndhub compatible wallet like BlueWallet or Zeus.",
            parse_mode="HTML",
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"<pre>{user.lndhub}</pre>",
            parse_mode="HTML",
        )


# pay a lightning invoice
@debounce
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = re.search("/refund\s+(lnbc[a-z0-9]+)\s*$", update.message.text)  # noqa: W605
    if result is None:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Unknown lightning invoice format. Should start with 'lnbc'.",
        )
        return

    # get the patment request from the regular expression
    payment_request = result.groups()[0]

    user = await users.helper.get_or_create_user(update.effective_user.id, update.effective_user.username)

    # pay the invoice
    payment_result = await config.lnbits.payInvoice(payment_request, user.adminkey)
    if payment_result["result"]:
        await context.bot.send_message(chat_id=update.effective_user.id, text="Payment succes.")
        logging.info(f"User {user.userid} paid and invoice")
    else:
        logging.warning(payment_result)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            parse_mode="HTML",
            text=payment_result["detail"],
        )


# send sats from user to user
@debounce
async def dj(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Send sats from one user to another
    """
    # verify that this is not a private chat
    # verify that the message is a reply
    if update.message.reply_to_message is None:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"The /dj command only works as a reply to another user. "
            f"If no amount is specified, the price for a track, "
            f"{await spotify.helper.get_price(update.effective_chat.id)} is sent.",
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )
        return

    # parse the amount to be paid
    amount = await spotify.helper.get_price(update.effective_chat.id)
    result = re.search("/[a-z]+(\s+([0-9]+))?\s*$", update.message.text)  # noqa: W605
    if result is not None:
        amount = result.groups()[1]
        if amount is None:
            amount = 21
        else:
            amount = int(amount)

    # get the user that is sending the sats and check his balance
    sender = await users.helper.get_or_create_user(update.effective_user.id, update.effective_user.username)
    balance = await users.helper.get_balance(sender)

    if balance < amount:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Insufficient balance, /fund your balance first to /dj another user.",
        )
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )

        # and stop here
        return

    # get the receiving user and create an invoice
    recipient = await users.helper.get_or_create_user(
        update.message.reply_to_message.from_user.id,
        update.message.reply_to_message.from_user.username,
    )
    invoice = await invoicing.helper.create_invoice(recipient, amount, f"@{sender.username} thinks you're a DJ!")
    invoice.recipient = recipient
    invoice.user = sender

    # pay the invoice
    result = await invoicing.helper.pay_invoice(sender, invoice)
    if result["result"]:
        # send message in the group chat
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"@{sender.username} sent {amount} sats to @{recipient.username}.",
        )
        # context.job_queue.run_once(delete_message, config.delete_message_timeout_medium, data={'message':message})

        # send a message in the private chat
        if not update.message.reply_to_message.from_user.is_bot:
            try:
                await context.bot.send_message(
                    chat_id=recipient.userid,
                    text=f"Received {amount} sats from @{sender.username}.",
                )
            except TelegramError:
                logging.info("Could not send message to user, probably not allowed")
        else:
            logging.info(f"@{sender.username} is sending {amount} sats to the bot")

        # send a message in the private chat
        try:
            await context.bot.send_message(
                chat_id=sender.userid,
                text=f"Sent {amount} sats to  @{recipient.username}.",
            )
        except TelegramError:
            logging.info("Could not send message to sender user, probably not allowed")

        logging.info(f"User {sender.userid} sent {amount} sats to {recipient.userid}")
    else:
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text="Payment failed. Sorry.")
        context.job_queue.run_once(
            delete_message,
            config.delete_message_timeout_short,
            data={"message": message},
        )


@debounce
async def web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    return the Web URL where tracks can be requested using a browser
    """
    if update.message.chat.type == "private":
        return

    jukebox_url = f"https://{config.domain}/jukebox/web/{update.effective_chat.id}"
    filename = os.path.join(const.QR_CODE_DIR, f"web_url_{update.effective_chat.id}.png")

    if not os.path.isfile(filename):
        img_bg = Image.open("../assets/web_jukebox_template.png")
        qr = qrcode.QRCode(box_size=7, border=0)
        qr.add_data(jukebox_url)
        qr.make()
        img_qr = qr.make_image()
        pos = (
            int((img_bg.size[0] - img_qr.size[0]) / 2),
            385 - int(img_qr.size[1] / 2),
        )
        img_bg.paste(img_qr, pos)
        img_bg.save(filename)

    with open(filename, "rb") as file:
        message = await context.bot.send_photo(
            update.effective_chat.id,
            file,
            caption=f"Access this Jukebox directly at the following URL: {jukebox_url}. "
            f"Pro tip: print out this image and scan it with your phone.",
            parse_mode="HTML",
        )

    context.job_queue.run_once(delete_message, config.delete_message_timeout_long, data={"message": message})
