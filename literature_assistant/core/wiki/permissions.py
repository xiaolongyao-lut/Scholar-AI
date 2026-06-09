"""Wiki page permissions and access control (G14 / Wave 13).

Permissions are stored in ``WikiPage.extra["permissions"]`` to avoid a
storage migration while the product is still local-first.  Missing permission
metadata is treated as private to the local workspace owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


DEFAULT_WIKI_OWNER = "local-user"
PERMISSIONS_KEY = "permissions"
_MAX_SHARED_USERS = 100
_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class WikiPageVisibility(str, Enum):
    """Page visibility level (G14 2026-05-26)."""

    PUBLIC = "public"
    PRIVATE = "private"
    SHARED = "shared"


@dataclass(frozen=True)
class WikiPagePermissions:
    """Page access-control metadata stored in ``WikiPage.extra``."""

    owner: str
    visibility: WikiPageVisibility
    shared_with: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage in WikiPage.extra."""
        return {
            "owner": self.owner,
            "visibility": self.visibility.value,
            "shared_with": list(self.shared_with),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        default_owner: str = DEFAULT_WIKI_OWNER,
    ) -> "WikiPagePermissions":
        """Deserialize permission metadata, failing closed on malformed fields."""
        if not isinstance(data, Mapping):
            return cls.default(default_owner)
        owner = normalize_user_id(data.get("owner"), default=default_owner)
        visibility = _coerce_visibility(data.get("visibility"))
        return cls(
            owner=owner,
            visibility=visibility,
            shared_with=normalize_shared_with(data.get("shared_with")),
        )

    @classmethod
    def default(cls, owner: str = DEFAULT_WIKI_OWNER) -> "WikiPagePermissions":
        """Create default private permissions for a local workspace page."""
        return cls(owner=normalize_user_id(owner, default=DEFAULT_WIKI_OWNER), visibility=WikiPageVisibility.PRIVATE)


def normalize_user_id(value: object | None, *, default: str | None = None) -> str:
    """Return a bounded user identifier accepted by the local ACL.

    Args:
        value: User id supplied by a trusted local caller.
        default: Optional fallback used by local-first API routes.

    Raises:
        ValueError: If the value is empty without a default or contains
            unsupported characters.
    """
    if value is None:
        if default is None:
            raise ValueError("user_id is required")
        value = default
    normalized = str(value).strip()
    if not normalized:
        if default is None:
            raise ValueError("user_id cannot be empty")
        normalized = default
    if not _USER_ID_RE.fullmatch(normalized):
        raise ValueError("user_id contains unsupported characters")
    return normalized


def normalize_shared_with(value: object | None) -> tuple[str, ...]:
    """Normalize a bounded shared-user list without accepting nested objects."""
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("shared_with must be a list of user ids")
    if len(value) > _MAX_SHARED_USERS:
        raise ValueError(f"shared_with cannot contain more than {_MAX_SHARED_USERS} users")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_user in value:
        user_id = normalize_user_id(raw_user)
        if user_id not in seen:
            normalized.append(user_id)
            seen.add(user_id)
    return tuple(normalized)


def can_read(
    page_extra: Mapping[str, Any],
    user_id: str | None,
    *,
    default_owner: str = DEFAULT_WIKI_OWNER,
) -> bool:
    """Check if user can read a wiki page.

    Args:
        page_extra: WikiPage.extra dict
        user_id: Current user ID. None is anonymous and only reads public pages.

    Returns:
        True if user has read access, False otherwise.
    """
    perms = get_permissions(page_extra, default_owner=default_owner)

    # Owner always has access
    if user_id and user_id == perms.owner:
        return True

    # Public pages: all users
    if perms.visibility == WikiPageVisibility.PUBLIC:
        return True

    # Private pages: owner only
    if perms.visibility == WikiPageVisibility.PRIVATE:
        return False

    # Shared pages: owner + shared_with list
    if perms.visibility == WikiPageVisibility.SHARED:
        return user_id is not None and user_id in perms.shared_with

    return False


def can_write(
    page_extra: Mapping[str, Any],
    user_id: str | None,
    *,
    default_owner: str = DEFAULT_WIKI_OWNER,
) -> bool:
    """Check if user can write/update a wiki page.

    Args:
        page_extra: WikiPage.extra dict
        user_id: Current user ID. None is anonymous and cannot write.

    Returns:
        True if user has write access, False otherwise.
    """
    perms = get_permissions(page_extra, default_owner=default_owner)

    # Only owner can write
    return user_id is not None and user_id == perms.owner


def set_permissions(page_extra: Mapping[str, Any], permissions: WikiPagePermissions) -> dict[str, Any]:
    """Update permissions in WikiPage.extra dict.

    Args:
        page_extra: WikiPage.extra dict (will be copied)
        permissions: New permissions to set

    Returns:
        New extra dict with updated permissions.
    """
    new_extra = dict(page_extra)
    new_extra[PERMISSIONS_KEY] = permissions.to_dict()
    return new_extra


def get_permissions(
    page_extra: Mapping[str, Any] | None,
    default_owner: str = DEFAULT_WIKI_OWNER,
) -> WikiPagePermissions:
    """Extract permissions from WikiPage.extra dict.

    Args:
        page_extra: WikiPage.extra dict
        default_owner: Default owner if no permissions set

    Returns:
        WikiPagePermissions instance.
    """
    extra = page_extra if isinstance(page_extra, Mapping) else {}
    perms_data = extra.get(PERMISSIONS_KEY)
    if perms_data is None:
        return WikiPagePermissions.default(default_owner)
    if not isinstance(perms_data, Mapping):
        return WikiPagePermissions.default(default_owner)
    return WikiPagePermissions.from_dict(perms_data, default_owner=default_owner)


def _coerce_visibility(value: object | None) -> WikiPageVisibility:
    if value is None:
        return WikiPageVisibility.PRIVATE
    try:
        return WikiPageVisibility(str(value))
    except ValueError:
        return WikiPageVisibility.PRIVATE
