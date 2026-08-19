"""Shared fixtures: synthetic site/year trees and ready-made ``RunConfig``s.

Everything lives under ``tmp_path``; no test touches a real data volume.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ``tests/`` is on sys.path under pytest's default import mode, but make the
# fixture package importable regardless of how pytest is invoked.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures.make_ghg import make_corrupt_ghg, make_ghg

from ghg2rflux.settings import MARKER_NAME, MARKER_SECTION, FolderSettings, RunConfig

SITE = "GL-TST"
YEAR = 2024
DAY = datetime(2024, 6, 1)


def write_marker(directory: str | Path, **values: object) -> Path:
    """Drop a ``ghg2rflux.dir.ini`` into ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MARKER_NAME
    body = [f"[{MARKER_SECTION}]"]
    body += [f"{key} = {value}" for key, value in values.items()]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def add_ghg(
    directory: str | Path,
    start: datetime,
    n_rows: int,
    hz: int = 10,
    layout: str = "licor_std",
    name: str | None = None,
) -> Path:
    """Create one synthetic archive whose name carries a 12-digit timestamp."""
    directory = Path(directory)
    if name is None:
        name = f"{SITE}_{start.strftime('%Y%m%d%H%M')}.ghg"
    return make_ghg(directory / name, start, n_rows, hz=hz, layout=layout)


def licor_name(start: datetime) -> str:
    """A real LI-COR filename shape -- deliberately *not* a 12-digit run."""
    return f"{start.strftime('%Y-%m-%dT%H%M%S')}_MM2-{SITE}-AIU-1915.ghg"


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    """``<input_root>/<SITE>/<YEAR>/ec/raw``, created and empty."""
    path = tmp_path / "input" / SITE / str(YEAR) / "ec" / "raw"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def input_root(tmp_path: Path) -> Path:
    return tmp_path / "input"


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    return tmp_path / "output"


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., Path]:
    """Factory writing a minimal ``config.ini`` and returning its path."""

    def _make(
        site: str = SITE,
        year: object = YEAR,
        file_id: str = "F10",
        hz: int = 10,
        input_root: str | Path | None = None,
        output_root: str | Path | None = None,
        averaging_minutes: int | None = None,
        name: str = "config.ini",
    ) -> Path:
        lines = [
            "[settings]",
            f"station_ID = {site}",
            f"year = {year}",
            f"file_ID = {file_id}",
            f"hz = {hz}",
        ]
        if averaging_minutes is not None:
            lines.append(f"averaging_minutes = {averaging_minutes}")
        if input_root is not None or output_root is not None:
            lines.append("")
            lines.append("[paths]")
            if input_root is not None:
                lines.append(f"input_root = {input_root}")
            if output_root is not None:
                lines.append(f"output_root = {output_root}")
        path = tmp_path / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return _make


@pytest.fixture
def make_run_config(
    tmp_path: Path, input_root: Path, output_root: Path, make_config: Callable[..., Path]
) -> Callable[..., RunConfig]:
    """Factory for a ``RunConfig`` pointed entirely at ``tmp_path``."""

    def _make(
        site: str = SITE,
        years: tuple[int, ...] = (YEAR,),
        hz: int = 10,
        averaging_minutes: int = 30,
        layout: str = "auto",
        file_id: str = "F10",
        **kwargs: object,
    ) -> RunConfig:
        config_path = kwargs.pop("config_path", None) or make_config(
            site=site, hz=hz, input_root=input_root, output_root=output_root
        )
        base = FolderSettings(
            hz=hz,
            averaging_minutes=averaging_minutes,
            layout=layout,
            file_id=file_id,
        )
        return RunConfig(
            site=site,
            years=years,
            input_root=str(input_root),
            output_root=str(output_root),
            base=base,
            config_path=str(config_path),
            **kwargs,  # type: ignore[arg-type]
        )

    return _make


@pytest.fixture
def write_disturbance() -> Callable[..., Path]:
    """Write a ``disturbance.txt`` next to the raw tree."""

    def _write(directory: str | Path, windows: list[tuple[str, str]]) -> Path:
        path = Path(directory) / "disturbance.txt"
        lines = ["date_start,date_end,comment"]
        lines += [f"{start},{end},synthetic" for start, end in windows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return _write


@pytest.fixture
def half_hours() -> Callable[[int], list[datetime]]:
    """Successive half-hour start times from 2024-06-01 00:00."""

    def _series(count: int, start: datetime = DAY, minutes: int = 30) -> list[datetime]:
        return [start + timedelta(minutes=minutes * i) for i in range(count)]

    return _series


__all__ = [
    "DAY",
    "SITE",
    "YEAR",
    "add_ghg",
    "licor_name",
    "make_corrupt_ghg",
    "make_ghg",
    "write_marker",
]
