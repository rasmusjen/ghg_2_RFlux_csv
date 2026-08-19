"""End-to-end ``run_year`` against synthetic trees under ``tmp_path``."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from conftest import SITE, YEAR, add_ghg, licor_name, write_marker
from fixtures.make_ghg import make_corrupt_ghg, make_ghg

from ghg2rflux.pipeline import run_year

DAY = datetime(2024, 6, 1)

# A short averaging period keeps most tests to a few hundred rows per file.
FAST_MINUTES = 1
FAST_ROWS_10HZ = 60 * FAST_MINUTES * 10  # 600


def out_csvs(cfg, year=YEAR) -> list[str]:
    directory = cfg.output_directory(year)
    if not os.path.isdir(directory):
        return []
    return sorted(n for n in os.listdir(directory) if n.endswith(".csv") and "_qa_summary" not in n)


def sidecar(cfg, year=YEAR) -> pd.DataFrame:
    directory = cfg.output_directory(year)
    name = next(n for n in os.listdir(directory) if n.endswith("_qa_summary.csv"))
    return pd.read_csv(os.path.join(directory, name))


def manifest_text(cfg, year=YEAR) -> str:
    directory = cfg.output_directory(year)
    name = next(n for n in os.listdir(directory) if n.endswith(".html"))
    return Path(directory, name).read_text(encoding="utf-8")


@pytest.fixture
def fast_cfg(make_run_config):
    """10 Hz, 1-minute periods -> 600 expected rows per file."""
    return make_run_config(hz=10, averaging_minutes=FAST_MINUTES)


class TestConversion:
    def test_full_length_file_converts(self, raw_dir, fast_cfg):
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        result = run_year(fast_cfg, YEAR)

        assert result.error == ""
        assert result.discovered == 1
        assert result.converted_full == 1
        assert result.converted_padded == 0
        assert result.rejected_missing == 0
        assert result.failed_parse == 0

        # Last row 00:00:59.9 + 100 ms -> 00:01:00, already on a 1-minute boundary.
        assert out_csvs(fast_cfg) == [f"{SITE}_EC_202406010001_F10.csv"]
        written = pd.read_csv(os.path.join(fast_cfg.output_directory(YEAR), out_csvs(fast_cfg)[0]))
        assert len(written) == FAST_ROWS_10HZ
        assert list(written.columns)[:4] == ["U", "V", "W", "T_SONIC"]

        assert os.path.isfile(result.report_path)
        assert os.path.isfile(result.sidecar_path)

    def test_several_files_each_get_their_own_csv(self, raw_dir, fast_cfg):
        for i in range(4):
            add_ghg(raw_dir, DAY + timedelta(minutes=i), FAST_ROWS_10HZ, hz=10)
        result = run_year(fast_cfg, YEAR)
        assert result.converted_full == 4
        assert len(out_csvs(fast_cfg)) == 4

    def test_file_id_reaches_the_output_name(self, raw_dir, make_run_config):
        cfg = make_run_config(hz=10, averaging_minutes=FAST_MINUTES, file_id="F42")
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        run_year(cfg, YEAR)
        assert out_csvs(cfg) == [f"{SITE}_EC_202406010001_F42.csv"]


class TestCompleteness:
    def test_ninety_five_percent_is_padded_to_full_length(self, raw_dir, fast_cfg):
        n = int(FAST_ROWS_10HZ * 0.95)  # 570
        add_ghg(raw_dir, DAY, n, hz=10)
        result = run_year(fast_cfg, YEAR)

        assert result.converted_padded == 1
        assert result.converted_full == 0
        assert len(out_csvs(fast_cfg)) == 1

        written = pd.read_csv(os.path.join(fast_cfg.output_directory(YEAR), out_csvs(fast_cfg)[0]))
        assert len(written) == FAST_ROWS_10HZ
        padding = written.iloc[n:]
        assert (padding == -9999).all().all()

        row = sidecar(fast_cfg).iloc[0]
        assert row["status"] == "converted_padded"
        assert row["padded_rows"] == FAST_ROWS_10HZ - n
        assert row["row_count"] == FAST_ROWS_10HZ

    def test_half_length_file_is_rejected_and_writes_nothing(self, raw_dir, fast_cfg):
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ // 2, hz=10)
        result = run_year(fast_cfg, YEAR)

        assert result.rejected_missing == 1
        assert result.converted_total == 0
        assert out_csvs(fast_cfg) == []
        assert sidecar(fast_cfg).iloc[0]["status"] == "rejected_missing"

    def test_exactly_at_the_threshold_is_kept(self, raw_dir, fast_cfg):
        # 90% is the cut-off and the comparison is strict '<'.
        add_ghg(raw_dir, DAY, int(FAST_ROWS_10HZ * 0.9), hz=10)
        result = run_year(fast_cfg, YEAR)
        assert result.converted_padded == 1
        assert result.rejected_missing == 0

    def test_corrupt_file_is_a_parse_failure(self, raw_dir, fast_cfg):
        make_corrupt_ghg(raw_dir / f"{SITE}_202406010000.ghg")
        result = run_year(fast_cfg, YEAR)

        assert result.discovered == 1
        assert result.failed_parse == 1
        assert result.converted_total == 0
        assert out_csvs(fast_cfg) == []
        assert sidecar(fast_cfg).iloc[0]["status"] == "failed_parse"

    def test_mixed_tree(self, raw_dir, fast_cfg):
        # Spaced 10 minutes apart: a short file's last row still rounds onto its
        # own minute, so no two outputs can collide.
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        add_ghg(raw_dir, DAY + timedelta(minutes=10), int(FAST_ROWS_10HZ * 0.95), hz=10)
        add_ghg(raw_dir, DAY + timedelta(minutes=20), FAST_ROWS_10HZ // 2, hz=10)
        make_corrupt_ghg(raw_dir / f"{SITE}_202406010030.ghg")

        result = run_year(fast_cfg, YEAR)
        assert (result.discovered, result.converted_full, result.converted_padded) == (4, 1, 1)
        assert (result.rejected_missing, result.failed_parse) == (1, 1)
        assert len(out_csvs(fast_cfg)) == 2


class TestDisturbance:
    def test_both_prefilter_and_post_parse_paths_are_exercised(
        self, raw_dir, fast_cfg, write_disturbance
    ):
        write_disturbance(raw_dir, [("202406010000", "202406010010")])

        # A 12-digit filename gives a hint -> excluded before the archive is opened.
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        # A LI-COR-style name yields no hint -> excluded only after parsing.
        add_ghg(
            raw_dir,
            DAY + timedelta(minutes=1),
            FAST_ROWS_10HZ,
            hz=10,
            name=licor_name(DAY + timedelta(minutes=1)),
        )
        # Well outside the window.
        add_ghg(raw_dir, DAY + timedelta(hours=5), FAST_ROWS_10HZ, hz=10)

        result = run_year(fast_cfg, YEAR)

        assert result.discovered == 3
        assert result.excluded_disturbance == 2
        assert result.converted_full == 1
        assert len(out_csvs(fast_cfg)) == 1

        rows = sidecar(fast_cfg)
        excluded = rows[rows["status"] == "excluded_disturbance"]
        reasons = set(excluded["reason"])
        assert "Timestamp within disturbance window (prefilter)" in reasons
        assert "Timestamp within disturbance window" in reasons

        html = manifest_text(fast_cfg)
        assert "Timestamp within disturbance window (prefilter)" in html

    def test_no_disturbance_file_excludes_nothing(self, raw_dir, fast_cfg):
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        result = run_year(fast_cfg, YEAR)
        assert result.excluded_disturbance == 0

    def test_excluded_folder_is_counted(self, raw_dir, fast_cfg):
        bad = raw_dir / "bad"
        bad.mkdir()
        write_marker(bad, exclude="true", note="instrument removed")
        add_ghg(bad, DAY, FAST_ROWS_10HZ, hz=10)
        add_ghg(raw_dir, DAY + timedelta(minutes=1), FAST_ROWS_10HZ, hz=10)

        result = run_year(fast_cfg, YEAR)
        assert result.excluded_folders == 1
        assert result.discovered == 1
        assert result.converted_full == 1


class TestMultipleFrequencies:
    """The core regression: per-folder Hz, not one scalar for the whole run."""

    def test_ten_and_twenty_hz_folders_both_convert_unpadded(self, raw_dir, make_run_config):
        cfg = make_run_config(hz=10, averaging_minutes=30)

        slow = raw_dir / "slow_10hz"
        slow.mkdir()
        write_marker(slow, hz=10, note="10 Hz period")
        add_ghg(slow, DAY, 60 * 30 * 10, hz=10)

        fast = raw_dir / "fast_20hz"
        fast.mkdir()
        write_marker(fast, hz=20, note="20 Hz period")
        add_ghg(fast, DAY + timedelta(minutes=30), 60 * 30 * 20, hz=20)

        result = run_year(cfg, YEAR)

        assert result.error == ""
        assert result.discovered == 2
        assert result.converted_full == 2, "a 20 Hz file must not be judged against 10 Hz"
        assert result.converted_padded == 0
        assert result.hz_mismatches == []

        rows = sidecar(cfg).set_index("file_name")
        assert set(rows["status"]) == {"converted_full"}
        assert set(rows["padded_rows"]) == {0}
        assert dict(zip(rows.index, rows["hz"], strict=True)) == {
            f"{SITE}_202406010000.ghg": 10,
            f"{SITE}_202406010030.ghg": 20,
        }
        assert dict(zip(rows.index, rows["expected_rows"], strict=True)) == {
            f"{SITE}_202406010000.ghg": 18000,
            f"{SITE}_202406010030.ghg": 36000,
        }

        directory = cfg.output_directory(YEAR)
        written = {n: len(pd.read_csv(os.path.join(directory, n))) for n in out_csvs(cfg)}
        assert written == {
            f"{SITE}_EC_202406010030_F10.csv": 60 * 30 * 10,
            f"{SITE}_EC_202406010100_F10.csv": 60 * 30 * 20,
        }

    def test_folder_settings_table_appears_in_the_manifest(self, raw_dir, make_run_config):
        cfg = make_run_config(hz=10, averaging_minutes=FAST_MINUTES)
        folder = raw_dir / "marked"
        folder.mkdir()
        write_marker(folder, hz=20, note="mast swapped")
        add_ghg(folder, DAY, 60 * FAST_MINUTES * 20, hz=20)
        result = run_year(cfg, YEAR)
        assert result.converted_full == 1
        assert "mast swapped" in manifest_text(cfg)


class TestHzMismatch:
    def test_declared_twenty_measured_ten(self, raw_dir, make_run_config):
        cfg = make_run_config(hz=10, averaging_minutes=FAST_MINUTES)
        folder = raw_dir / "wrong"
        folder.mkdir()
        write_marker(folder, hz=20, note="marker says 20 Hz")
        # Enough rows to clear the completeness threshold for the declared 20 Hz
        # (1200 expected) while actually being sampled at 10 Hz.
        add_ghg(folder, DAY, 1200, hz=10)

        result = run_year(cfg, YEAR)

        assert result.error == ""
        assert result.hz_mismatches, "a 2x frequency error must be flagged"
        mismatch = result.hz_mismatches[0]
        assert mismatch["declared_hz"] == 20
        assert mismatch["measured_hz"] == pytest.approx(10.0, rel=0.01)
        assert mismatch["files"] == 1
        assert result.ok is False

        html = manifest_text(cfg)
        assert "Acquisition frequency mismatch detected" in html

    def test_matching_frequency_produces_no_mismatch(self, raw_dir, fast_cfg):
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        result = run_year(fast_cfg, YEAR)
        assert result.hz_mismatches == []
        assert result.ok is True


class TestFailureModes:
    def test_missing_input_directory_sets_error_and_does_not_raise(self, fast_cfg):
        result = run_year(fast_cfg, 1999)
        assert result.error
        assert "does not exist" in result.error
        assert result.discovered == 0
        assert not os.path.isdir(fast_cfg.output_directory(1999))

    def test_empty_input_directory_still_writes_a_manifest(self, raw_dir, fast_cfg):
        result = run_year(fast_cfg, YEAR)
        assert result.error == ""
        assert result.discovered == 0
        assert os.path.isfile(result.report_path)

    def test_duplicate_rounded_timestamps_collide(self, raw_dir, fast_cfg):
        # Two files 10 seconds apart both ceiling onto the same 1-minute boundary.
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10, name="a_202406010000.ghg")
        make_ghg(
            raw_dir / "b_202406010000.ghg",
            DAY + timedelta(seconds=10),
            FAST_ROWS_10HZ,
            hz=10,
        )
        result = run_year(fast_cfg, YEAR)
        assert result.converted_total == 1
        assert result.failed_parse == 1
        assert len(out_csvs(fast_cfg)) == 1

    def test_overwrite_replaces_prior_output(self, raw_dir, fast_cfg, make_run_config):
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        first = run_year(fast_cfg, YEAR)
        assert first.converted_full == 1

        again = run_year(fast_cfg, YEAR)
        assert again.converted_total == 0
        assert again.failed_parse == 1

        overwriting = make_run_config(
            hz=10, averaging_minutes=FAST_MINUTES, overwrite=True, config_path=fast_cfg.config_path
        )
        third = run_year(overwriting, YEAR)
        assert third.converted_full == 1

    def test_dry_run_writes_nothing(self, raw_dir, make_run_config):
        cfg = make_run_config(hz=10, averaging_minutes=FAST_MINUTES, dry_run=True)
        add_ghg(raw_dir, DAY, FAST_ROWS_10HZ, hz=10)
        result = run_year(cfg, YEAR)
        assert result.discovered == 1
        assert result.converted_total == 0
        assert not os.path.exists(cfg.output_directory(YEAR))
        assert result.report_path == ""

    def test_unknown_layout_in_a_marker_fails_the_year_not_every_file(self, raw_dir, fast_cfg):
        # A typo'd `layout =` is a configuration error, so it must stop the year
        # with one clear message. Letting it reach process_ghg_file would turn a
        # single typo into "every file in this folder failed to parse".
        folder = raw_dir / "period_a"
        folder.mkdir()
        write_marker(folder, layout="licor_stdd")
        make_ghg(folder / licor_name(DAY), DAY, FAST_ROWS_10HZ, hz=10)

        result = run_year(fast_cfg, YEAR)

        assert result.error
        assert "licor_stdd" in result.error
        assert "Known layouts" in result.error
        assert result.failed_parse == 0
        assert out_csvs(fast_cfg) == []
