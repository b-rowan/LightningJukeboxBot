import base64
import logging
import re

from fastapi import APIRouter
from fastapi.requests import Request

from lightning_jukebox_bot.application import spotify, telegram, users
from lightning_jukebox_bot.ui.templates import templates

router = APIRouter(prefix="/spotify")
logger = logging.getLogger(__name__)


@router.get("")
async def spotify_callback(request: Request):
    """
    This function handles the callback from spotify when authorizing request to an account
    """

    logger.info("Got callback from spotify")

    if "code" not in request.query_params:
        logger.error("no code in response from spotify")
        # callback without code
        return {"success": False}

    code = request.query_params["code"]
    if not re.search("^[A-Za-z0-9\-\_]+$", code):
        logger.warning("authorisation code does not match regex")
        return {"success": False}

    state = request.query_params["state"]
    if not re.search("^[0-9A-Za-z\-]+", state):
        logger.warning("state parameter does not match regex")
        return {"success": False}

    try:
        state = base64.b64decode(state.encode("ascii")).decode("ascii")
        [chatid, userid] = state.split(":")
        chatid = int(chatid)
        userid = int(userid)
    except ValueError:
        logger.error("Failure during state query parameter parsing")
        return {"success": False}

    logger.info(f"Spotify callback for {chatid} {userid} with code {code}")

    try:
        auth_manager = await spotify.helper.get_auth_manager(chatid)
        if auth_manager is not None:
            auth_manager.get_access_token(code)
            await users.helper.set_group_owner(chatid, userid)
            await telegram.app.bot.send_message(
                chat_id=userid,
                text="Spotify connected to the chat. All revenues of requested tracks are coming your way. "
                "Execute the /decouple command in the group to remove the authorisation.",
            )
    except Exception as e:
        logger.error(e)
        logger.error("Failure during auth_manager instantiation")
        return {"success": False}

    return templates.TemplateResponse(request, name="spotify/success.html.jinja", context={"title": "Auth Success"})
