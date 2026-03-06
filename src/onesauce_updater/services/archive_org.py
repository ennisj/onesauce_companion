from __future__ import annotations

from dataclasses import dataclass

from requests import Session
from requests.cookies import create_cookie


LOGIN_URL = "https://archive.org/services/xauthn/"


class ArchiveOrgAuthError(RuntimeError):
    """Raised when Archive.org authentication fails."""


@dataclass(frozen=True)
class ArchiveOrgCredentials:
    email: str
    password: str


def authenticate(session: Session, credentials: ArchiveOrgCredentials) -> str:
    response = session.post(
        LOGIN_URL,
        params={"op": "login"},
        data={"email": credentials.email, "password": credentials.password},
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    if not payload.get("success"):
        raise ArchiveOrgAuthError(_auth_error_message(payload))

    cookies = payload["values"]["cookies"]
    for cookie_name in ("logged-in-user", "logged-in-sig"):
        for name, value in _parse_cookie_string(f"{cookie_name}={cookies[cookie_name]}").items():
            if name != cookie_name:
                continue
            session.cookies.set_cookie(
                create_cookie(
                    cookie_name,
                    value,
                    domain=".archive.org",
                    path="/",
                )
            )

    return payload["values"].get("screenname") or credentials.email


def _auth_error_message(payload: dict) -> str:
    values = payload.get("values", {})
    reason = values.get("reason") or payload.get("error") or "unknown_error"
    if reason == "account_not_found":
        return "Archive.org account not found. Check the email address and try again."
    if reason == "account_bad_password":
        return "Archive.org password was rejected."
    return f"Archive.org authentication failed: {reason}"


def _parse_cookie_string(raw_cookie: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in raw_cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        parsed[name] = value
    return parsed
