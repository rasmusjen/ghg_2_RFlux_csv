"""``ghg2rflux scan`` -- read-only inspection that proposes directory markers.

Onboarding a legacy dataset is otherwise detective work: open a folder, guess the
frequency, hope. ``scan`` samples a handful of archives per folder and reports
what is actually there, then prints the marker files it would create. It never
writes -- placing a marker is a deliberate, reviewed act, and the ``note`` field
is the part a human has to supply.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .discovery import discover
from .reader import process_ghg_file
from .settings import MARKER_NAME, MARKER_SECTION, PLAUSIBLE_HZ, RunConfig

#: Archives sampled per folder. Enough to catch a mixed folder, few enough that
#: scanning a whole site-year stays interactive.
SAMPLE_SIZE = 5


@dataclass
class FolderScan:
    folder: str
    n_files: int
    measured: list[float] = field(default_factory=list)
    #: Row count of each sampled file, parallel to ``measured``.
    rows: list[int] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    layouts: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    declared_hz: int = 0
    declared_minutes: int = 30
    has_marker: bool = False

    @property
    def _full_samples(self) -> list[float]:
        """Measurements from files that are not obviously truncated.

        A period's last file is usually cut short when the instrument stops, and
        such a file often reports the *new* frequency at a changeover boundary.
        Judging a folder "mixed" on that evidence would demand a pointless split,
        so short files are excluded here and reported separately.
        """
        if not self.rows:
            return list(self.measured)
        longest = max(self.rows)
        return [hz for hz, n in zip(self.measured, self.rows, strict=True) if n >= 0.5 * longest]

    @property
    def partial_samples(self) -> int:
        return len(self.measured) - len(self._full_samples)

    @property
    def nominal_hz(self) -> int | None:
        """Nearest plausible frequency to the median full-length measurement."""
        candidates = self._full_samples or self.measured
        if not candidates:
            return None
        median = sorted(candidates)[len(candidates) // 2]
        return min(PLAUSIBLE_HZ, key=lambda candidate: abs(candidate - median))

    @property
    def mixed(self) -> bool:
        """True when full-length sampled files disagree -- the folder must be split."""
        full = self._full_samples
        if len(full) < 2:
            return False
        nominals = {min(PLAUSIBLE_HZ, key=lambda c: abs(c - m)) for m in full}
        return len(nominals) > 1

    @property
    def nominal_minutes(self) -> int | None:
        longest = max(self.rows) if self.rows else 0
        full = [
            d for d, n in zip(self.durations, self.rows, strict=True) if n >= 0.5 * longest
        ] or self.durations
        if not full:
            return None
        median = sorted(full)[len(full) // 2]
        for candidate in (5, 10, 15, 20, 30, 60, 120):
            if abs(median - candidate) <= max(1.0, candidate * 0.1):
                return candidate
        return None


def _sample(paths: list[str]) -> list[str]:
    """First, last, middle and a couple of spread picks -- deterministic."""
    if len(paths) <= SAMPLE_SIZE:
        return list(paths)
    n = len(paths)
    idx = sorted({0, n - 1, n // 2, n // 4, (3 * n) // 4})
    return [paths[i] for i in idx]


def scan_year(cfg: RunConfig, year: int) -> int:
    """Print what is in one station-year. Returns a nonzero code on findings."""
    input_directory = cfg.input_directory(year)
    if not os.path.isdir(input_directory):
        print(f"ERROR [{cfg.site} {year}] input directory does not exist: {input_directory}")
        return 1

    ghg_files, excluded_folders = discover(input_directory, cfg.base)
    if not ghg_files:
        print(f"[{cfg.site} {year}] no .ghg files found under {input_directory}")
        return 1

    by_folder: dict[str, list[Any]] = defaultdict(list)
    for f in ghg_files:
        by_folder[os.path.dirname(f.path)].append(f)

    print(f"\n[{cfg.site} {year}] scanning {len(ghg_files)} file(s) in {len(by_folder)} folder(s)")
    print(f"  input: {input_directory}\n")

    scans: list[FolderScan] = []
    for folder, entries in sorted(by_folder.items()):
        settings = entries[0].settings
        scan = FolderScan(
            folder=folder,
            n_files=len(entries),
            declared_hz=settings.hz,
            declared_minutes=settings.averaging_minutes,
            has_marker=bool(settings.marker_path),
        )
        for entry in _sample([e.path for e in entries]):
            read = process_ghg_file(entry, settings.layout)
            if read.frame is None:
                scan.errors.append(f"{os.path.basename(entry)}: {read.error}")
                continue
            if read.measured_hz:
                scan.measured.append(read.measured_hz)
                scan.rows.append(len(read.frame))
                scan.durations.append(len(read.frame) / read.measured_hz / 60.0)
            if read.layout:
                scan.layouts.add(read.layout)
        scans.append(scan)

    header = f"  {'folder':<32} {'n':>6} {'hz':>7} {'min':>5}  {'layout':<10} {'marker':<7} notes"
    print(header)
    print("  " + "-" * (len(header) - 2))

    findings = 0
    for scan in scans:
        rel = os.path.relpath(scan.folder, input_directory)
        hz_text = f"{scan.nominal_hz}" if scan.nominal_hz else "?"
        min_text = f"{scan.nominal_minutes}" if scan.nominal_minutes else "?"
        layout_text = "/".join(sorted(scan.layouts)) or "?"
        marker_text = "yes" if scan.has_marker else "-"

        notes = []
        if scan.mixed:
            notes.append("MIXED Hz among full-length files -- split this folder")
            findings += 1
        if scan.partial_samples:
            notes.append(
                f"{scan.partial_samples} truncated boundary file(s), "
                "normally rejected by the completeness check"
            )
        if scan.nominal_hz and scan.nominal_hz != scan.declared_hz:
            notes.append(f"declared {scan.declared_hz} Hz")
            findings += 1
        if scan.nominal_minutes and scan.nominal_minutes != scan.declared_minutes:
            notes.append(f"declared {scan.declared_minutes} min")
            findings += 1
        if len(scan.layouts) > 1:
            notes.append("MIXED column layouts")
            findings += 1
        if scan.errors:
            notes.append(f"{len(scan.errors)} unreadable")

        print(
            f"  {rel:<32} {scan.n_files:>6} {hz_text:>7} {min_text:>5}  "
            f"{layout_text:<10} {marker_text:<7} {'; '.join(notes)}"
        )

    proposals = [
        s
        for s in scans
        if s.nominal_hz
        and not s.has_marker
        and (s.nominal_hz != s.declared_hz or s.nominal_minutes not in (None, 30))
    ]

    if proposals:
        print(f"\n{len(proposals)} marker(s) proposed. scan never writes -- place these by hand:\n")
        for scan in proposals:
            print(f"  # {os.path.join(scan.folder, MARKER_NAME)}")
            print(f"  [{MARKER_SECTION}]")
            print(f"  hz   = {scan.nominal_hz}")
            if scan.nominal_minutes and scan.nominal_minutes != 30:
                print(f"  averaging_minutes = {scan.nominal_minutes}")
            print("  note = <why this period differs -- instrument swap, service visit, ...>")
            print()
    else:
        print("\nNo markers proposed: every folder already matches its resolved settings.")

    for item in excluded_folders:
        print(f"  EXCLUDED {os.path.relpath(item.path, input_directory)}  # {item.note}")

    return 1 if findings else 0
