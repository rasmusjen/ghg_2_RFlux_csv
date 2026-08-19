"""Filename timestamp extraction and averaging-boundary rounding."""

from __future__ import annotations

import pytest

from ghg2rflux.timestamps import (
    ceil_timestamp_to_boundary,
    ceil_timestamp_to_half_hour,
    extract_timestamp_from_file_path,
)


class TestExtractTimestamp:
    def test_twelve_digit_name(self):
        assert extract_timestamp_from_file_path("GL-ZaF_202406011230.ghg") == "202406011230"

    def test_twelve_digits_bare(self):
        assert extract_timestamp_from_file_path("/data/raw/202406011230.ghg") == "202406011230"

    def test_fourteen_digit_name_is_truncated_to_twelve(self):
        # A 14-digit YYYYMMDDHHMMSS run is matched by the second pattern and cut
        # to the minute; the 12-digit pattern's lookarounds keep it from firing.
        assert extract_timestamp_from_file_path("site_20240601123045_x.ghg") == "202406011230"

    def test_real_licor_name_has_no_digit_run(self):
        # The LI-COR convention '2024-06-01T000000_MM2-...' carries no run of 12
        # or 14 consecutive digits, so no hint is recovered from the name. This is
        # why the golden dataset's disturbance exclusions all happen post-parse.
        name = "2024-06-01T000000_MM2-GL-ZaF-AIU-1915.ghg"
        assert extract_timestamp_from_file_path(name) is None

    def test_licor_name_under_plain_directory_still_none(self):
        path = "/L0_raw/GL-ZaF/2024/ec/raw/06/2024-06-01T000000_MM2-GL-ZaF-AIU-1915.ghg"
        assert extract_timestamp_from_file_path(path) is None

    def test_directory_carries_the_timestamp(self):
        path = "/data/202406011230/payload.ghg"
        assert extract_timestamp_from_file_path(path) == "202406011230"

    def test_no_timestamp_returns_none(self):
        assert extract_timestamp_from_file_path("no_timestamp_here.ghg") is None

    def test_implausible_digits_are_rejected(self):
        # 999999999999 parses as digits but not as a date -> no hint.
        assert extract_timestamp_from_file_path("x_999999999999.ghg") is None

    def test_second_candidate_is_tried_when_first_is_invalid(self):
        name = "x_999999999999_y_202406011230.ghg"
        assert extract_timestamp_from_file_path(name) == "202406011230"


class TestCeilToBoundary:
    @pytest.mark.parametrize("stamp", ["202406011200", "202406011230", "202406010000"])
    def test_already_on_boundary_is_unchanged(self, stamp):
        assert ceil_timestamp_to_boundary(stamp, 30) == stamp

    def test_rounds_up_to_the_next_half_hour(self):
        assert ceil_timestamp_to_boundary("202406011201", 30) == "202406011230"

    def test_one_minute_before_the_boundary(self):
        assert ceil_timestamp_to_boundary("202406011229", 30) == "202406011230"

    def test_day_rollover(self):
        assert ceil_timestamp_to_boundary("202406012345", 30) == "202406020000"

    def test_month_rollover(self):
        assert ceil_timestamp_to_boundary("202406302345", 30) == "202407010000"

    def test_year_rollover(self):
        assert ceil_timestamp_to_boundary("202412312345", 30) == "202501010000"

    def test_sixty_minute_period(self):
        assert ceil_timestamp_to_boundary("202406011201", 60) == "202406011300"
        assert ceil_timestamp_to_boundary("202406011200", 60) == "202406011200"

    def test_ten_minute_period(self):
        assert ceil_timestamp_to_boundary("202406011201", 10) == "202406011210"
        assert ceil_timestamp_to_boundary("202406011210", 10) == "202406011210"
        assert ceil_timestamp_to_boundary("202406012351", 10) == "202406020000"

    def test_one_minute_period_is_identity(self):
        assert ceil_timestamp_to_boundary("202406011237", 1) == "202406011237"

    @pytest.mark.parametrize("minutes", [0, -1, -30])
    def test_invalid_averaging_minutes_raises(self, minutes):
        with pytest.raises(ValueError, match="averaging_minutes must be positive"):
            ceil_timestamp_to_boundary("202406011201", minutes)

    def test_unparseable_timestamp_raises(self):
        with pytest.raises(ValueError):
            ceil_timestamp_to_boundary("not-a-timestamp", 30)

    def test_half_hour_alias_matches_thirty_minutes(self):
        for stamp in ("202406011201", "202406011230", "202406012345"):
            assert ceil_timestamp_to_half_hour(stamp) == ceil_timestamp_to_boundary(stamp, 30)
