from fastapi import APIRouter

from guestbook.api.admin import router as admin_router
from guestbook.api.auth import router as auth_router
from guestbook.api.events import router as events_router
from guestbook.api.guests import router as guests_router
from guestbook.api.households import router as households_router
from guestbook.api.orgs import router as orgs_router
from guestbook.api.qr import router as qr_router
from guestbook.api.rsvps import router as rsvps_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(orgs_router)
api_router.include_router(events_router)
api_router.include_router(rsvps_router)
api_router.include_router(admin_router)
api_router.include_router(guests_router)
api_router.include_router(qr_router)
api_router.include_router(households_router)
