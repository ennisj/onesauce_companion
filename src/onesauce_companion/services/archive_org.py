from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from internetarchive import get_session
from internetarchive.config import get_auth_config
from internetarchive.exceptions import AuthenticationError


class ArchiveOrgAuthError(RuntimeError):
    """Raised when Archive.org authentication fails."""


@dataclass(frozen=True)
class ArchiveOrgCredentials:
    email: str
    password: str


def get_authenticated_config(credentials: ArchiveOrgCredentials) -> tuple[dict[str, Any], str]:
    try:
        config = get_auth_config(credentials.email, credentials.password)
    except AuthenticationError as exc:
        raise ArchiveOrgAuthError(_auth_error_message(str(exc))) from exc

    user = str(config.get("general", {}).get("screenname") or credentials.email)
    return config, user


def create_authenticated_session(credentials: ArchiveOrgCredentials):
    config, user = get_authenticated_config(credentials)
    session = get_session(config=config)
    session.headers.update({"User-Agent": "onesauce-companion/0.1.0"})
    return session, user, config


def authenticate(credentials: ArchiveOrgCredentials) -> str:
    _, user, _ = create_authenticated_session(credentials)
    return user


def _auth_error_message(message: str) -> str:
    normalized = message.strip()
    if normalized in {"account_not_found", "Account not found, check your email and try again."}:
        return "Archive.org account not found. Check the email address and try again."
    if normalized in {"account_bad_password", "Incorrect password, try again."}:
        return "Archive.org password was rejected."
    if normalized.lower().startswith("authentication failed:"):
        return f"Archive.org {normalized[0].lower() + normalized[1:]}"
    return f"Archive.org authentication failed: {normalized}"
