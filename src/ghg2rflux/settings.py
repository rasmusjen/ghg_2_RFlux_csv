"""Configuration model and the four-layer settings resolution.

Every ``.ghg`` file resolves its settings from four layers, deepest wins, merged
per key::

    1. directory marker   ghg2rflux.dir.ini, nearest at-or-above the file,
                          merged over any ancestor markers     <- highest
    2. CLI flags          the default for folders with NO marker
    3. config.ini         the project default
    4. built-in defaults  hz=10, averaging_minutes=30, layout=auto

Markers deliberately beat CLI flags: a marker is a durable, reviewed fact about
that data, whereas ``-hz`` is a convenience default. That ordering is what makes
``-hz 10`` safe to pass across a multi-year run -- it can never silently override
a period someone already documented.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, replace

from .columns import AUTO

#: Filename of a directory-scoped override.
MARKER_NAME = "ghg2rflux.dir.ini"

#: Section a marker's keys live under.
MARKER_SECTION = "dir"

DEFAULT_HZ = 10
DEFAULT_AVERAGING_MINUTES = 30

#: Frequencies we consider plausible; anything else is warned about, not blocked.
PLAUSIBLE_HZ = (1, 2, 5, 10, 20, 50, 100)

_LAYER_DEFAULT = "default"
_LAYER_CONFIG = "config.ini"
_LAYER_CLI = "cli"


@dataclass(frozen=True)
class FolderSettings:
    """Settings in force for one directory (and, by inheritance, its children)."""

    hz: int = DEFAULT_HZ
    averaging_minutes: int = DEFAULT_AVERAGING_MINUTES
    layout: str = AUTO
    file_id: str = "F10"
    exclude: bool = False
    note: str = ""
    #: Which layer each value came from, for the manifest's provenance table.
    sources: dict[str, str] = None  # type: ignore[assignment]
    #: Path of the marker that last set any value here ('' when none).
    marker_path: str = ""

    def __post_init__(self) -> None:
        if self.sources is None:
            object.__setattr__(
                self,
                "sources",
                dict.fromkeys(
                    ("hz", "averaging_minutes", "layout", "file_id", "exclude"), _LAYER_DEFAULT
                ),
            )

    @property
    def expected_rows(self) -> int:
        """Rows a complete file should contain: ``60 * minutes * hz``."""
        return 60 * self.averaging_minutes * self.hz

    @property
    def expected_files_per_day(self) -> int:
        """Files a complete day should contain: ``1440 / minutes``."""
        return 1440 // self.averaging_minutes

    def merged_with(
        self, overrides: dict[str, object], layer: str, marker_path: str = ""
    ) -> FolderSettings:
        """Return a copy with ``overrides`` applied, recording their origin."""
        if not overrides:
            return self
        sources = dict(self.sources)
        for key in overrides:
            sources[key] = layer
        merged: FolderSettings = replace(
            self,
            **overrides,  # type: ignore[arg-type]
            sources=sources,
            marker_path=marker_path or self.marker_path,
        )
        return merged


def _coerce(key: str, raw: str, origin: str) -> object:
    """Convert one marker/config value, with an error naming where it came from."""
    text = raw.strip()
    try:
        if key == "hz":
            value = int(text)
            if value <= 0:
                raise ValueError("must be positive")
            return value
        if key == "averaging_minutes":
            value = int(text)
            if value <= 0 or 1440 % value:
                raise ValueError("must be a positive divisor of 1440")
            return value
        if key == "exclude":
            return text.strip().lower() in {"1", "true", "yes", "on"}
        return text
    except ValueError as e:
        raise ValueError(f"{origin}: invalid value for {key!r}: {raw!r} ({e})") from None


#: Marker keys mapped onto FolderSettings field names.
_MARKER_KEYS = {
    "hz": "hz",
    "averaging_minutes": "averaging_minutes",
    "layout": "layout",
    "file_id": "file_id",
    "file_ID": "file_id",
    "exclude": "exclude",
    "note": "note",
}


def read_marker(directory: str) -> tuple[dict[str, object], str]:
    """Read ``ghg2rflux.dir.ini`` from ``directory``.

    Returns ``(overrides, marker_path)``; ``({}, '')`` when there is no marker.
    """
    marker_path = os.path.join(directory, MARKER_NAME)
    if not os.path.isfile(marker_path):
        return {}, ""

    parser = configparser.ConfigParser()
    # Preserve key casing (configparser lower-cases option names by default).
    parser.optionxform = str  # type: ignore[method-assign,assignment]
    try:
        parser.read(marker_path, encoding="utf-8")
    except configparser.Error as e:
        raise ValueError(f"{marker_path}: cannot be parsed ({e})") from None

    if not parser.has_section(MARKER_SECTION):
        raise ValueError(f"{marker_path}: missing a [{MARKER_SECTION}] section")

    overrides: dict[str, object] = {}
    for key, raw in parser[MARKER_SECTION].items():
        field = _MARKER_KEYS.get(key) or _MARKER_KEYS.get(key.lower())
        if field is None:
            known = ", ".join(sorted(set(_MARKER_KEYS.values())))
            raise ValueError(f"{marker_path}: unknown key {key!r}. Known keys: {known}")
        overrides[field] = _coerce(field, raw, marker_path)

    return overrides, marker_path


def hz_is_plausible(hz: int) -> bool:
    return hz in PLAUSIBLE_HZ


@dataclass(frozen=True)
class RunConfig:
    """Everything one invocation needs, before per-folder resolution."""

    site: str
    years: tuple[int, ...]
    input_root: str
    output_root: str
    base: FolderSettings
    config_path: str
    overwrite: bool = False
    dry_run: bool = False
    continue_on_error: bool = True

    def input_directory(self, year: int) -> str:
        return os.path.join(self.input_root, self.site, str(year), "ec", "raw")

    def output_directory(self, year: int) -> str:
        return os.path.join(self.output_root, self.site, str(year), "ec", "rflux_csv")


def load_config(config_path: str) -> tuple[configparser.ConfigParser, dict[str, object]]:
    """Read the main ``config.ini``; returns the parser and the base overrides."""
    parser = configparser.ConfigParser()
    parser.optionxform = str  # type: ignore[method-assign,assignment]
    read_ok = parser.read(config_path, encoding="utf-8")
    if not read_ok:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if not parser.has_section("settings"):
        raise ValueError(f"{config_path}: missing a [settings] section")

    settings = parser["settings"]
    overrides: dict[str, object] = {}
    if "hz" in settings:
        overrides["hz"] = _coerce("hz", settings["hz"], config_path)
    if "averaging_minutes" in settings:
        overrides["averaging_minutes"] = _coerce(
            "averaging_minutes", settings["averaging_minutes"], config_path
        )
    if "layout" in settings:
        overrides["layout"] = _coerce("layout", settings["layout"], config_path)
    for key in ("file_ID", "file_id"):
        if key in settings:
            overrides["file_id"] = _coerce("file_id", settings[key], config_path)
            break

    return parser, overrides


def parse_years(tokens: list[str]) -> tuple[int, ...]:
    """Expand ``['2020', '2022-2024']`` into ``(2020, 2022, 2023, 2024)``."""
    years: list[int] = []
    for token in tokens:
        text = str(token).strip()
        if not text:
            continue
        if "-" in text:
            first, _, last = text.partition("-")
            try:
                start, end = int(first), int(last)
            except ValueError:
                raise ValueError(f"Cannot parse year range {text!r}") from None
            if end < start:
                raise ValueError(f"Year range {text!r} runs backwards")
            years.extend(range(start, end + 1))
        else:
            try:
                years.append(int(text))
            except ValueError:
                raise ValueError(f"Cannot parse year {text!r}") from None

    seen: dict[int, None] = {}
    for y in years:
        seen[y] = None
    return tuple(seen)


def base_settings(
    config_overrides: dict[str, object],
    cli_overrides: dict[str, object],
) -> FolderSettings:
    """Build the root settings: defaults <- config.ini <- CLI flags."""
    settings = FolderSettings()
    settings = settings.merged_with(config_overrides, _LAYER_CONFIG)
    settings = settings.merged_with(cli_overrides, _LAYER_CLI)
    return settings
