"""Timestamp extraction and averaging-boundary rounding.

Transplanted from GHG2RFLUX.py:143-168. ``ceil_timestamp_to_boundary`` generalises
the original ``ceil_timestamp_to_half_hour``; at the default 30 minutes it is the
same function, which is what keeps output filenames byte-identical.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

TIMESTAMP_FORMAT = "%Y%m%d%H%M"

#: 12-digit YYYYMMDDHHMM first, then 14-digit YYYYMMDDHHMMSS truncated to 12.
#: The negative lookarounds stop a 14-digit run from matching the 12-digit form.
_PATTERNS = (r"(?<!\d)(\d{12})(?!\d)", r"(?<!\d)(\d{14})(?!\d)")


def extract_timestamp_from_file_path(file_path: str) -> str | None:
    """Best-effort ``YYYYMMDDHHMM`` hint from a filename, else the full path.

    This is only a hint used for the pre-parse disturbance filter and the daily
    coverage counts; the authoritative timestamp always comes from inside the
    archive.
    """
    file_name = os.path.basename(file_path)

    for pattern in _PATTERNS:
        candidates = re.findall(pattern, file_name)
        if not candidates:
            candidates = re.findall(pattern, file_path)

        for candidate in candidates:
            timestamp_text = candidate[:12]
            try:
                datetime.strptime(timestamp_text, TIMESTAMP_FORMAT)
                return str(timestamp_text)
            except Exception:  # try the next candidate
                continue

    return None


def ceil_timestamp_to_boundary(timestamp_str: str, averaging_minutes: int = 30) -> str:
    """Round ``YYYYMMDDHHMM`` up to the next averaging-period boundary.

    At ``averaging_minutes=30`` this is the original half-hour ceiling: a
    timestamp already on a boundary is left alone, anything else moves forward.
    """
    if averaging_minutes <= 0:
        raise ValueError(f"averaging_minutes must be positive, got {averaging_minutes}")

    dt_value = datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)
    minutes_since_midnight = dt_value.hour * 60 + dt_value.minute
    remainder = minutes_since_midnight % averaging_minutes
    if remainder != 0:
        dt_value = dt_value + timedelta(minutes=(averaging_minutes - remainder))
    return dt_value.strftime(TIMESTAMP_FORMAT)


def ceil_timestamp_to_half_hour(timestamp_str: str) -> str:
    """Backwards-compatible alias for the original half-hour rounding."""
    return ceil_timestamp_to_boundary(timestamp_str, 30)
