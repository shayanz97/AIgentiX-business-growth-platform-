"""Authentication and session management. Framework-independent (no FastAPI imports)."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import Conflict, InvalidInput
from aigentix.platform.identity.models import User, UserSession
from aigentix.platform.identity.passwords import hash_password, verify_password

MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class IssuedSession:
    token: str  # raw token: returned to the client once, never stored
    session: UserSession


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, *, email: str, password: str, full_name: str = "") -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidInput(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    user = User(email=normalise_email(email), full_name=full_name.strip(), password_hash=hash_password(password))
    try:
        with db.begin_nested():  # savepoint: a duplicate must not roll back the caller's transaction
            db.add(user)
    except IntegrityError as exc:
        raise Conflict("A user with this e-mail already exists") from exc
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalise_email(email)))


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    """Return the user for valid credentials, otherwise None. Constant-ish time for unknown users."""
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, None)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def issue_session(db: Session, user: User, *, ttl: timedelta) -> IssuedSession:
    token = secrets.token_urlsafe(32)
    session = UserSession(user_id=user.id, token_hash=_hash_token(token), expires_at=utcnow() + ttl)
    db.add(session)
    db.flush()
    return IssuedSession(token=token, session=session)


def resolve_session(db: Session, token: str) -> User | None:
    """Return the active user owning a valid, unexpired session token."""
    if not token:
        return None
    return db.scalar(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == _hash_token(token),
            UserSession.expires_at > utcnow(),
            User.is_active.is_(True),
        )
    )


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))


def purge_expired_sessions(db: Session) -> int:
    result = db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    return int(result.rowcount)  # type: ignore[attr-defined]
