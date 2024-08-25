import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


message_debounce = {}


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
