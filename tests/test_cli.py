"""``main(argv)`` -- argument plumbing, exit codes and the marker/CLI precedence."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from conftest import SITE, add_ghg, write_marker
from fixtures.make_ghg import make_corrupt_ghg

from ghg2rflux.cli import build_parser, build_run_config, main

DAY = datetime(2024, 6, 1)


def raw_for(input_root: Path, year: int, site: str = SITE) -> Path:
    path = input_root / site / str(year) / "ec" / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rflux_for(output_root: Path, year: int, site: str = SITE) -> Path:
    return output_root / site / str(year) / "ec" / "rflux_csv"


def listing(directory: Path, suffix: str) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(n for n in os.listdir(directory) if n.endswith(suffix))


def data_csvs(directory: Path) -> list[str]:
    return [n for n in listing(directory, ".csv") if "_qa_summary" not in n]


def sidecar_frame(directory: Path) -> pd.DataFrame:
    name = listing(directory, "_qa_summary.csv")[0]
    return pd.read_csv(directory / name)


def argv(config: Path, input_root: Path, output_root: Path, *extra: str) -> list[str]:
    return [
        "--config",
        str(config),
        "--input-root",
        str(input_root),
        "--output-root",
        str(output_root),
        *extra,
    ]


class TestSingleYearRun:
    def test_clean_run_returns_zero_and_writes_output(self, make_config, input_root, output_root):
        config = make_config(averaging_minutes=1)
        add_ghg(raw_for(input_root, 2024), DAY, 600, hz=10)

        code = main(argv(config, input_root, output_root, "-site", SITE, "-years", "2024"))
        assert code == 0

        out = rflux_for(output_root, 2024)
        assert data_csvs(out) == [f"{SITE}_EC_202406010001_F10.csv"]
        assert len(listing(out, ".html")) == 1

    def test_missing_year_returns_one(self, make_config, input_root, output_root):
        config = make_config(averaging_minutes=1)
        raw_for(input_root, 2024)
        code = main(argv(config, input_root, output_root, "-site", SITE, "-years", "2019"))
        assert code == 1

    def test_hz_mismatch_returns_one(self, make_config, input_root, output_root):
        config = make_config(averaging_minutes=1)
        raw = raw_for(input_root, 2024)
        folder = raw / "wrong"
        folder.mkdir()
        write_marker(folder, hz=20, note="marker claims 20 Hz")
        add_ghg(folder, DAY, 1200, hz=10)  # actually 10 Hz

        code = main(argv(config, input_root, output_root, "-site", SITE, "-years", "2024"))
        assert code == 1
        html = (
            rflux_for(output_root, 2024) / listing(rflux_for(output_root, 2024), ".html")[0]
        ).read_text(encoding="utf-8")
        assert "Acquisition frequency mismatch detected" in html

    def test_a_corrupt_file_alone_does_not_fail_the_run(self, make_config, input_root, output_root):
        config = make_config(averaging_minutes=1)
        make_corrupt_ghg(raw_for(input_root, 2024) / f"{SITE}_202406010000.ghg")
        code = main(argv(config, input_root, output_root, "-site", SITE, "-years", "2024"))
        assert code == 0


class TestMultiYear:
    def test_one_manifest_per_year_in_separate_directories(
        self, make_config, input_root, output_root
    ):
        config = make_config(averaging_minutes=1)
        for year in (2020, 2021, 2022):
            raw = raw_for(input_root, year)
            add_ghg(raw, DAY.replace(year=year), 600, hz=10)

        code = main(argv(config, input_root, output_root, "-site", SITE, "-years", "2020-2022"))
        assert code == 0

        for year in (2020, 2021, 2022):
            out = rflux_for(output_root, year)
            assert len(listing(out, ".html")) == 1, year
            assert len(listing(out, "_qa_summary.csv")) == 1, year
            assert data_csvs(out) == [f"{SITE}_EC_{year}06010001_F10.csv"]

    def test_parse_years_is_reachable_from_the_command_line(self, make_config, tmp_path):
        parser = build_parser()
        args = parser.parse_args(
            ["--config", str(make_config()), "-site", SITE, "-years", "2020-2022"]
        )
        cfg = build_run_config(args)
        assert cfg.years == (2020, 2021, 2022)

    def test_mixed_year_tokens(self, make_config):
        args = build_parser().parse_args(
            ["--config", str(make_config()), "-site", SITE, "-years", "2018", "2020-2021"]
        )
        assert build_run_config(args).years == (2018, 2020, 2021)

    def test_one_bad_year_still_runs_the_others(self, make_config, input_root, output_root):
        config = make_config(averaging_minutes=1)
        add_ghg(raw_for(input_root, 2021), DAY.replace(year=2021), 600, hz=10)

        code = main(argv(config, input_root, output_root, "-site", SITE, "-years", "2020-2021"))
        assert code == 1  # 2020 is missing
        assert len(listing(rflux_for(output_root, 2021), ".html")) == 1
        assert not rflux_for(output_root, 2020).exists()


class TestDryRun:
    def test_dry_run_writes_nothing(self, make_config, input_root, output_root, capsys):
        config = make_config(averaging_minutes=1)
        add_ghg(raw_for(input_root, 2024), DAY, 600, hz=10)

        code = main(
            argv(config, input_root, output_root, "-site", SITE, "-years", "2024", "--dry-run")
        )
        assert code == 0
        assert not output_root.exists()
        assert "dry run" in capsys.readouterr().out


class TestMarkerPrecedence:
    def test_a_marker_beats_the_hz_flag(self, make_config, input_root, output_root):
        """THE precedence rule: ``-hz`` is only a default for unmarked folders."""
        config = make_config(averaging_minutes=1)
        raw = raw_for(input_root, 2024)

        marked = raw / "marked_20hz"
        marked.mkdir()
        write_marker(marked, hz=20, note="ran at 20 Hz")
        # A complete 1-minute file at 20 Hz: 1200 rows. Judged at the CLI's 10 Hz
        # (600 expected) it would look like a 2x over-length file; judged at the
        # marker's 20 Hz it is exactly full.
        add_ghg(marked, DAY, 1200, hz=20)

        unmarked = raw / "unmarked"
        unmarked.mkdir()
        add_ghg(unmarked, DAY.replace(hour=1), 600, hz=10)

        code = main(
            argv(config, input_root, output_root, "-site", SITE, "-years", "2024", "-hz", "10")
        )
        assert code == 0

        rows = sidecar_frame(rflux_for(output_root, 2024)).set_index("file_name")
        assert rows.loc[f"{SITE}_202406010000.ghg", "hz"] == 20
        assert rows.loc[f"{SITE}_202406010100.ghg", "hz"] == 10
        assert rows.loc[f"{SITE}_202406010000.ghg", "expected_rows"] == 1200
        assert set(rows["status"]) == {"converted_full"}
        assert set(rows["padded_rows"]) == {0}

        out = rflux_for(output_root, 2024)
        written = {n: len(pd.read_csv(out / n)) for n in data_csvs(out)}
        assert written == {
            f"{SITE}_EC_202406010001_F10.csv": 1200,
            f"{SITE}_EC_202406010101_F10.csv": 600,
        }

    def test_cli_hz_applies_where_there_is_no_marker(self, make_config, input_root, output_root):
        config = make_config(hz=10, averaging_minutes=1)
        add_ghg(raw_for(input_root, 2024), DAY, 1200, hz=20)

        code = main(
            argv(config, input_root, output_root, "-site", SITE, "-years", "2024", "-hz", "20")
        )
        assert code == 0
        rows = sidecar_frame(rflux_for(output_root, 2024))
        assert rows.iloc[0]["status"] == "converted_full"


class TestConfigResolution:
    def test_site_and_years_fall_back_to_the_config_file(
        self, make_config, input_root, output_root
    ):
        config = make_config(site=SITE, year=2024, averaging_minutes=1)
        add_ghg(raw_for(input_root, 2024), DAY, 600, hz=10)
        assert main(argv(config, input_root, output_root)) == 0
        assert len(data_csvs(rflux_for(output_root, 2024))) == 1

    def test_roots_fall_back_to_the_config_paths_section(
        self, make_config, input_root, output_root
    ):
        config = make_config(
            year=2024, averaging_minutes=1, input_root=input_root, output_root=output_root
        )
        add_ghg(raw_for(input_root, 2024), DAY, 600, hz=10)
        code = main(["--config", str(config), "-site", SITE, "-years", "2024"])
        assert code == 0
        assert len(data_csvs(rflux_for(output_root, 2024))) == 1

    def test_file_id_flag_reaches_the_output_name(self, make_config, input_root, output_root):
        config = make_config(averaging_minutes=1)
        add_ghg(raw_for(input_root, 2024), DAY, 600, hz=10)
        code = main(
            argv(
                config,
                input_root,
                output_root,
                "-site",
                SITE,
                "-years",
                "2024",
                "--file-id",
                "F77",
            )
        )
        assert code == 0
        assert data_csvs(rflux_for(output_root, 2024)) == [f"{SITE}_EC_202406010001_F77.csv"]

    def test_missing_config_raises(self, tmp_path, input_root, output_root):
        with pytest.raises(FileNotFoundError):
            main(
                argv(
                    tmp_path / "absent.ini",
                    input_root,
                    output_root,
                    "-site",
                    SITE,
                    "-years",
                    "2024",
                )
            )

    def test_no_site_anywhere_exits(self, tmp_path, input_root, output_root):
        config = tmp_path / "bare.ini"
        config.write_text("[settings]\nyear = 2024\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            main(argv(config, input_root, output_root, "-years", "2024"))

    def test_no_years_anywhere_exits(self, tmp_path, input_root, output_root):
        config = tmp_path / "bare.ini"
        config.write_text("[settings]\nstation_ID = GL-TST\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            main(argv(config, input_root, output_root, "-site", SITE))


class TestScanCommand:
    def test_scan_is_read_only(self, make_config, input_root, output_root, capsys):
        config = make_config(averaging_minutes=1)
        add_ghg(raw_for(input_root, 2024), DAY, 600, hz=10)

        main(argv(config, input_root, output_root, "scan", "-site", SITE, "-years", "2024"))
        assert not output_root.exists()
        assert capsys.readouterr().out
