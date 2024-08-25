import json
import logging
from time import time

from redis import RedisError
from spotipy import CacheHandler, SpotifyOAuth

from lightning_jukebox_bot.application import redis
from lightning_jukebox_bot.settings import config

logger = logging.getLogger(__name__)


class SpotifySettings:
    def __init__(self, tguserid):
        self.userid = tguserid
        self.userkey = f"user:{self.userid}"
        self.client_secret = None
        self.client_id = None

    def to_json(self):
        data = {
            "telegram_userid": self.userid,
            "client_secret": self.client_secret,
            "client_id": self.client_id,
        }
        return json.dumps(data)

    def from_json(self, data):
        assert data is not None
        obj = json.loads(data)
        assert obj is not None
        assert obj["telegram_userid"] == self.userid

        if "client_secret" in obj:
            self.client_secret = obj["client_secret"]

        if "client_id" in obj:
            self.client_id = obj["client_id"]


class CacheJukeboxHandler(CacheHandler):
    """
    This cache handler keeps track of spotify auth data and is stored in the redis database per group so that multiple
    authorisations can be active at the same time
    """

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.rediskey = f"spotify_token:{self.chat_id}"
        self.token = None

    def get_cached_token(self):
        logging.debug("Obtain cached token")
        token_info = None

        try:
            token_info = redis.cache.get(self.rediskey)
            if token_info:
                return json.loads(token_info)
        except RedisError as e:
            logging.warning("Error getting token from cache: " + str(e))

        return token_info

    def save_token_to_cache(self, token_info):
        logging.info("saving token to cache")
        try:
            redis.cache.set(self.rediskey, json.dumps(token_info))
        except RedisError as e:
            logging.warning("Error saving token to cache: " + str(e))


def add_to_queue(sp, spotify_uri_list):
    """
    Add a list of tracks to the queue
    """
    for uri in spotify_uri_list:
        sp.add_to_queue(uri)


# construct the track title from a Spotify track item
def get_track_title(item: dict):
    """
    Get a readable version of the track title
    """
    if item is None:
        return "No track item"
    if "artists" not in item:
        return "No artists"
    if item["artists"][0] is None:
        return "No artist"
    if item["artists"][0]["name"] is None:
        return "No name"
    if item["name"] is None:
        return "No track name"

    artist = item["artists"][0]["name"]
    track = item["name"]

    return f"{artist} - {track}"


async def get_price(chat_id):
    """
    Gets the price for tracks in this group. Defaults to the initial price of 21 sats
    """
    rediskey = f"group:{chat_id}"
    price = redis.cache.hget(rediskey, "price")
    if price is None:
        price = config.price
    return int(price)


async def set_price(chat_id, price):
    """
    Set the price in a group
    """
    rediskey = f"group:{chat_id}"
    price = redis.cache.hset(rediskey, "price", price)


async def create_auth_manager(chat_id, client_id, client_secret):
    logger.debug("create auth manager")
    cache_handler = CacheJukeboxHandler(chat_id)
    return SpotifyOAuth(
        scope="user-read-currently-playing,user-modify-playback-state,user-read-playback-state",
        client_secret=client_secret,
        client_id=client_id,
        redirect_uri=config.spotify_redirect_uri,
        show_dialog=False,
        open_browser=False,
        cache_handler=cache_handler,
    )


async def init_auth_manager(chat_id, client_id, client_secret):
    """
    Initialize a spotify auth manager for a specific group
    """
    logger.info("init auth manager")
    data = {"chat_id": chat_id, "client_id": client_id, "client_secret": client_secret}
    redis.cache.hset(f"group:{chat_id}", "authmanager", json.dumps(data))

    return await create_auth_manager(chat_id, client_id, client_secret)


async def get_auth_manager(chat_id):
    """
    Create a spotify auth manager for a specific group
    """
    logger.debug("Get Auth Manager")
    am_data = redis.cache.hget(f"group:{chat_id}", "authmanager")
    if am_data is None:
        return None

    data = json.loads(am_data)
    return await create_auth_manager(data["chat_id"], data["client_id"], data["client_secret"])


# TODO: maybe we can perform a de-authorize call at spotify instead of just removing the key
async def delete_auth_manager(chat_id):
    """
    Removes an auth manager from our local store
    """
    data = redis.cache.hget(f"group:{chat_id}", "authmanager")
    if data is None:
        return True

    # delete the spotify token as well
    redis.cache.delete(f"spotify_token:{chat_id}")

    redis.cache.hdel(f"group:{chat_id}", "authmanager")

    # delete the spotify token as well
    redis.cache.delete(f"spotify_token:{chat_id}")
    return True


async def save_spotify_settings(sps):
    """
    Store spotify settings in Redis
    """
    redis.cache.hset(sps.userkey, "spotify", sps.to_json())


async def get_spotify_settings(userid):
    """
    Get the spotify settings for this user
    """
    sps = SpotifySettings(userid)
    data = redis.cache.hget(sps.userkey, "spotify")
    if data is not None:
        sps.from_json(data)
    return sps


async def get_history(chat_id, maxlen):
    rediskey = f"history:{chat_id}"
    titles = []
    for i in range(0, min(maxlen, redis.cache.llen(rediskey))):
        titles.append(redis.cache.lindex(rediskey, i).decode("utf-8"))
    return titles


async def update_history(chat_id: int, title: str) -> None:
    rediskey = f"history:{chat_id}"
    currenttitle = redis.cache.lindex(rediskey, 0)

    if currenttitle is None:
        redis.cache.lpush(rediskey, title)
    else:
        currenttitle = currenttitle.decode("utf-8")
        if currenttitle != title:
            redis.cache.lpush(rediskey, title)

        if redis.cache.llen(rediskey) > 100:
            redis.cache.rpop(rediskey)

    # update last played entry
    redis.cache.hset(f"lastplayed:{chat_id}", title, int(time()))


async def get_donation_fee(chat_id: int) -> int:
    """
    Gets the donation fee
    """
    rediskey = f"group:{chat_id}"
    fee = redis.cache.hget(rediskey, "donation_fee")
    if fee is None:
        fee = config.donation_fee
    fee = int(fee)
    if fee < 0:
        fee = config.donation_fee
    return int(fee)


async def set_donation_fee(chat_id: int, fee: int) -> None:
    """
    Sets the donation fee
    """
    rediskey = f"group:{chat_id}"
    redis.cache.hset(rediskey, "donation_fee", fee)
