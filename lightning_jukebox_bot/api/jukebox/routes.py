import re

import spotipy
from fastapi import APIRouter
from fastapi.requests import Request
from telegram import Update

from lightning_jukebox_bot.application import invoicing, spotify, telegram, users
from lightning_jukebox_bot.ui.templates import templates
from . import web

router = APIRouter(prefix="/jukebox")
router.include_router(web.router)


@router.post("/telegram")
async def telegram_callback(request: Request):
    """Handle incoming Telegram updates by putting them into the `update_queue`"""
    await telegram.app.update_queue.put(Update.de_json(data=await request.json(), bot=telegram.app.bot))
    return {"success": True}


@router.post("/lnbitscallback")
async def lnbits_lnurlp_callback(request: Request):
    """
    Callback from LNbits when a wallet is funded. Send a message to the telegram user

    The callback is a POST request with a userid parameter in the URL
    """
    tg_userid = request.query_params["userid"]
    if re.search("^[0-9]+$", tg_userid):
        obj = await request.json()
        amount = int(obj["amount"] / 1000)
        await telegram.app.bot.send_message(
            chat_id=int(tg_userid),
            text=f"Received {amount} sats. Type /stack to view your sats stack.",
        )
    return {"success": True}


@router.get("/payinvoice")
async def payinvoice_callback(request: Request):
    if "payment_hash" not in request.query_params:
        return {"success": False, "message": "Invoice not found"}

    payment_hash = request.query_params["payment_hash"]

    invoice = await invoicing.helper.get_invoice(payment_hash)
    if invoice is None:
        return {"success": False, "message": "Invoice not found"}

    return templates.TemplateResponse(
        request, "payinvoice.html.jinja", context={"title": invoice.title, "invoice": invoice}
    )


@router.post("/invoicecallback")
async def invoicepaid_callback(request: Request):
    data = await request.json()
    payment_hash = data["payment_hash"]

    invoice = await invoicing.helper.get_invoice(payment_hash)
    if invoice is None:
        return {"success": False, "message": "No valid invoice found."}

    # process in the bot
    await invoicing.helper.callback_paid_invoice(invoice)

    return {"success": True}


@router.get("/status")
async def jukebox_status(request: Request):
    if "chat_id" not in request.query_params:
        return {}

    chat_id = request.query_params["chat_id"]

    auth_manager = await spotify.helper.get_auth_manager(chat_id)
    if auth_manager is None:
        return {"title": "Nothing is playing at the moment."}

    # create spotify instance
    sp = spotipy.Spotify(auth_manager=auth_manager)

    # get the current track
    track = sp.current_user_playing_track()
    title = "Nothing is playing at the moment"
    if track:
        title = spotify.helper.get_track_title(track["item"])
    return {"title": title}


@router.get("/fund")
async def jukebox_fund(request: Request):
    if "command" not in request.query_params:
        return {"success": False}

    key = request.query_params["command"]
    if key is None:
        return {"success": False}

    command = telegram.helper.get_command(key)
    if command is None:
        return {"success": False}

    if command.command != "FUND":
        return {"success": False}

    user = await users.helper.get_or_create_user(command.userid)
    if user is None:
        return

    lnurl = await users.helper.get_funding_lnurl(user)

    return templates.TemplateResponse(
        request, "jukebox/fund.html.jinja", context={"title": f"Fund {user.username}", "lnurl": lnurl}
    )
