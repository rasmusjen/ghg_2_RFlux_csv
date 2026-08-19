"""Command-line entry point.

    ghg2rflux -site GL-ZaF -years 2020 2021 2022
    ghg2rflux -site GL-Dsk -years 2020 -hz 10      # markers still win where present
    ghg2rflux -site GL-Dsk -years 2020 --dry-run
    ghg2rflux scan -site GL-Dsk -years 2020

Both ``-site`` and ``--site`` spellings are accepted for every option.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .pipeline import YearResult, run_year
from .scan import scan_year
from .settings import RunConfig, base_settings, load_config, parse_years

DEFAULT_INPUT_ROOT = r"D:\L0_raw"
DEFAULT_OUTPUT_ROOT = r"D:\L0_raw_sc26"


def default_config_path() -> str:
    """``config.ini`` next to the repo root, not the current directory.

    The original read a bare relative ``'config.ini'``, so running the script
    from anywhere but the repo root raised ``KeyError: 'settings'``.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))
    return os.path.join(repo_root, "config.ini")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghg2rflux",
        description="Convert raw LI-COR .ghg archives into RFlux-ready .csv files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "scan"],
        help="'run' converts; 'scan' reports what is in the tree and proposes markers",
    )
    parser.add_argument("-site", "--site", dest="site", help="station ID, e.g. GL-ZaF")
    parser.add_argument(
        "-years",
        "--years",
        dest="years",
        nargs="+",
        help="years to process: 2020 2021 2022, or a range 2020-2022, or a mix",
    )
    parser.add_argument(
        "-hz",
        "--hz",
        dest="hz",
        type=int,
        help="acquisition frequency for folders WITHOUT a marker (markers win)",
    )
    parser.add_argument(
        "--averaging-minutes",
        dest="averaging_minutes",
        type=int,
        help="averaging period in minutes for folders without a marker",
    )
    parser.add_argument("--layout", dest="layout", help="column layout name, or 'auto'")
    parser.add_argument("--file-id", dest="file_id", help="file identifier used in output names")
    # Defaults resolve later: CLI flag -> [paths] in config.ini -> built-in.
    parser.add_argument("--input-root", dest="input_root", default=None)
    parser.add_argument("--output-root", dest="output_root", default=None)
    parser.add_argument("--config", dest="config", default=None, help="path to config.ini")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve settings and report the plan; write nothing",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace existing output files")
    parser.add_argument(
        "--stop-on-error",
        dest="continue_on_error",
        action="store_false",
        help="abort the whole run when a year fails (default: carry on)",
    )
    return parser


def build_run_config(args: argparse.Namespace) -> RunConfig:
    config_path = args.config or default_config_path()
    parser, config_overrides = load_config(config_path)
    settings = parser["settings"]

    site = args.site or settings.get("station_ID")
    if not site:
        raise SystemExit("No site given: pass -site or set station_ID in config.ini")

    if args.years:
        years = parse_years(list(args.years))
    else:
        raw = settings.get("years") or settings.get("year")
        if not raw:
            raise SystemExit("No years given: pass -years or set years/year in config.ini")
        years = parse_years(raw.replace(",", " ").split())

    if not years:
        raise SystemExit("No years to process.")

    cli_overrides: dict[str, object] = {}
    if args.hz is not None:
        cli_overrides["hz"] = args.hz
    if args.averaging_minutes is not None:
        cli_overrides["averaging_minutes"] = args.averaging_minutes
    if args.layout:
        cli_overrides["layout"] = args.layout
    if args.file_id:
        cli_overrides["file_id"] = args.file_id

    paths = parser["paths"] if parser.has_section("paths") else {}
    input_root = args.input_root or paths.get("input_root") or DEFAULT_INPUT_ROOT
    output_root = args.output_root or paths.get("output_root") or DEFAULT_OUTPUT_ROOT

    return RunConfig(
        site=site,
        years=years,
        input_root=input_root,
        output_root=output_root,
        base=base_settings(config_overrides, cli_overrides),
        config_path=config_path,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
    )


def _print_rollup(results: list[YearResult]) -> None:
    if not results:
        return
    print("\n" + "=" * 96)
    print(
        f"{'year':>6} {'found':>7} {'conv':>7} {'excl':>6} {'rej':>6} "
        f"{'fail':>6} {'hz!':>4}  manifest"
    )
    for r in results:
        manifest = os.path.basename(r.report_path) if r.report_path else (r.error or "-")
        print(
            f"{r.year:>6} {r.discovered:>7} {r.converted_total:>7} "
            f"{r.excluded_disturbance:>6} {r.rejected_missing:>6} {r.failed_parse:>6} "
            f"{len(r.hz_mismatches):>4}  {manifest}"
        )
    print("=" * 96)

    mismatched = [r for r in results if r.hz_mismatches]
    if mismatched:
        print("\nWARNING: acquisition frequency mismatches detected:")
        for r in mismatched:
            for m in r.hz_mismatches:
                print(
                    f"  {r.year} {m['folder']}: declared {m['declared_hz']} Hz, "
                    f"measured {m['measured_hz']:.2f} Hz "
                    f"({m['files']}/{m['total']} files) -- {m['consequence']}"
                )
        print("  Review the manifest banner before publishing this output.")

    failed = [r for r in results if r.error]
    if failed:
        print("\nERRORS:")
        for r in failed:
            print(f"  {r.year}: {r.error}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = build_run_config(args)
    command = " ".join(["ghg2rflux", *(argv if argv is not None else sys.argv[1:])])

    if args.command == "scan":
        exit_code = 0
        for year in cfg.years:
            exit_code |= scan_year(cfg, year)
        return exit_code

    print(
        f"ghg2rflux {__version__}: {cfg.site} "
        f"{', '.join(str(y) for y in cfg.years)}" + ("  [dry run]" if cfg.dry_run else "")
    )

    results: list[YearResult] = []
    for year in cfg.years:
        result = run_year(cfg, year, command=command)
        results.append(result)
        if result.error and not cfg.continue_on_error:
            break

    if not cfg.dry_run:
        _print_rollup(results)

    if any(r.error for r in results) or any(r.hz_mismatches for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
