from fastapi import APIRouter

from . import jukebox, spotify

router = APIRouter()
router.include_router(spotify.router)
router.include_router(jukebox.router)
