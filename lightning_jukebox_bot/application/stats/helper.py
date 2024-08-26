import logging

from lightning_jukebox_bot.application import redis, users
from lightning_jukebox_bot.settings import config


async def get_bot_stack() -> int:
    """
    Returns the amount of sats of the Jukebox Bot itself.
    """
    jukeboxbot: users.helper.User = await users.helper.get_or_create_user(config.bot_id)
    balance: int = await users.helper.get_balance(jukeboxbot)
    return balance


async def get_jukebox_groups() -> dict:
    """
    Returns a list of Jukebox groups and some stats about them
    """
    result = {"numgroups": 0, "group": []}
    for key in redis.cache.scan_iter("group:*"):
        chatid: int = int(key.decode("utf-8").split(":")[1])

        result["numgroups"] += 1

        owner = None
        try:
            owner = await users.helper.get_group_owner(chatid)
        # TODO: replace bare except
        except:  # noqa: E722
            logging.error("problem getting group stats")

        result["group"].append({"groupid": chatid, "owner": owner})

    return result
