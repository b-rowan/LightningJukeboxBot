import json
import logging

import aiomqtt
import spotipy

from lightning_jukebox_bot.application import redis, spotify, telegram, users
from lightning_jukebox_bot.application.users.helper import User
from lightning_jukebox_bot.settings import config


class Invoice:
    def __init__(self, payment_hash, payment_request=None):
        self.payment_hash = payment_hash
        self.payment_request = payment_request
        self.rediskey = f"invoice:{self.payment_hash}"
        self.recipient = None
        self.user = None
        self.amount_to_pay = None
        self.spotify_uri_list = None
        self.title = None
        self.chat_id = None
        self.message_id = None
        self.ttl = 300

    def to_json(self):
        userdata = {
            "payment_hash": self.payment_hash,
            "payment_request": self.payment_request,
            "amount_to_pay": self.amount_to_pay,
            "recipient": {
                "userid": self.recipient.userid,
                "username": self.recipient.username,
            },
            "user": {"userid": self.user.userid, "username": self.user.username},
            "spotify_uri_list": self.spotify_uri_list,
            "title": self.title,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
        }
        return json.dumps(userdata)

    def from_json(self, data):
        assert data is not None
        data = json.loads(data)
        assert data is not None
        assert data["payment_hash"] == self.payment_hash

        if self.payment_request is not None:
            assert self.payment_request == data["payment_request"]
        else:
            self.payment_request = data["payment_request"]

        udata = data["recipient"]
        self.recipient = User(udata["userid"], udata["username"])
        udata = data["user"]
        self.user = User(udata["userid"], udata["username"])

        self.amount_to_pay = data["amount_to_pay"]
        self.spotify_uri_list = data["spotify_uri_list"]
        self.title = data["title"]
        self.chat_id = data["chat_id"]
        self.message_id = data["message_id"]


# Get/Create a QR code and store in filename
async def create_invoice(user: User, amount: int, memo: str) -> Invoice:
    lnbits_invoice = await config.lnbits.createInvoice(user.invoicekey, amount, memo, None)
    invoice = Invoice(lnbits_invoice["payment_hash"], lnbits_invoice["payment_request"])
    return invoice


async def pay_invoice(user: User, invoice: Invoice):
    assert user is not None
    assert invoice is not None
    result = await config.lnbits.payInvoice(invoice.payment_request, user.adminkey)

    if result["result"] == True:
        return {"result": True, "detail": "Payment success"}
    else:
        retval = {"result": False, "detail": result["detail"]}
        return retval


async def save_invoice(invoice: Invoice) -> None:
    redis.cache.set(invoice.rediskey, invoice.to_json())


async def delete_invoice(payment_hash: str) -> bool:
    if payment_hash is None:
        logging.error("Delete invoice called with None payment_hash")
        return False
    rediskey = f"invoice:{payment_hash}"
    if redis.cache.delete(rediskey) == 0:
        logging.info("Invoice already deleted")
        return False
    return True


async def invoice_paid(invoice: Invoice) -> bool:
    result = await config.lnbits.checkInvoice(invoice.recipient.invoicekey, invoice.payment_hash)
    if result == True:
        return True
    else:
        return False


async def get_invoice(payment_hash: str) -> Invoice:
    """
    load invoice from redis
    """
    rediskey = f"invoice:{payment_hash}"
    data = redis.cache.get(rediskey)
    if data is None:
        return None

    invoice = Invoice(payment_hash, None)
    invoice.from_json(data)
    print(invoice)
    return invoice


async def callback_paid_invoice(invoice: Invoice):
    if invoice is None:
        logging.error("Invoice is None")
        return
    logging.info("callback_paid_invoice")
    logging.info(invoice.to_json())

    if invoice.chat_id is None:
        logging.error("Invoice chat_id is None")
        return

    if await delete_invoice(invoice.payment_hash) == False:
        logging.info("invoicehelper.delete_invoice returned False")
        return

    auth_manager = await spotify.helper.get_auth_manager(invoice.chat_id)
    if auth_manager is None:
        logging.error("No auth manager after succesfull payment")
        return

    try:
        logging.info(f"Trying to delete chat_id {invoice.chat_id}, messageid {invoice.message_id}")
        await telegram.app.bot.delete_message(invoice.chat_id, invoice.message_id)
    except:
        pass

    # add to the queue and inform others
    sp = spotipy.Spotify(auth_manager=auth_manager)

    spotify.helper.add_to_queue(sp, invoice.spotify_uri_list)
    try:
        await telegram.app.bot.send_message(
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

    # make donation to the bot
    jukeboxbot = await users.helper.get_or_create_user(config.bot_id)
    donator = await users.helper.get_or_create_user(invoice.recipient.userid)
    donation_amount: int = await spotify.helper.get_donation_fee(invoice.chat_id)
    donation_amount = min(donation_amount, invoice.amount_to_pay)
    donation_invoice = await create_invoice(jukeboxbot, donation_amount, "donation to the bot")
    result = await pay_invoice(donator, donation_invoice)

    return result
