"""Recursive ``.ghg`` discovery with per-directory settings resolution.

``os.walk`` is top-down, so a single pass resolves every directory's settings by
merging its own marker over its parent's -- no pre-scan needed. This keeps the
original depth-agnostic discovery (GHG2RFLUX.py:616-620), which is what lets the
same code handle month folders, flat years, and two-deep nesting alike.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .settings import MARKER_NAME, FolderSettings, read_marker

_LAYER_MARKER = "marker"


@dataclass(frozen=True)
class DiscoveredFile:
    path: str
    settings: FolderSettings


@dataclass(frozen=True)
class ExcludedFolder:
    path: str
    note: str
    marker_path: str


def discover(root: str, base: FolderSettings) -> tuple[list[DiscoveredFile], list[ExcludedFolder]]:
    """Walk ``root`` returning ``.ghg`` files with their resolved settings.

    Directories carrying ``exclude = true`` are pruned in place, so an excluded
    subtree costs nothing and is reported rather than silently skipped.
    """
    files: list[DiscoveredFile] = []
    excluded: list[ExcludedFolder] = []
    resolved: dict[str, FolderSettings] = {}

    for current, subdirs, filenames in os.walk(root):
        parent = os.path.dirname(current)
        inherited = resolved.get(parent, base) if current != root else base

        overrides, marker_path = read_marker(current)
        settings = (
            inherited.merged_with(overrides, _LAYER_MARKER, marker_path) if overrides else inherited
        )
        resolved[current] = settings

        if settings.exclude:
            excluded.append(
                ExcludedFolder(path=current, note=settings.note, marker_path=settings.marker_path)
            )
            subdirs[:] = []
            continue

        # Filesystem order, exactly as the original walk (GHG2RFLUX.py:617-620).
        # Not sorted deliberately: run-record order reaches the sidecar CSV and the
        # report tables, so sorting here would break byte-identity with the baseline.
        for name in filenames:
            if name.endswith(".ghg"):
                files.append(DiscoveredFile(os.path.join(current, name), settings))

    return files, excluded


def find_markers(root: str) -> list[str]:
    """Every marker file under ``root`` (for reporting and ``scan``)."""
    found: list[str] = []
    for current, _subdirs, filenames in os.walk(root):
        if MARKER_NAME in filenames:
            found.append(os.path.join(current, MARKER_NAME))
    return sorted(found)
