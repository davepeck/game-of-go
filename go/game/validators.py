"""
Input validation helpers.

Ported from the ad-hoc ``is_valid_*`` methods on ``GoHandler`` in _old/go.py.
These are intentionally permissive (matching the original behavior) — the
point is to reject obvious junk and let the rest through. User-facing errors
are returned via the JSON ``flash`` field.
"""

from . import game_logic as gl


def is_valid_name(name: str | None) -> bool:
    """Return ``True`` if ``name`` is non-empty and under 200 characters."""
    return name is not None and 0 < len(name) < 200


def is_valid_email(email: str | None) -> bool:
    """Return ``True`` if ``email`` looks minimally email-shaped."""
    if email is None:
        return False
    if len(email) <= 4 or len(email) > 200:
        return False
    i_at = email.find("@")
    i_p = email.find(".")
    i_right_p = email.rfind(".")
    if i_at == -1 or i_p == -1:
        return False
    if i_at == 0:
        return False
    if i_at >= (i_right_p - 1):
        return False
    return i_right_p < len(email) - 1


def is_valid_contact_type(contact_type: str | None) -> bool:
    """Return ``True`` for ``'email'`` (the only live contact type now)."""
    return contact_type == gl.CONST.Email_Contact


def is_valid_active_contact_type(contact_type: str | None) -> bool:
    """Return ``True`` for ``'email'`` or ``'none'``."""
    return contact_type in (gl.CONST.Email_Contact, gl.CONST.No_Contact)


def is_valid_contact(contact: str | None, contact_type: str | None) -> bool:
    """Return ``True`` if ``contact`` is valid for the given ``contact_type``."""
    if contact_type == gl.CONST.Email_Contact:
        return is_valid_email(contact)
    return False
