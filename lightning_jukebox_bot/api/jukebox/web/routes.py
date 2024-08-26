import logging
import re

import spotipy
from fastapi import APIRouter
from fastapi.requests import Request

from lightning_jukebox_bot.application import invoicing, spotify, users
from lightning_jukebox_bot.application.telegram import app
from lightning_jukebox_bot.application.telegram.util import check_invoice_callback
from lightning_jukebox_bot.application.users.helper import User
from lightning_jukebox_bot.settings import config
from lightning_jukebox_bot.ui.templates import templates

router = APIRouter(prefix="/web/{chat_id}")

logger = logging.getLogger(__name__)


@router.get("")
async def web_home(request: Request, chat_id: int):
    if chat_id is None:
        return {"success": False, "message": "Incomplete request."}

    # get spotify auth manager
    auth_manager = await spotify.helper.get_auth_manager(chat_id)
    if auth_manager is None:
        return {"success": False, "message": "Incomplete request."}

    return templates.TemplateResponse(request, "jukebox/web/index.html.jinja", context={"title": "Add Music"})


@router.post("/search")
async def web_search(request: Request):
    chat_id = request.path_params["chat_id"]
    print("Web search")

    # validate that chat_id is present
    if chat_id is None:
        return {"status": 400, "message": "Incomplete request. Chat ID is None"}

    # validate that chat_id is a digit
    try:
        chat_id = int(chat_id)
    except:
        return {"status": 400, "message": "Incomplete request. Failed to cast chat_id"}

    # get form
    form = await request.json()

    print("Web search for ", form)
    # validate that form is present
    if form is None:
        return {"status": 400, "message": "Incomplete request form is None"}

    # get query
    query = form["query"]

    # validate that query is present
    if query is None:
        return {"status": 400, "message": "Incomplete request query is None"}

    # validate allow characters in query
    if not re.search("^[A-Za-z0-9 ]+$", query):
        return {"status": 400, "message": "Incomplete request query is invalid"}

    # get spotify auth manager
    auth_manager = await spotify.helper.get_auth_manager(chat_id)
    if auth_manager is None:
        return {"status": 400, "message": "Incomplete request auth manager is None"}

    # create spotify instance
    sp = spotipy.Spotify(auth_manager=auth_manager)
    if sp is None:
        return {"status": 400, "message": "Incomplete response sp is none"}

    # search for tracks
    numtries: int = 3
    while numtries > 0:
        try:
            result = sp.search(query)
        except spotipy.exceptions.SpotifyException:
            numtries -= 1
            if numtries == 0:
                logger.error("Spotify returned and exception, not returning search result")
                return {"status": 400, "message": "Search currently unavailable"}
            logger.warning("Spotify returned and exception, retrying")
            continue
        break

    # create a list of max five items
    if len(result["tracks"]["items"]) == 0:
        return {"status": 200, "results": []}

    tracktitles = {}
    results = []

    for item in result["tracks"]["items"]:
        title = spotify.helper.get_track_title(item)
        track_id = item["uri"]
        result = re.search("^spotify:track:([A-Z0-9a-z]+)$", track_id)
        if not result:
            continue

        # strip spotify from the track id
        track_id = result.groups()[0]

        if title not in tracktitles:
            tracktitles[title] = 1
            results.append({"title": title, "track_id": track_id})

            # max five suggestions
            if len(results) == 5:
                break

    return {"status": 200, "results": results}


@router.get("/add")
async def web_add(request: Request):
    chat_id = request.path_params["chat_id"]
    track_id = request.query_params["track_id"]

    # validate that chat_id is present
    if chat_id is None:
        logger.info("chat_id is NULL")
        return {"status": 400, "message": "Incomplete request"}

    # validate that chat_id is a digit
    try:
        chat_id = int(chat_id)
    except:
        logger.warning("chat_id is not an integer")
        return {"status": 400, "message": "Incomplete request"}

    # validate track_id is not None
    if track_id is None:
        logger.info("track_id is None")
        return {"status": 400, "message": "Incomplete request"}

    # vaidate track id is spotify track
    # spotify:track:1532ejaMFnQPcHD9BAeqwr
    if not re.search("^[A-Za-z0-9]+$", track_id):
        logger.warning("track_id does not match regular expression")
        return {"status": 400, "message": "Incomplete request"}

    # add spotify prefix to the track_id
    track_id = f"spotify:track:{track_id}"

    # get spotify auth manager
    auth_manager = await spotify.helper.get_auth_manager(chat_id)
    if auth_manager is None:
        logger.warning("Auth_manager is NULL")
        return {"status": 400, "message": "Incomplete request"}

    # create spotify instance
    sp = spotipy.Spotify(auth_manager=auth_manager)

    if sp is None:
        logger.warning("sp is None")
        return {"status": 400, "message": "Incomplete request"}

    track = sp.track(track_id)
    track_len = track["duration_ms"] / 1000

    amount_to_pay = int(await spotify.helper.get_price(chat_id))
    if track_len > 600:
        amount_to_pay = 10 * amount_to_pay
    #        if ( track_len > 1800 ):
    #            amount_to_pay = 10 * amount_
    #        elif ( track_len > 600 ):
    #            amount_to_pay = amount_to_pay * 1.0166428 ** (track_len - 300)
    recipient = await users.helper.get_group_owner(chat_id)
    invoice_title = f"'{spotify.helper.get_track_title(track)}'"
    invoice = await invoicing.helper.create_invoice(recipient, amount_to_pay, invoice_title)
    if invoice is None:
        return {"status": 400, "message": "Payments not available"}

    invoice.user = User(80, "Web user")
    invoice.title = invoice_title
    invoice.recipient = recipient
    logger.info("recipient when creating invoice: " + recipient.to_json())
    invoice.spotify_uri_list = [track_id]
    invoice.title = invoice_title
    invoice.chat_id = chat_id
    invoice.amount_to_pay = amount_to_pay

    # save the invoice
    await invoicing.helper.save_invoice(invoice)

    app.job_queue.run_once(check_invoice_callback, 15, data=invoice)

    return {
        "status": 200,
        "payment_url": f"https://{config.domain}/jukebox/payinvoice?payment_hash={invoice.payment_hash}",
    }
