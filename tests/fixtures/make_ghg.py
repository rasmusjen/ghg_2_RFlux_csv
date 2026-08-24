"""Synthetic ``.ghg`` archive builder for the test suite.

A real ``.ghg`` is a ZIP holding, among other members, a ``<name>.data`` text
file whose first seven lines are instrument preamble (``skiprows=7``), followed
by a TAB-delimited header row and TAB-delimited data rows. The reader only ever
looks at ``Seconds``/``Nanoseconds`` plus one of the two column layouts, so the
files produced here carry exactly those columns (plus the leading ``DATAH``
column real files have) and nothing else.

``Seconds``/``Nanoseconds`` are generated as exact integer arithmetic so that
``reader.measure_hz`` -- which takes the median inter-sample interval -- recovers
the requested frequency exactly.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path

from ghg2rflux.columns import LAYOUTS

#: The seven preamble lines a real LI-COR ``.data`` member starts with.
PREAMBLE = (
    "Model:\tLI-7200 Enclosed CO2/H2O Analyzer",
    "SN:\t72H-0867",
    "Instrument:\tMM2-TEST-0001",
    "File Type:\t2",
    "Software Version:\t8.9.0",
    "Timestamp:\t00:00:00",
    "Timezone:\tUTC",
)

NANOS_PER_SECOND = 1_000_000_000


def _epoch_seconds(start: datetime) -> int:
    """Naive datetimes are read back by pandas as UTC, so anchor them there."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return int(start.timestamp())


def data_member_text(
    start: datetime,
    n_rows: int,
    hz: int = 10,
    layout: str = "licor_std",
) -> str:
    """Render the ``.data`` payload for one archive."""
    try:
        columns = LAYOUTS[layout]
    except KeyError:
        raise KeyError(f"Unknown layout {layout!r}; known: {sorted(LAYOUTS)}") from None

    if NANOS_PER_SECOND % hz:
        raise ValueError(f"hz={hz} does not divide a second into whole nanoseconds")
    step_ns = NANOS_PER_SECOND // hz

    header = ["DATAH", "Seconds", "Nanoseconds", *columns]
    lines = [*PREAMBLE, "\t".join(header)]

    epoch = _epoch_seconds(start)
    for i in range(n_rows):
        total_ns = i * step_ns
        seconds = epoch + total_ns // NANOS_PER_SECOND
        nanoseconds = total_ns % NANOS_PER_SECOND
        # Deterministic, bounded, obviously-synthetic values.
        values = [f"{(i % 100) / 10 + j:.4f}" for j in range(len(columns))]
        lines.append("\t".join(["DATA", str(seconds), str(nanoseconds), *values]))

    return "\n".join(lines) + "\n"


def make_ghg(
    path: str | Path,
    start: datetime,
    n_rows: int,
    hz: int = 10,
    layout: str = "licor_std",
) -> Path:
    """Write a valid synthetic ``.ghg`` archive at ``path`` and return it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    member = path.name[: -len(".ghg")] if path.name.endswith(".ghg") else path.name

    payload = data_member_text(start, n_rows, hz=hz, layout=layout)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{member}.data", payload)
        # A couple of decoy members, as real archives carry.
        archive.writestr(f"{member}.metadata", "[Site]\nsite_name=synthetic\n")
        archive.writestr(f"{member}-biomet.data", "no biomet\n")
    return path


def make_corrupt_ghg(path: str | Path) -> Path:
    """Write something that is *not* a zip archive, for the failure path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a zip archive\n" * 8)
    return path


def make_empty_zip_ghg(path: str | Path) -> Path:
    """A valid zip with no ``.data`` member (the other way a read can fail)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "nothing to see here\n")
    return path
