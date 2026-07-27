"""Scholar AI product version policy."""

from __future__ import annotations

from typing import Literal


__version__ = "0.1.9.3"
SCHOLAR_AI_USER_AGENT = f"ScholarAI/{__version__} compliant-open-access-client"
VersionChange = Literal["bugfix", "feature", "major"]


def parse_version(version: str) -> tuple[int, int, int, int]:
    """Parse an exact four-field Scholar AI product version.

    Args:
        version: Version text in ``major.track.feature.fix`` order.

    Returns:
        The four numeric fields in policy order.

    Raises:
        TypeError: If ``version`` is not text.
        ValueError: If the value is not four dot-separated ASCII integers.
    """

    if not isinstance(version, str):
        raise TypeError("version must be a string")
    fields = version.split(".")
    if len(fields) != 4 or any(
        not field.isascii()
        or not field.isdecimal()
        or (len(field) > 1 and field.startswith("0"))
        for field in fields
    ):
        raise ValueError("version must contain exactly four numeric fields")
    major, track, feature, fix = (int(field) for field in fields)
    return major, track, feature, fix


def bump_version(version: str, change: VersionChange) -> str:
    """Return the next product version for an authorized change kind.

    Args:
        version: Current canonical ``major.track.feature.fix`` version.
        change: One of ``bugfix``, ``feature``, or ``major``.

    Returns:
        A canonical four-part version with less-significant fields reset by
        feature and major changes.

    Raises:
        TypeError: If ``change`` is not text.
        ValueError: If ``version`` or ``change`` violates the version policy.
    """

    major, track, feature, fix = parse_version(version)
    if not isinstance(change, str):
        raise TypeError("change must be a string")
    if change == "bugfix":
        fix += 1
    elif change == "feature":
        feature += 1
        fix = 0
    elif change == "major":
        major += 1
        track = 0
        feature = 0
        fix = 0
    else:
        raise ValueError("change must be one of: bugfix, feature, major")
    return f"{major}.{track}.{feature}.{fix}"


__all__ = [
    "SCHOLAR_AI_USER_AGENT",
    "VersionChange",
    "__version__",
    "bump_version",
    "parse_version",
]
