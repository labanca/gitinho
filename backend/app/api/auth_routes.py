"""Authentication routes: GitHub OAuth login/callback/logout/me."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth.allowlist import is_member_of_org
from app.auth.oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    record_audit,
    upsert_user,
    verify_state,
)
from app.auth.session import (
    create_session,
    resolve_session,
    revoke_session,
)
from app.deps import DbDep, SettingsDep, UserDep
from app.logging_setup import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.get("/github/login")
async def github_login(settings: SettingsDep) -> RedirectResponse:
    url, _state = build_authorize_url(settings)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    settings: SettingsDep,
    db: DbDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error or not code or not state or not verify_state(settings, state):
        await record_audit(db, "login.invalid_callback", {"error": error})
        return RedirectResponse("/?error=oauth", status_code=303)

    token = await exchange_code_for_token(settings, code)
    if not token:
        await record_audit(db, "login.token_exchange_failed")
        return RedirectResponse("/?error=oauth", status_code=303)

    profile = await fetch_github_user(token)
    if not profile:
        await record_audit(db, "login.profile_failed")
        return RedirectResponse("/?error=oauth", status_code=303)

    if not await is_member_of_org(token, settings.ALLOWED_ORG):
        await record_audit(
            db,
            "login.denied",
            {"login": profile.get("login"), "org": settings.ALLOWED_ORG},
        )
        return RedirectResponse(
            f"/?error=forbidden&org={settings.ALLOWED_ORG}", status_code=303
        )

    user = await upsert_user(db, profile)
    response = RedirectResponse("/", status_code=303)
    await create_session(
        db,
        user=user,
        request=request,
        response=response,
        is_secure=(settings.APP_ENV == "production"),
    )
    await record_audit(db, "login.ok", {"login": user.github_login})
    log.info("login.ok", login=user.github_login)
    return response


@router.post("/logout")
async def logout(request: Request, db: DbDep) -> JSONResponse:
    response = JSONResponse({"ok": True})
    await revoke_session(db, request, response)
    return response


@router.get("/me")
async def me(request: Request, db: DbDep) -> JSONResponse:
    user = await resolve_session(request, db)
    if user is None:
        return JSONResponse({"authenticated": False}, status_code=401)
    return JSONResponse(
        {
            "authenticated": True,
            "user": {
                "id": str(user.id),
                "login": user.github_login,
                "avatar_url": user.avatar_url,
            },
        }
    )
