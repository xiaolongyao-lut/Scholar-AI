"""Wiki page permissions and access control (G14 / Wave 13).

Implements simple ACL for wiki pages:
- owner: user who created the page
- visibility: public (all), private (owner only), shared (explicit list)
- shared_with: list of user IDs with read access

Permissions stored in WikiPage.extra["permissions"] to avoid schema migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class WikiPageVisibility(str, Enum):
    """Page visibility level (G14 2026-05-26)."""
    PUBLIC = "public"      # All users can read
    PRIVATE = "private"    # Only owner can read/write
    SHARED = "shared"      # Owner + shared_with list can read


@dataclass(frozen=True)
class WikiPagePermissions:
    """Page access control metadata (G14 2026-05-26).

    Stored in WikiPage.extra["permissions"] as dict.
    """
    owner: str                          # User ID who created the page
    visibility: WikiPageVisibility
    shared_with: tuple[str, ...] = ()   # User IDs with read access (when visibility=shared)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage in WikiPage.extra."""
        return {
            "owner": self.owner,
            "visibility": self.visibility.value,
            "shared_with": list(self.shared_with),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WikiPagePermissions":
        """Deserialize from WikiPage.extra["permissions"]."""
        return cls(
            owner=str(data.get("owner", "")),
            visibility=WikiPageVisibility(data.get("visibility", "public")),
            shared_with=tuple(str(u) for u in data.get("shared_with", [])),
        )

    @classmethod
    def default(cls, owner: str) -> "WikiPagePermissions":
        """Create default permissions (public, owner only)."""
        return cls(owner=owner, visibility=WikiPageVisibility.PUBLIC)


def can_read(page_extra: dict[str, Any], user_id: str | None) -> bool:
    """Check if user can read a wiki page.

    Args:
        page_extra: WikiPage.extra dict
        user_id: Current user ID (None = anonymous)

    Returns:
        True if user has read access, False otherwise.
    """
    perms_data = page_extra.get("permissions")
    if perms_data is None:
        # No permissions set = public (backward compat)
        return True

    perms = WikiPagePermissions.from_dict(perms_data)

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


def can_write(page_extra: dict[str, Any], user_id: str | None) -> bool:
    """Check if user can write/update a wiki page.

    Args:
        page_extra: WikiPage.extra dict
        user_id: Current user ID (None = anonymous)

    Returns:
        True if user has write access, False otherwise.
    """
    perms_data = page_extra.get("permissions")
    if perms_data is None:
        # No permissions set = owner-only write (backward compat)
        return True  # Assume all existing pages are writable for now

    perms = WikiPagePermissions.from_dict(perms_data)

    # Only owner can write
    return user_id is not None and user_id == perms.owner


def set_permissions(page_extra: dict[str, Any], permissions: WikiPagePermissions) -> dict[str, Any]:
    """Update permissions in WikiPage.extra dict.

    Args:
        page_extra: WikiPage.extra dict (will be copied)
        permissions: New permissions to set

    Returns:
        New extra dict with updated permissions.
    """
    new_extra = dict(page_extra)
    new_extra["permissions"] = permissions.to_dict()
    return new_extra


def get_permissions(page_extra: dict[str, Any], default_owner: str = "system") -> WikiPagePermissions:
    """Extract permissions from WikiPage.extra dict.

    Args:
        page_extra: WikiPage.extra dict
        default_owner: Default owner if no permissions set

    Returns:
        WikiPagePermissions instance.
    """
    perms_data = page_extra.get("permissions")
    if perms_data is None:
        return WikiPagePermissions.default(default_owner)
    return WikiPagePermissions.from_dict(perms_data)
