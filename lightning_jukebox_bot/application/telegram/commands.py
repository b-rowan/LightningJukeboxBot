import spotipy
from telegram import Update
from telegram.ext import ContextTypes

from .util import debounce
from .. import spotify


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
            text=f"Execute the /add command in the group instead of the private chat.",
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
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text=jukeboxtexts.add_command_help)
        context.job_queue.run_once(
            delete_message,
            settings.delete_message_timeout_medium,
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
                            f"Pay {await spotifyhelper.get_price(update.effective_chat.id)} sats for a random track",
                            callback_data=telegramhelper.add_command(
                                TelegramCommand(0, telegramhelper.playrandom, playlistid)
                            ),
                        )
                    ]
                ]
            ),
        )

        # start a job to kill the message  after 30 seconds if not used
        context.job_queue.run_once(
            delete_message,
            settings.delete_message_timeout_long,
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
            logging.info("Spotify Oauth error")
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Music player not available, search aborted.",
            )
            return

        except spotipy.exceptions.SpotifyException:
            numtries -= 1
            if numtries == 0:
                # spotify still triggers an exception
                logging.error("Spotify returned and exception, not returning search result")
                message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Music player unavailable, search aborted.",
                )
                return
            logging.warning("Spotify returned and exception, retrying")
            continue

        break

    # create a list of max five buttons, each with a unique song title
    if len(result["tracks"]["items"]) > 0:
        tracktitles = {}
        button_list = []
        for item in result["tracks"]["items"]:
            title = spotifyhelper.get_track_title(item)
            if title not in tracktitles:
                tracktitles[title] = 1
                button_list.append(
                    [
                        InlineKeyboardButton(
                            title,
                            callback_data=telegramhelper.add_command(
                                TelegramCommand(
                                    update.effective_user.id,
                                    telegramhelper.add,
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
                    callback_data=telegramhelper.add_command(
                        TelegramCommand(update.effective_user.id, telegramhelper.cancel, None)
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
            settings.delete_message_timeout_medium,
            data={"message": message},
        )
    else:
        message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"No results for '{searchstr}'")
        context.job_queue.run_once(
            delete_message,
            settings.delete_message_timeout_short,
            data={"message": message},
        )
