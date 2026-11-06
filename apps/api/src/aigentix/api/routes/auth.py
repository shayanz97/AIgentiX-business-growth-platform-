from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, EmailStr, StringConstraints

from aigentix.api.deps import AppSettings, DbSession
from aigentix.api.schemas import ErrorResponse, UserRead
from aigentix.core.errors import NotAuthenticated
from aigentix.core.logging import get_logger
from aigentix.platform.identity import service as identity
from aigentix.platform.identity.throttle import login_throttle

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


@router.post(
    "/login",
    response_model=UserRead,
    operation_id="login",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def login(body: LoginRequest, request: Request, response: Response, db: DbSession, settings: AppSettings) -> UserRead:
    account = identity.normalise_email(body.email)
    login_throttle.check(account)
    with login_throttle.hashing_slot():
        user = identity.authenticate(db, email=account, password=body.password)
    if user is None:
        login_throttle.record_failure(account)
        log.info("auth.login_failed")
        raise NotAuthenticated("Invalid e-mail or password")
    login_throttle.reset(account)

    # Rotate: drop any session the browser already had (prevents session fixation).
    if old := request.cookies.get(settings.session_cookie_name):
        identity.revoke_session(db, old)
    ttl = timedelta(hours=settings.session_ttl_hours)
    issued = identity.issue_session(db, user, ttl=ttl)
    db.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    log.info("auth.login_succeeded", user_id=str(user.id))
    return UserRead.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout")
def logout(request: Request, response: Response, db: DbSession, settings: AppSettings) -> None:
    if token := request.cookies.get(settings.session_cookie_name):
        identity.revoke_session(db, token)
        db.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
