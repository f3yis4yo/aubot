"""Staff authentication and the owner's business / Buddy settings."""
from django.contrib.auth import aauthenticate, alogin, alogout
from django.middleware.csrf import get_token
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import EmailStr, Field

from core.security import check_csrf, client_ip, current_staff, rate_limit

from .models import BusinessProfile

auth_router = Router(tags=["auth"])
settings_router = Router(tags=["staff"])


class LoginIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=256)


@auth_router.get("/csrf")
async def csrf(request):
    """Sets the csrftoken cookie the SPA echoes back in X-CSRFToken."""
    return {"csrf_token": get_token(request)}


@auth_router.post("/login")
async def login(request, payload: LoginIn):
    check_csrf(request)
    await rate_limit(f"login:{client_ip(request)}", limit=10)  # slows password guessing
    user = await aauthenticate(request, username=payload.username, password=payload.password)
    if user is None:
        raise HttpError(401, "Incorrect username or password.")
    await alogin(request, user)
    staff = await current_staff(request)
    return {"username": staff.username, "name": staff.get_full_name() or staff.username, "is_owner": staff.aubot_is_owner}


@auth_router.post("/logout")
async def logout(request):
    check_csrf(request)
    await alogout(request)
    return {"ok": True}


class ProfileIn(Schema):
    business_name: str = Field(min_length=1, max_length=120)
    tagline: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    email: EmailStr
    address: str = Field(default="", max_length=200)
    opening_hours: str = Field(default="", max_length=200)
    buddy_name: str = Field(min_length=1, max_length=40)
    buddy_greeting: str = Field(min_length=1, max_length=300)
    buddy_tone: str
    buddy_voice: str


FIELDS = list(ProfileIn.model_fields)


def _profile_dict(p: BusinessProfile) -> dict:
    return {
        **{f: getattr(p, f) for f in FIELDS},
        "tone_choices": [{"value": v, "label": l} for v, l in BusinessProfile.TONES],
        "voice_choices": [{"value": v, "label": l} for v, l in BusinessProfile.VOICES],
        "updated_at": p.updated_at.isoformat(),
    }


@settings_router.get("/settings")
async def get_settings(request):
    await current_staff(request)
    return _profile_dict(await BusinessProfile.aget_solo())


@settings_router.put("/settings")
async def update_settings(request, payload: ProfileIn):
    """Owner sets Buddy's name, greeting, tone and voice without retraining (Assessment 1)."""
    await current_staff(request, owner=True)
    if payload.buddy_tone not in dict(BusinessProfile.TONES):
        raise HttpError(400, "Unknown tone.")
    if payload.buddy_voice not in dict(BusinessProfile.VOICES):
        raise HttpError(400, "Unknown voice.")
    profile = await BusinessProfile.aget_solo()
    for field in FIELDS:
        setattr(profile, field, getattr(payload, field))
    await profile.asave()
    return _profile_dict(profile)
