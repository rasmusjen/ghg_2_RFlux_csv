"""Disturbance-window loading and lookup.

Transplanted verbatim from GHG2RFLUX.py:67-140. Windows are inclusive on both
ends, merged into non-overlapping intervals, and probed with ``bisect_right`` so
a long disturbance file costs O(log n) per data file rather than O(n).
"""

from __future__ import annotations

import os
from bisect import bisect_right
from datetime import datetime

import pandas as pd

Window = tuple[datetime, datetime]

TIMESTAMP_FORMAT = "%Y%m%d%H%M"


def load_disturbance_windows(file_path: str) -> list[Window]:
    """Read ``disturbance.txt`` (a CSV) and return validated windows."""
    if not os.path.isfile(file_path):
        return []

    try:
        disturbance_df = pd.read_csv(file_path)
    except Exception as e:  # a malformed file must not abort the run
        print(f"Unable to read disturbance file {file_path}: {e}")
        return []

    required_cols = {"date_start", "date_end"}
    if not required_cols.issubset(disturbance_df.columns):
        print(f"Disturbance file {file_path} is missing required columns: date_start,date_end")
        return []

    disturbance_df["date_start"] = pd.to_datetime(
        disturbance_df["date_start"].astype(str).str.strip(),
        format=TIMESTAMP_FORMAT,
        errors="coerce",
    )
    disturbance_df["date_end"] = pd.to_datetime(
        disturbance_df["date_end"].astype(str).str.strip(),
        format=TIMESTAMP_FORMAT,
        errors="coerce",
    )

    disturbance_df = disturbance_df.dropna(subset=["date_start", "date_end"])
    disturbance_df = disturbance_df[disturbance_df["date_end"] >= disturbance_df["date_start"]]

    windows = list(zip(disturbance_df["date_start"], disturbance_df["date_end"], strict=False))
    if windows:
        print(f"Loaded {len(windows)} disturbance window(s) from {file_path}")
    else:
        print(f"No valid disturbance windows found in {file_path}")
    return windows


def build_disturbance_index(windows: list[Window]) -> tuple[list[Window], list[datetime]]:
    """Sort and merge overlapping windows; return ``(merged, start_times)``."""
    if not windows:
        return [], []

    sorted_windows = sorted(windows, key=lambda item: item[0])
    merged_windows: list[list[datetime]] = []
    for start_dt, end_dt in sorted_windows:
        if not merged_windows:
            merged_windows.append([start_dt, end_dt])
            continue

        last_end = merged_windows[-1][1]
        if start_dt <= last_end:
            if end_dt > last_end:
                merged_windows[-1][1] = end_dt
        else:
            merged_windows.append([start_dt, end_dt])

    merged = [(start_dt, end_dt) for start_dt, end_dt in merged_windows]
    starts = [start_dt for start_dt, _ in merged]
    return merged, starts


def is_in_disturbance(
    timestamp_str: str | None,
    windows: list[Window],
    window_starts: list[datetime],
) -> bool:
    """True when ``timestamp_str`` (``YYYYMMDDHHMM``) falls inside any window."""
    if not windows:
        return False

    try:
        file_dt = datetime.strptime(str(timestamp_str), TIMESTAMP_FORMAT)
    except Exception:  # an unparseable hint simply is not excluded
        return False

    idx = bisect_right(window_starts, file_dt) - 1
    if idx < 0:
        return False

    return file_dt <= windows[idx][1]
