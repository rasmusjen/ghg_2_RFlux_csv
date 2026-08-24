"""Disturbance-window loading, merging and inclusive lookup."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ghg2rflux.disturbance import (
    build_disturbance_index,
    is_in_disturbance,
    load_disturbance_windows,
)


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def index(rows: list[tuple[str, str]]):
    windows = [
        (datetime.strptime(a, "%Y%m%d%H%M"), datetime.strptime(b, "%Y%m%d%H%M")) for a, b in rows
    ]
    return build_disturbance_index(windows)


class TestLoad:
    def test_valid_file(self, tmp_path):
        path = write(
            tmp_path / "disturbance.txt",
            "date_start,date_end,comment\n"
            "202406012000,202406020400,storm\n"
            "202406050000,202406050100,maintenance\n",
        )
        windows = load_disturbance_windows(path)
        assert len(windows) == 2
        assert windows[0][0] == datetime(2024, 6, 1, 20, 0)
        assert windows[0][1] == datetime(2024, 6, 2, 4, 0)

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_disturbance_windows(str(tmp_path / "nope.txt")) == []

    def test_missing_required_columns_returns_empty(self, tmp_path):
        path = write(tmp_path / "d.txt", "start,end\n202406012000,202406020400\n")
        assert load_disturbance_windows(path) == []

    def test_only_one_required_column_returns_empty(self, tmp_path):
        path = write(tmp_path / "d.txt", "date_start,comment\n202406012000,x\n")
        assert load_disturbance_windows(path) == []

    def test_unparseable_rows_are_dropped(self, tmp_path):
        path = write(
            tmp_path / "d.txt",
            "date_start,date_end\n"
            "not-a-date,202406020400\n"
            "202406012000,also-bad\n"
            "202406050000,202406050100\n",
        )
        windows = load_disturbance_windows(path)
        assert len(windows) == 1
        assert windows[0][0] == datetime(2024, 6, 5, 0, 0)

    def test_inverted_rows_are_dropped(self, tmp_path):
        path = write(
            tmp_path / "d.txt",
            "date_start,date_end\n202406020400,202406012000\n202406050000,202406050100\n",
        )
        windows = load_disturbance_windows(path)
        assert len(windows) == 1
        assert windows[0][0] == datetime(2024, 6, 5, 0, 0)

    def test_zero_length_window_is_kept(self, tmp_path):
        path = write(tmp_path / "d.txt", "date_start,date_end\n202406012000,202406012000\n")
        assert len(load_disturbance_windows(path)) == 1

    def test_whitespace_is_stripped(self, tmp_path):
        path = write(tmp_path / "d.txt", "date_start,date_end\n 202406012000 , 202406012100 \n")
        assert len(load_disturbance_windows(path)) == 1

    def test_empty_body_returns_empty(self, tmp_path):
        path = write(tmp_path / "d.txt", "date_start,date_end\n")
        assert load_disturbance_windows(path) == []


class TestBuildIndex:
    def test_empty(self):
        assert build_disturbance_index([]) == ([], [])

    def test_sorts_windows(self):
        merged, starts = index([("202406050000", "202406050100"), ("202406010000", "202406010100")])
        assert starts == sorted(starts)
        assert merged[0][0] == datetime(2024, 6, 1)

    def test_overlapping_windows_merge(self):
        merged, starts = index([("202406010000", "202406011200"), ("202406010600", "202406020000")])
        assert len(merged) == 1
        assert merged[0] == (datetime(2024, 6, 1, 0, 0), datetime(2024, 6, 2, 0, 0))
        assert starts == [datetime(2024, 6, 1, 0, 0)]

    def test_touching_windows_merge(self):
        merged, _ = index([("202406010000", "202406011200"), ("202406011200", "202406020000")])
        assert len(merged) == 1

    def test_contained_window_is_absorbed(self):
        merged, _ = index([("202406010000", "202406020000"), ("202406010600", "202406010700")])
        assert merged == [(datetime(2024, 6, 1), datetime(2024, 6, 2))]

    def test_disjoint_windows_stay_separate(self):
        merged, _ = index([("202406010000", "202406010100"), ("202406050000", "202406050100")])
        assert len(merged) == 2


class TestIsInDisturbance:
    @pytest.fixture
    def idx(self):
        return index([("202406012000", "202406020400"), ("202406100000", "202406100100")])

    def test_inside(self, idx):
        assert is_in_disturbance("202406012300", *idx) is True

    def test_inclusive_at_the_start(self, idx):
        assert is_in_disturbance("202406012000", *idx) is True

    def test_inclusive_at_the_end(self, idx):
        assert is_in_disturbance("202406020400", *idx) is True

    def test_one_minute_outside_each_end(self, idx):
        assert is_in_disturbance("202406011959", *idx) is False
        assert is_in_disturbance("202406020401", *idx) is False

    def test_before_all_windows(self, idx):
        assert is_in_disturbance("202401010000", *idx) is False

    def test_after_all_windows(self, idx):
        assert is_in_disturbance("202412310000", *idx) is False

    def test_between_windows(self, idx):
        assert is_in_disturbance("202406050000", *idx) is False

    def test_second_window_is_found(self, idx):
        assert is_in_disturbance("202406100030", *idx) is True

    def test_no_windows_is_always_false(self):
        assert is_in_disturbance("202406012300", [], []) is False

    def test_unparseable_timestamp_is_false(self, idx):
        assert is_in_disturbance("garbage", *idx) is False

    def test_none_timestamp_is_false(self, idx):
        assert is_in_disturbance(None, *idx) is False

    def test_merged_gap_is_covered(self):
        # The gap between two overlapping windows must be inside the merged one.
        idx = index([("202406010000", "202406011200"), ("202406010600", "202406020000")])
        assert is_in_disturbance("202406011800", *idx) is True
