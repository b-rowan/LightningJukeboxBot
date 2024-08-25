from fastapi import APIRouter
from fastapi.requests import Request

from lightning_jukebox_bot.application import spotify
from lightning_jukebox_bot.ui.templates import templates

router = APIRouter(prefix="/web/{chat_id}")


@router.get("")
async def web_home(request: Request, chat_id: int):
    if chat_id is None:
        return {"success": False, "message": "Incomplete request."}

    # get spotify auth manager
    auth_manager = await spotify.helper.get_auth_manager(chat_id)
    if auth_manager is None:
        return {"success": False, "message": "Incomplete request."}

    return templates.TemplateResponse(request, "jukebox/web/index.html.jinja", context={"title": "Add Music"})
