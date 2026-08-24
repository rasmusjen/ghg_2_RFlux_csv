"""Marker parsing, settings algebra, year parsing and the base layering."""

from __future__ import annotations

import pytest
from conftest import write_marker

from ghg2rflux.settings import (
    MARKER_NAME,
    FolderSettings,
    base_settings,
    hz_is_plausible,
    load_config,
    parse_years,
    read_marker,
)


class TestReadMarker:
    def test_no_marker(self, tmp_path):
        assert read_marker(str(tmp_path)) == ({}, "")

    def test_valid_marker(self, tmp_path):
        write_marker(tmp_path, hz=20, averaging_minutes=30, layout="licor_aux", note="mast A")
        overrides, path = read_marker(str(tmp_path))
        assert overrides == {
            "hz": 20,
            "averaging_minutes": 30,
            "layout": "licor_aux",
            "note": "mast A",
        }
        assert path.endswith(MARKER_NAME)

    def test_unknown_key_raises_naming_the_key(self, tmp_path):
        write_marker(tmp_path, frequency=20)
        with pytest.raises(ValueError, match="unknown key 'frequency'"):
            read_marker(str(tmp_path))

    def test_missing_dir_section_raises(self, tmp_path):
        (tmp_path / MARKER_NAME).write_text("[settings]\nhz = 20\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"missing a \[dir\] section"):
            read_marker(str(tmp_path))

    def test_unparseable_marker_raises(self, tmp_path):
        (tmp_path / MARKER_NAME).write_text("[dir\nhz = 20\n", encoding="utf-8")
        with pytest.raises(ValueError):
            read_marker(str(tmp_path))

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", "  True  "])
    def test_exclude_truthy(self, tmp_path, raw):
        write_marker(tmp_path, exclude=raw)
        assert read_marker(str(tmp_path))[0]["exclude"] is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "maybe"])
    def test_exclude_falsy(self, tmp_path, raw):
        write_marker(tmp_path, exclude=raw)
        assert read_marker(str(tmp_path))[0]["exclude"] is False

    def test_file_id_both_spellings(self, tmp_path):
        write_marker(tmp_path, file_ID="F20")
        assert read_marker(str(tmp_path))[0] == {"file_id": "F20"}
        write_marker(tmp_path, file_id="F30")
        assert read_marker(str(tmp_path))[0] == {"file_id": "F30"}

    @pytest.mark.parametrize("bad", ["0", "-5", "ten"])
    def test_invalid_hz_raises(self, tmp_path, bad):
        write_marker(tmp_path, hz=bad)
        with pytest.raises(ValueError, match="invalid value for 'hz'"):
            read_marker(str(tmp_path))

    @pytest.mark.parametrize("bad", ["0", "-30", "7", "abc"])
    def test_invalid_averaging_minutes_raises(self, tmp_path, bad):
        write_marker(tmp_path, averaging_minutes=bad)
        with pytest.raises(ValueError, match="invalid value for 'averaging_minutes'"):
            read_marker(str(tmp_path))


class TestFolderSettings:
    def test_defaults(self):
        s = FolderSettings()
        assert (s.hz, s.averaging_minutes, s.layout, s.file_id) == (10, 30, "auto", "F10")
        assert s.exclude is False
        assert set(s.sources) == {"hz", "averaging_minutes", "layout", "file_id", "exclude"}
        assert set(s.sources.values()) == {"default"}

    @pytest.mark.parametrize(("minutes", "hz"), [(30, 10), (30, 20), (60, 10), (10, 20), (1, 10)])
    def test_expected_rows(self, minutes, hz):
        s = FolderSettings(hz=hz, averaging_minutes=minutes)
        assert s.expected_rows == 60 * minutes * hz

    @pytest.mark.parametrize("minutes", [30, 60, 10, 1, 15])
    def test_expected_files_per_day(self, minutes):
        assert FolderSettings(averaging_minutes=minutes).expected_files_per_day == 1440 // minutes

    def test_merged_with_records_the_layer(self):
        s = FolderSettings().merged_with({"hz": 20}, "marker", "/x/ghg2rflux.dir.ini")
        assert s.hz == 20
        assert s.sources["hz"] == "marker"
        assert s.marker_path == "/x/ghg2rflux.dir.ini"

    def test_merged_with_leaves_untouched_keys_inherited(self):
        s = FolderSettings(hz=20, averaging_minutes=60, file_id="F20")
        merged = s.merged_with({"hz": 10}, "marker")
        assert merged.averaging_minutes == 60
        assert merged.file_id == "F20"
        assert merged.sources["averaging_minutes"] == "default"
        assert merged.sources["hz"] == "marker"

    def test_merged_with_empty_is_a_noop(self):
        s = FolderSettings(hz=20)
        assert s.merged_with({}, "marker", "/x") is s

    def test_merged_with_does_not_mutate_the_original(self):
        s = FolderSettings()
        s.merged_with({"hz": 50}, "marker")
        assert s.hz == 10
        assert s.sources["hz"] == "default"

    def test_marker_path_is_inherited_when_not_overridden(self):
        s = FolderSettings().merged_with({"hz": 20}, "marker", "/deep/ghg2rflux.dir.ini")
        child = s.merged_with({"layout": "licor_aux"}, "marker")
        assert child.marker_path == "/deep/ghg2rflux.dir.ini"


class TestParseYears:
    def test_single(self):
        assert parse_years(["2020"]) == (2020,)

    def test_range(self):
        assert parse_years(["2020-2022"]) == (2020, 2021, 2022)

    def test_mixed_list(self):
        assert parse_years(["2018", "2020-2022", "2025"]) == (2018, 2020, 2021, 2022, 2025)

    def test_deduplicates(self):
        assert parse_years(["2020", "2020-2021", "2021"]) == (2020, 2021)

    def test_preserves_order(self):
        assert parse_years(["2022", "2019", "2021"]) == (2022, 2019, 2021)

    def test_ignores_blanks(self):
        assert parse_years(["", "  ", "2020"]) == (2020,)

    def test_single_year_range(self):
        assert parse_years(["2020-2020"]) == (2020,)

    def test_backwards_range_raises(self):
        with pytest.raises(ValueError, match="runs backwards"):
            parse_years(["2022-2020"])

    def test_unparseable_range_raises(self):
        with pytest.raises(ValueError, match="Cannot parse year range"):
            parse_years(["twenty-twenty"])

    def test_unparseable_year_raises(self):
        with pytest.raises(ValueError, match="Cannot parse year"):
            parse_years(["twentytwenty"])

    def test_empty_input(self):
        assert parse_years([]) == ()


class TestLoadConfig:
    def test_reads_settings_and_overrides(self, make_config):
        path = make_config(site="GL-ZaF", hz=20, file_id="F20")
        parser, overrides = load_config(str(path))
        assert parser["settings"]["station_ID"] == "GL-ZaF"
        assert overrides == {"hz": 20, "file_id": "F20"}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "absent.ini"))

    def test_missing_settings_section_raises(self, tmp_path):
        path = tmp_path / "c.ini"
        path.write_text("[paths]\ninput_root = x\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"missing a \[settings\] section"):
            load_config(str(path))

    def test_averaging_minutes_override(self, make_config):
        _, overrides = load_config(str(make_config(averaging_minutes=60)))
        assert overrides["averaging_minutes"] == 60


class TestBaseSettings:
    def test_defaults_only(self):
        s = base_settings({}, {})
        assert s.hz == 10
        assert s.sources["hz"] == "default"

    def test_config_layer(self):
        s = base_settings({"hz": 20}, {})
        assert s.hz == 20
        assert s.sources["hz"] == "config.ini"

    def test_cli_beats_config(self):
        s = base_settings({"hz": 20, "file_id": "F20"}, {"hz": 50})
        assert s.hz == 50
        assert s.sources["hz"] == "cli"
        # config-only keys survive the CLI layer
        assert s.file_id == "F20"
        assert s.sources["file_id"] == "config.ini"

    def test_full_layering(self):
        s = base_settings(
            {"hz": 20, "averaging_minutes": 60},
            {"layout": "licor_aux"},
        )
        assert (s.hz, s.averaging_minutes, s.layout) == (20, 60, "licor_aux")
        assert s.sources["hz"] == "config.ini"
        assert s.sources["averaging_minutes"] == "config.ini"
        assert s.sources["layout"] == "cli"
        assert s.sources["file_id"] == "default"


def test_hz_is_plausible():
    assert hz_is_plausible(10)
    assert hz_is_plausible(20)
    assert not hz_is_plausible(13)
