"""Per-year conversion run.

Transplanted from GHG2RFLUX.py:616-872. One ``run_year`` call is exactly one of
the original script's runs: its own input tree, output directory, HTML manifest
and sidecar CSV. Years share no state, which is what keeps a multi-year run's
per-year reports identical to a single-year run's.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from tqdm import tqdm

from .columns import validate_layout
from .discovery import ExcludedFolder, discover
from .disturbance import build_disturbance_index, is_in_disturbance, load_disturbance_windows
from .provenance import compute_file_hash, compute_tree_hash, get_git_metadata
from .reader import process_ghg_file
from .report import write_report
from .settings import RunConfig, hz_is_plausible
from .timestamps import ceil_timestamp_to_boundary, extract_timestamp_from_file_path

#: A file's measured frequency may drift this fraction from the declared value
#: before it counts as a mismatch. Generous: we are catching 10-vs-20 Hz errors,
#: not clock jitter.
HZ_TOLERANCE = 0.15

#: Files shorter than this fraction of a full period are rejected outright.
COMPLETENESS_THRESHOLD = 0.9


@dataclass
class YearResult:
    """Outcome of one station-year."""

    site: str
    year: int
    discovered: int = 0
    converted_full: int = 0
    converted_padded: int = 0
    excluded_disturbance: int = 0
    excluded_folders: int = 0
    rejected_missing: int = 0
    failed_parse: int = 0
    hz_mismatches: list[dict[str, Any]] = field(default_factory=list)
    report_path: str = ""
    sidecar_path: str = ""
    error: str = ""

    @property
    def converted_total(self) -> int:
        return self.converted_full + self.converted_padded

    @property
    def ok(self) -> bool:
        return not self.error and not self.hz_mismatches


def _collect_hz_mismatches(
    measured_by_folder: dict[str, list[float]],
    declared_by_folder: dict[str, int],
    counts_by_folder: dict[str, int],
    averaging_by_folder: dict[str, int],
    input_directory: str = "",
) -> list[dict[str, Any]]:
    """Compare each folder's measured frequency against its declared one."""
    mismatches: list[dict[str, Any]] = []
    for folder, measurements in sorted(measured_by_folder.items()):
        if not measurements:
            continue
        declared = declared_by_folder.get(folder)
        if not declared:
            continue

        offenders = [m for m in measurements if abs(m - declared) / declared > HZ_TOLERANCE]
        if not offenders:
            continue

        median_measured = sorted(offenders)[len(offenders) // 2]
        averaging = averaging_by_folder.get(folder, 30)
        declared_rows = 60 * averaging * declared
        measured_rows = int(60 * averaging * median_measured)
        if measured_rows > declared_rows:
            consequence = (
                f"declared {declared_rows} rows/file but the data supplies about "
                f"{measured_rows}; excess rows are dropped from the period"
            )
        else:
            consequence = (
                f"declared {declared_rows} rows/file but the data supplies about "
                f"{measured_rows}; the shortfall is padded with -9999"
            )

        mismatches.append(
            {
                "folder": os.path.relpath(folder, input_directory) if input_directory else folder,
                "declared_hz": declared,
                "measured_hz": median_measured,
                "files": len(offenders),
                "total": counts_by_folder.get(folder, len(measurements)),
                "consequence": consequence,
            }
        )
    return mismatches


def run_year(cfg: RunConfig, year: int, command: str = "") -> YearResult:
    """Convert one station-year. Returns counts plus the manifest paths."""
    result = YearResult(site=cfg.site, year=year)

    input_directory = cfg.input_directory(year)
    output_directory = cfg.output_directory(year)

    if not os.path.isdir(input_directory):
        # The original walked a missing directory silently and "succeeded" with
        # zero files, which is indistinguishable from a genuinely empty year.
        result.error = f"Input directory does not exist: {input_directory}"
        print(f"ERROR [{cfg.site} {year}] {result.error}")
        return result

    ghg_files, excluded_folders = discover(input_directory, cfg.base)
    result.discovered = len(ghg_files)
    result.excluded_folders = len(excluded_folders)

    disturbance_file = os.path.join(input_directory, "disturbance.txt")
    disturbance_windows = load_disturbance_windows(disturbance_file)
    windows_indexed, window_starts = build_disturbance_index(disturbance_windows)

    # A misspelled `layout =` in a marker is a configuration error. Catch it once
    # here rather than letting it become a per-file parse failure for the folder.
    for layout in {f.settings.layout for f in ghg_files}:
        try:
            validate_layout(layout)
        except KeyError as e:
            result.error = str(e).strip("\"'")
            print(f"ERROR [{cfg.site} {year}] {result.error}")
            return result

    uses_markers = any(f.settings.marker_path for f in ghg_files) or bool(excluded_folders)

    if cfg.dry_run:
        _print_plan(cfg, year, ghg_files, excluded_folders, input_directory, output_directory)
        return result

    os.makedirs(output_directory, exist_ok=True)

    run_started = datetime.now()
    run_records: list[dict[str, Any]] = []
    converted_timestamps: list[datetime] = []
    seen_timestamps: list[datetime] = []
    written_this_run: set[str] = set()

    measured_by_folder: dict[str, list[float]] = defaultdict(list)
    declared_by_folder: dict[str, int] = {}
    counts_by_folder: dict[str, int] = defaultdict(int)
    averaging_by_folder: dict[str, int] = {}
    files_by_folder: dict[str, int] = defaultdict(int)

    pbar = tqdm(total=len(ghg_files))

    for discovered in ghg_files:
        file_path = discovered.path
        settings = discovered.settings
        file_name = os.path.basename(file_path)
        folder = os.path.dirname(file_path)

        declared_by_folder[folder] = settings.hz
        averaging_by_folder[folder] = settings.averaging_minutes
        counts_by_folder[folder] += 1

        timestamp_hint = extract_timestamp_from_file_path(file_path)
        timestamp_hint_dt = None
        if timestamp_hint is not None:
            try:
                timestamp_hint_dt = datetime.strptime(timestamp_hint, "%Y%m%d%H%M")
                seen_timestamps.append(timestamp_hint_dt)
            except Exception:
                timestamp_hint_dt = None

        base_record = {
            "file_name": file_name,
            "file_path": file_path,
            "hz": settings.hz,
            "averaging_minutes": settings.averaging_minutes,
            "layout": settings.layout,
            "expected_rows": settings.expected_rows,
            "file_id": settings.file_id,
            "source_marker": settings.marker_path,
        }

        if timestamp_hint and is_in_disturbance(timestamp_hint, windows_indexed, window_starts):
            print("File omitted due to disturbance window (prefilter):", file_path)
            run_records.append(
                {
                    **base_record,
                    "status": "excluded_disturbance",
                    "timestamp": timestamp_hint,
                    "timestamp_dt": timestamp_hint_dt,
                    "reason": "Timestamp within disturbance window (prefilter)",
                    "prefilter": True,
                }
            )
            pbar.update(1)
            continue

        read = process_ghg_file(file_path, settings.layout)
        df1, timestamp = read.frame, read.timestamp

        timestamp_dt = None
        if timestamp is not None:
            try:
                timestamp_dt = datetime.strptime(timestamp, "%Y%m%d%H%M")
                if timestamp_hint_dt is None or timestamp_dt != timestamp_hint_dt:
                    seen_timestamps.append(timestamp_dt)
            except Exception:
                timestamp_dt = None

        if df1 is None:
            print("File could not be processed:", file_path)
            run_records.append(
                {
                    **base_record,
                    "status": "failed_parse",
                    "timestamp": timestamp if timestamp else "NA",
                    "timestamp_dt": timestamp_dt,
                    "reason": read.error if read.error else "File is empty or invalid archive",
                }
            )
            pbar.update(1)
            continue

        if read.measured_hz is not None:
            measured_by_folder[folder].append(read.measured_hz)

        if is_in_disturbance(timestamp, windows_indexed, window_starts):
            print("File omitted due to disturbance window:", file_path)
            run_records.append(
                {
                    **base_record,
                    "status": "excluded_disturbance",
                    "timestamp": timestamp,
                    "timestamp_dt": timestamp_dt,
                    "reason": "Timestamp within disturbance window",
                    "row_count": len(df1),
                    "prefilter": False,
                    "measured_hz": read.measured_hz,
                }
            )
            pbar.update(1)
            continue

        expected_rows = settings.expected_rows
        if len(df1) < expected_rows * COMPLETENESS_THRESHOLD:
            print("File is omitted. Missing more than 10% of data:", file_path)
            run_records.append(
                {
                    **base_record,
                    "status": "rejected_missing",
                    "timestamp": timestamp,
                    "timestamp_dt": timestamp_dt,
                    "reason": "More than 10% rows missing",
                    "row_count": len(df1),
                    "measured_hz": read.measured_hz,
                }
            )
            pbar.update(1)
            continue

        padded_rows = 0
        status = "converted_full"
        if len(df1) < expected_rows:
            missing_rows = expected_rows - len(df1)
            padded_rows = missing_rows
            add_missing_rows = pd.DataFrame({col: [-9999] * missing_rows for col in df1.columns})
            df1 = pd.concat([df1, add_missing_rows], ignore_index=True)
            status = "converted_padded"

        try:
            # timestamp is non-None whenever df1 is non-None (see reader.ReadResult).
            output_timestamp = ceil_timestamp_to_boundary(
                str(timestamp), settings.averaging_minutes
            )
        except Exception:
            print("File not written due to invalid timestamp for filename rounding:", file_path)
            run_records.append(
                {
                    **base_record,
                    "status": "failed_parse",
                    "timestamp": timestamp if timestamp else "NA",
                    "timestamp_dt": timestamp_dt,
                    "reason": f"Invalid timestamp for half-hour rounding: {timestamp}",
                }
            )
            pbar.update(1)
            continue

        output_file_name = f"{cfg.site}_EC_{output_timestamp}_{settings.file_id}.csv"
        output_file_path = os.path.join(output_directory, output_file_name)

        if os.path.exists(output_file_path) and not cfg.overwrite:
            # Distinguish a genuine within-run collision from output left by an
            # earlier run: the original could not tell them apart, so a re-run
            # reported every file as failed.
            if output_file_name in written_this_run:
                reason = f"Duplicate output filename after half-hour rounding: {output_file_name}"
            else:
                reason = (
                    f"Duplicate output filename after half-hour rounding: {output_file_name} "
                    "(existed before this run; pass --overwrite to replace)"
                )
            print("File not written due to duplicate rounded timestamp:", output_file_path)
            run_records.append(
                {
                    **base_record,
                    "status": "failed_parse",
                    "timestamp": timestamp,
                    "timestamp_dt": timestamp_dt,
                    "reason": reason,
                }
            )
            pbar.update(1)
            continue

        df1.to_csv(output_file_path, index=False)
        written_this_run.add(output_file_name)
        files_by_folder[folder] += 1

        run_records.append(
            {
                **base_record,
                "status": status,
                "timestamp": timestamp,
                "timestamp_dt": timestamp_dt,
                "reason": "",
                "row_count": len(df1),
                "padded_rows": padded_rows,
                "output_file": output_file_path,
                "measured_hz": read.measured_hz,
            }
        )
        if timestamp_dt is not None:
            converted_timestamps.append(timestamp_dt)

        pbar.update(1)

    pbar.close()

    result.hz_mismatches = _collect_hz_mismatches(
        measured_by_folder,
        declared_by_folder,
        counts_by_folder,
        averaging_by_folder,
        input_directory,
    )

    context = _build_report_context(
        cfg=cfg,
        year=year,
        input_directory=input_directory,
        output_directory=output_directory,
        disturbance_file=disturbance_file,
        disturbance_windows=disturbance_windows,
        run_records=run_records,
        seen_timestamps=seen_timestamps,
        converted_timestamps=converted_timestamps,
        ghg_files=ghg_files,
        excluded_folders=excluded_folders,
        files_by_folder=files_by_folder,
        run_started=run_started,
        hz_mismatches=result.hz_mismatches,
        uses_markers=uses_markers,
        command=command,
    )

    result.converted_full = context["stats"]["converted_full"]
    result.converted_padded = context["stats"]["converted_padded"]
    result.excluded_disturbance = context["stats"]["excluded_disturbance"]
    result.rejected_missing = context["stats"]["rejected_missing"]
    result.failed_parse = context["stats"]["failed_parse"]

    report_path, sidecar_path = write_report(context)
    result.report_path = report_path
    result.sidecar_path = sidecar_path
    print(f"Run manifest written: {report_path}")
    print(f"QA sidecar CSV written: {sidecar_path}")
    return result


def _build_report_context(
    *,
    cfg: RunConfig,
    year: int,
    input_directory: str,
    output_directory: str,
    disturbance_file: str,
    disturbance_windows: list[Any],
    run_records: list[dict[str, Any]],
    seen_timestamps: list[datetime],
    converted_timestamps: list[datetime],
    ghg_files: list[Any],
    excluded_folders: list[ExcludedFolder],
    files_by_folder: dict[str, int],
    run_started: datetime,
    hz_mismatches: list[dict[str, Any]],
    uses_markers: bool,
    command: str,
) -> dict[str, Any]:
    start_datetime = None
    end_datetime = None
    all_timestamps = [
        r["timestamp_dt"] for r in run_records if isinstance(r.get("timestamp_dt"), datetime)
    ]
    if all_timestamps:
        start_datetime = min(all_timestamps)
        end_datetime = max(all_timestamps)
        day_list = list(
            pd.date_range(start_datetime.date(), end_datetime.date(), freq="D").to_pydatetime()
        )
        day_list = [day.replace(hour=0, minute=0, second=0, microsecond=0) for day in day_list]
    else:
        day_list = []

    converted_by_day = dict.fromkeys(day_list, 0)
    seen_by_day = dict.fromkeys(day_list, 0)

    for ts in seen_timestamps:
        day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if day in seen_by_day:
            seen_by_day[day] += 1

    for ts in converted_timestamps:
        day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if day in converted_by_day:
            converted_by_day[day] += 1

    converted_full = sum(1 for r in run_records if r["status"] == "converted_full")
    converted_padded = sum(1 for r in run_records if r["status"] == "converted_padded")
    excluded_disturbance = [r for r in run_records if r["status"] == "excluded_disturbance"]
    # Explicit flag rather than string-matching the human-readable reason, which
    # is how the original split these two counts.
    excluded_prefilter = [r for r in excluded_disturbance if r.get("prefilter")]
    excluded_post_parse = [r for r in excluded_disturbance if not r.get("prefilter")]
    rejected_missing = [r for r in run_records if r["status"] == "rejected_missing"]
    failed_files = [r for r in run_records if r["status"] == "failed_parse"]

    main_module = sys.modules.get("__main__")
    script_file = os.path.abspath(getattr(main_module, "__file__", None) or __file__)
    script_directory = os.path.dirname(os.path.abspath(__file__))
    script_hash = compute_tree_hash(script_directory)
    config_hash = compute_file_hash(cfg.config_path)
    git_metadata = get_git_metadata(script_directory)
    run_finished = datetime.now()

    distinct = sorted({f.settings.expected_rows for f in ghg_files}) or [cfg.base.expected_rows]
    expected_rows_display = " / ".join(str(v) for v in distinct)
    if len(distinct) > 1:
        expected_rows_display += f" ({len(distinct)} periods)"

    averaging_values = sorted({f.settings.averaging_minutes for f in ghg_files}) or [
        cfg.base.averaging_minutes
    ]
    expected_files_per_day = 1440 // averaging_values[0]

    folder_rows = []
    if uses_markers:
        seen_folders: dict[str, Any] = {}
        for f in ghg_files:
            seen_folders.setdefault(os.path.dirname(f.path), f.settings)
        for folder, s in sorted(seen_folders.items()):
            folder_rows.append(
                (
                    os.path.relpath(folder, input_directory),
                    s.hz,
                    s.averaging_minutes,
                    s.layout,
                    s.file_id,
                    files_by_folder.get(folder, 0),
                    s.sources.get("hz", "default"),
                    s.note,
                )
            )

    marker_fingerprint = "|".join(
        sorted(
            {
                f"{f.settings.marker_path}:{f.settings.hz}:{f.settings.averaging_minutes}"
                for f in ghg_files
            }
        )
    )
    report_hash_source = (
        f"{cfg.site}|{year}|{cfg.base.file_id}|{marker_fingerprint}|"
        f"{run_started.isoformat()}|{run_finished.isoformat()}|"
        f"{len(ghg_files)}|{converted_full}|{converted_padded}|{len(excluded_disturbance)}|"
        f"{len(rejected_missing)}|{len(failed_files)}|{script_hash}|{config_hash}"
    )
    report_hash = hashlib.sha256(report_hash_source.encode("utf-8")).hexdigest()

    for s in {f.settings.hz for f in ghg_files}:
        if not hz_is_plausible(s):
            print(f"WARNING: configured frequency {s} Hz is unusual; check your settings.")

    return {
        "station_ID": cfg.site,
        "year": year,
        "file_ID": cfg.base.file_id,
        "input_directory": input_directory,
        "output_directory": output_directory,
        "disturbance_file": disturbance_file,
        "config_file": cfg.config_path,
        # Keys are lower-cased to match the original report exactly: configparser
        # folds option names, and published manifests show 'station_id'/'file_id'.
        "config_settings": {
            "station_id": cfg.site,
            "year": year,
            "file_id": cfg.base.file_id,
            "hz": cfg.base.hz,
        },
        "script_file": script_file,
        "script_directory": script_directory,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "process_datetime": run_finished,
        "script_hash": script_hash,
        "config_hash": config_hash,
        "report_hash": report_hash,
        "script_version": git_metadata["short_hash"],
        "git_metadata": git_metadata,
        "disturbance_windows": disturbance_windows,
        "excluded_disturbance": excluded_disturbance,
        "rejected_missing": rejected_missing,
        "failed_files": failed_files,
        "day_list": day_list,
        "converted_by_day": converted_by_day,
        "seen_by_day": seen_by_day,
        "run_records": run_records,
        "hz_mismatches": hz_mismatches,
        "folder_rows": folder_rows,
        "excluded_folders": excluded_folders,
        "extended_sidecar": uses_markers,
        "run_arguments": {
            "python_version": sys.version.replace("\n", " "),
            "os": f"{platform.system()} {platform.release()} ({platform.version()})",
            "working_directory": os.getcwd(),
            "command": command or " ".join([os.path.basename(sys.argv[0]), *sys.argv[1:]]),
        },
        "stats": {
            "total_discovered": len(ghg_files),
            "converted_total": converted_full + converted_padded,
            "converted_full": converted_full,
            "converted_padded": converted_padded,
            "excluded_disturbance": len(excluded_disturbance),
            "excluded_disturbance_prefilter": len(excluded_prefilter),
            "excluded_disturbance_post_parse": len(excluded_post_parse),
            "rejected_missing": len(rejected_missing),
            "failed_parse": len(failed_files),
            "expected_rows_per_file": expected_rows_display,
            "expected_files_per_day": expected_files_per_day,
            "disturbance_windows_loaded": len(disturbance_windows),
        },
    }


def _print_plan(
    cfg: RunConfig,
    year: int,
    ghg_files: list[Any],
    excluded_folders: list[ExcludedFolder],
    input_directory: str,
    output_directory: str,
) -> None:
    """Dry-run summary: what would be processed, with which settings and why."""
    print(f"\n[{cfg.site} {year}] dry run")
    print(f"  input : {input_directory}")
    print(f"  output: {output_directory}")
    print(f"  {len(ghg_files)} .ghg file(s) discovered")

    by_folder: dict[str, Any] = {}
    counts: dict[str, int] = defaultdict(int)
    for f in ghg_files:
        folder = os.path.dirname(f.path)
        by_folder.setdefault(folder, f.settings)
        counts[folder] += 1

    if by_folder:
        print(f"  {'folder':<34} {'n':>6}  {'hz':>4} {'min':>4}  {'layout':<10} source")
        for folder, s in sorted(by_folder.items()):
            rel = os.path.relpath(folder, input_directory)
            print(
                f"  {rel:<34} {counts[folder]:>6}  {s.hz:>4} {s.averaging_minutes:>4}  "
                f"{s.layout:<10} {s.sources.get('hz', 'default')}"
                + (f"  # {s.note}" if s.note else "")
            )

    for item in excluded_folders:
        print(f"  EXCLUDED {os.path.relpath(item.path, input_directory)}  # {item.note}")
