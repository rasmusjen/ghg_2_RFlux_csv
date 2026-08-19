"""Recursive discovery and the per-directory settings resolution.

These trees mirror the real archive shapes: a flat year, month folders, and the
GL-Dsk 2020 case where three sibling folders ran at 20 / 10 / 20 Hz.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from conftest import SITE, write_marker
from fixtures.make_ghg import make_ghg

from ghg2rflux.discovery import discover, find_markers
from ghg2rflux.settings import MARKER_NAME, FolderSettings

BASE = FolderSettings()
DAY = datetime(2024, 6, 1)


def touch_ghg(directory, index: int = 0, hz: int = 10) -> str:
    """A tiny valid archive; discovery never opens it, but realism is cheap."""
    start = DAY + timedelta(minutes=30 * index)
    name = f"{SITE}_{start.strftime('%Y%m%d%H%M')}.ghg"
    return str(make_ghg(os.path.join(str(directory), name), start, 20, hz=hz))


def by_name(files):
    return {os.path.basename(f.path): f for f in files}


class TestFlatAndMonthLayouts:
    def test_flat_year_inherits_base(self, raw_dir):
        for i in range(3):
            touch_ghg(raw_dir, i)
        files, excluded = discover(str(raw_dir), BASE)
        assert len(files) == 3
        assert excluded == []
        for f in files:
            assert f.settings.hz == 10
            assert f.settings.averaging_minutes == 30
            assert f.settings.sources["hz"] == "default"
            assert f.settings.marker_path == ""

    def test_month_folders(self, raw_dir):
        for month in range(1, 13):
            folder = raw_dir / f"{month:02d}"
            folder.mkdir()
            touch_ghg(folder, month)
        files, excluded = discover(str(raw_dir), BASE)
        assert len(files) == 12
        assert excluded == []
        assert {f.settings.hz for f in files} == {10}
        assert {os.path.basename(os.path.dirname(f.path)) for f in files} == {
            f"{m:02d}" for m in range(1, 13)
        }

    def test_non_ghg_files_are_ignored(self, raw_dir):
        touch_ghg(raw_dir, 0)
        (raw_dir / "disturbance.txt").write_text("date_start,date_end\n", encoding="utf-8")
        (raw_dir / "notes.md").write_text("hello\n", encoding="utf-8")
        (raw_dir / "archive.ghg.bak").write_text("x\n", encoding="utf-8")
        files, _ = discover(str(raw_dir), BASE)
        assert len(files) == 1

    def test_empty_tree(self, raw_dir):
        assert discover(str(raw_dir), BASE) == ([], [])

    def test_base_overrides_are_inherited_everywhere(self, raw_dir):
        sub = raw_dir / "06"
        sub.mkdir()
        touch_ghg(sub, 1)
        base = FolderSettings(hz=20, averaging_minutes=60, file_id="F20")
        files, _ = discover(str(raw_dir), base)
        assert files[0].settings.hz == 20
        assert files[0].settings.averaging_minutes == 60
        assert files[0].settings.file_id == "F20"


class TestPerFolderMarkers:
    def test_gl_dsk_2020_shape(self, raw_dir):
        """Three sibling folders at 20 / 10 / 20 Hz, each with its own marker."""
        plan = {"2020_01": 20, "2020_02": 10, "2020_03": 20}
        for name, hz in plan.items():
            folder = raw_dir / name
            folder.mkdir()
            write_marker(folder, hz=hz, note=f"{name} ran at {hz} Hz")
            for i in range(2):
                touch_ghg(folder, i, hz=hz)

        files, excluded = discover(str(raw_dir), BASE)
        assert len(files) == 6
        assert excluded == []

        for f in files:
            folder = os.path.basename(os.path.dirname(f.path))
            assert f.settings.hz == plan[folder]
            assert f.settings.sources["hz"] == "marker"
            assert f.settings.marker_path == os.path.join(str(raw_dir), folder, MARKER_NAME)
            assert f.settings.note == f"{folder} ran at {plan[folder]} Hz"
            # Untouched keys still come from the base layer.
            assert f.settings.averaging_minutes == 30
            assert f.settings.sources["averaging_minutes"] == "default"

    def test_expected_rows_differ_per_folder(self, raw_dir):
        for name, hz in (("a", 10), ("b", 20)):
            folder = raw_dir / name
            folder.mkdir()
            write_marker(folder, hz=hz)
            touch_ghg(folder, 0, hz=hz)
        files, _ = discover(str(raw_dir), BASE)
        rows = {os.path.basename(os.path.dirname(f.path)): f.settings.expected_rows for f in files}
        assert rows == {"a": 60 * 30 * 10, "b": 60 * 30 * 20}

    def test_marker_beats_a_non_default_base(self, raw_dir):
        """A marker outranks the CLI/config layer, not just the built-in default."""
        write_marker(raw_dir, hz=20)
        touch_ghg(raw_dir, 0)
        base = FolderSettings().merged_with({"hz": 50}, "cli")
        files, _ = discover(str(raw_dir), base)
        assert files[0].settings.hz == 20
        assert files[0].settings.sources["hz"] == "marker"


class TestNestedInheritance:
    def test_deeper_marker_overrides_only_its_own_keys(self, raw_dir):
        write_marker(raw_dir, hz=10, averaging_minutes=60, layout="licor_aux", file_ID="F20")
        touch_ghg(raw_dir, 0)

        deep = raw_dir / "06" / "week2"
        deep.mkdir(parents=True)
        write_marker(deep, hz=20)
        touch_ghg(deep, 1, hz=20)

        files = by_name(discover(str(raw_dir), BASE)[0])
        shallow = next(f for f in files.values() if os.path.dirname(f.path) == str(raw_dir))
        deepest = next(f for f in files.values() if os.path.dirname(f.path) == str(deep))

        assert shallow.settings.hz == 10
        assert deepest.settings.hz == 20
        # Per-key merge: everything the deep marker did not mention is inherited.
        for s in (shallow.settings, deepest.settings):
            assert s.averaging_minutes == 60
            assert s.layout == "licor_aux"
            assert s.file_id == "F20"
        assert deepest.settings.sources["hz"] == "marker"
        assert deepest.settings.sources["averaging_minutes"] == "marker"
        assert deepest.settings.marker_path == str(deep / MARKER_NAME)

    def test_folder_without_a_marker_inherits_the_marked_parent(self, raw_dir):
        write_marker(raw_dir, hz=20, note="whole year at 20 Hz")
        child = raw_dir / "06"
        child.mkdir()
        grandchild = child / "day01"
        grandchild.mkdir()
        touch_ghg(grandchild, 0, hz=20)

        files, _ = discover(str(raw_dir), BASE)
        assert len(files) == 1
        s = files[0].settings
        assert s.hz == 20
        assert s.note == "whole year at 20 Hz"
        assert s.sources["hz"] == "marker"
        assert s.marker_path == str(raw_dir / MARKER_NAME)

    def test_three_level_chain(self, raw_dir):
        write_marker(raw_dir, hz=20)
        mid = raw_dir / "06"
        mid.mkdir()
        write_marker(mid, averaging_minutes=60)
        deep = mid / "day01"
        deep.mkdir()
        write_marker(deep, layout="licor_aux")
        touch_ghg(deep, 0, hz=20)

        s = discover(str(raw_dir), BASE)[0][0].settings
        assert (s.hz, s.averaging_minutes, s.layout) == (20, 60, "licor_aux")
        assert s.marker_path == str(deep / MARKER_NAME)


class TestExclusion:
    def test_excluded_subtree_is_pruned_and_siblings_survive(self, raw_dir):
        good = raw_dir / "good"
        good.mkdir()
        touch_ghg(good, 0)
        touch_ghg(good, 1)

        bad = raw_dir / "bad"
        bad.mkdir()
        write_marker(bad, exclude="true", note="instrument in the workshop")
        touch_ghg(bad, 2)
        deeper = bad / "deeper"
        deeper.mkdir()
        touch_ghg(deeper, 3)

        files, excluded = discover(str(raw_dir), BASE)

        assert len(files) == 2
        assert all(str(bad) not in f.path for f in files)
        assert all(os.path.dirname(f.path) == str(good) for f in files)

        assert len(excluded) == 1
        assert excluded[0].path == str(bad)
        assert excluded[0].note == "instrument in the workshop"
        assert excluded[0].marker_path == str(bad / MARKER_NAME)

    def test_exclude_false_does_not_prune(self, raw_dir):
        folder = raw_dir / "maybe"
        folder.mkdir()
        write_marker(folder, exclude="false", hz=20)
        touch_ghg(folder, 0, hz=20)
        files, excluded = discover(str(raw_dir), BASE)
        assert len(files) == 1
        assert excluded == []
        assert files[0].settings.hz == 20

    def test_exclusion_is_inherited_by_children(self, raw_dir):
        bad = raw_dir / "bad"
        bad.mkdir()
        write_marker(bad, exclude="yes")
        touch_ghg(bad, 0)
        files, excluded = discover(str(raw_dir), BASE)
        assert files == []
        assert len(excluded) == 1

    def test_excluding_the_root_yields_nothing(self, raw_dir):
        write_marker(raw_dir, exclude="true", note="year not usable")
        touch_ghg(raw_dir, 0)
        files, excluded = discover(str(raw_dir), BASE)
        assert files == []
        assert [e.path for e in excluded] == [str(raw_dir)]


class TestMarkerFilesThemselves:
    def test_markers_are_never_returned_as_data(self, raw_dir):
        write_marker(raw_dir, hz=20)
        sub = raw_dir / "06"
        sub.mkdir()
        write_marker(sub, note="june")
        touch_ghg(sub, 0, hz=20)
        files, _ = discover(str(raw_dir), BASE)
        assert len(files) == 1
        assert all(not f.path.endswith(MARKER_NAME) for f in files)
        assert all(f.path.endswith(".ghg") for f in files)

    def test_find_markers_lists_all_of_them(self, raw_dir):
        write_marker(raw_dir, hz=20)
        sub = raw_dir / "06"
        sub.mkdir()
        write_marker(sub, note="june")
        deep = sub / "day01"
        deep.mkdir()
        touch_ghg(deep, 0, hz=20)
        assert find_markers(str(raw_dir)) == sorted(
            [str(raw_dir / MARKER_NAME), str(sub / MARKER_NAME)]
        )

    def test_find_markers_on_a_bare_tree(self, raw_dir):
        assert find_markers(str(raw_dir)) == []
