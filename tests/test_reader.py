"""Archive reading, layout selection and frequency measurement."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest
from fixtures.make_ghg import make_corrupt_ghg, make_empty_zip_ghg, make_ghg

from ghg2rflux.columns import AUTO, VARS_RENAME, VARS_SUBSET1, VARS_SUBSET2, select_layout
from ghg2rflux.reader import measure_hz, process_ghg_file

START = datetime(2024, 6, 1, 12, 0, 0)


@pytest.fixture
def std_file(tmp_path):
    """A full 30-minute, 10 Hz, licor_std archive: 18000 rows."""
    return str(make_ghg(tmp_path / "GL-TST_202406011200.ghg", START, 18000, hz=10))


class TestProcessGhgFile:
    def test_full_length_file_shape_and_columns(self, std_file):
        read = process_ghg_file(std_file)
        assert read.error is None
        assert read.frame is not None
        assert read.frame.shape == (18000, len(VARS_RENAME))
        assert list(read.frame.columns) == VARS_RENAME
        assert list(read.frame.columns[:4]) == ["U", "V", "W", "T_SONIC"]

    def test_layout_is_licor_std(self, std_file):
        assert process_ghg_file(std_file).layout == "licor_std"

    def test_licor_aux_layout_is_auto_detected(self, tmp_path):
        path = make_ghg(tmp_path / "aux.ghg", START, 600, hz=10, layout="licor_aux")
        read = process_ghg_file(str(path))
        assert read.error is None
        assert read.layout == "licor_aux"
        assert list(read.frame.columns) == VARS_RENAME

    def test_explicit_layout_is_honoured(self, tmp_path):
        path = make_ghg(tmp_path / "aux.ghg", START, 600, hz=10, layout="licor_aux")
        read = process_ghg_file(str(path), layout="licor_aux")
        assert read.error is None
        assert read.layout == "licor_aux"

    def test_wrong_explicit_layout_fails_loudly_but_does_not_raise(self, std_file):
        # licor_aux column names are absent from a licor_std file.
        read = process_ghg_file(std_file, layout="licor_aux")
        assert read.frame is None
        assert read.error

    def test_unknown_layout_name_is_reported_not_raised(self, std_file):
        # select_layout raises KeyError; process_ghg_file's blanket except turns
        # that into an error result so one bad marker cannot abort the run.
        read = process_ghg_file(std_file, layout="nonsense")
        assert read.frame is None
        assert "nonsense" in read.error

    def test_anemometer_diagnostics_is_overwritten_with_sentinel(self, std_file):
        frame = process_ghg_file(std_file).frame
        assert (frame["SA_DIAG"] == -9999).all()

    def test_timestamp_is_the_last_row_not_the_first(self, std_file):
        read = process_ghg_file(std_file)
        # 18000 rows at 10 Hz from 12:00:00 end at 12:29:59.9; the reader's
        # +100 ms offset carries that to 12:30:00 exactly.
        assert read.timestamp == "202406011230"
        assert read.timestamp != START.strftime("%Y%m%d%H%M")

    def test_short_file_timestamp_still_comes_from_the_end(self, tmp_path):
        path = make_ghg(tmp_path / "short.ghg", START, 600, hz=10)
        assert process_ghg_file(str(path)).timestamp == "202406011201"

    def test_measured_hz_is_reported(self, std_file):
        assert process_ghg_file(std_file).measured_hz == pytest.approx(10.0, rel=0.01)

    def test_twenty_hz_file(self, tmp_path):
        path = make_ghg(tmp_path / "fast.ghg", START, 1200, hz=20)
        read = process_ghg_file(str(path))
        assert read.measured_hz == pytest.approx(20.0, rel=0.01)
        assert len(read.frame) == 1200

    def test_corrupt_archive_returns_an_error_and_does_not_raise(self, tmp_path):
        path = make_corrupt_ghg(tmp_path / "broken.ghg")
        read = process_ghg_file(str(path))
        assert read.frame is None
        assert read.timestamp is None
        assert isinstance(read.error, str) and read.error
        assert read.measured_hz is None

    def test_missing_file_returns_an_error(self, tmp_path):
        read = process_ghg_file(str(tmp_path / "absent.ghg"))
        assert read.frame is None
        assert read.error

    def test_zip_without_a_data_member_returns_an_error(self, tmp_path):
        path = make_empty_zip_ghg(tmp_path / "empty.ghg")
        read = process_ghg_file(str(path))
        assert read.frame is None
        assert read.timestamp is None
        # NOTE: the failure here is an IndexError from the ``[...][0]`` member
        # lookup, whose str() is empty -- so ``error`` is '' rather than a
        # message. The pipeline substitutes its own text, so this is cosmetic.
        assert read.error is not None


class TestSelectLayout:
    def test_auto_picks_subset1_when_u_and_v_present(self):
        name, cols = select_layout(list(VARS_SUBSET1), AUTO)
        assert name == "licor_std"
        assert cols == VARS_SUBSET1

    def test_auto_falls_back_to_subset2(self):
        name, cols = select_layout(list(VARS_SUBSET2), AUTO)
        assert name == "licor_aux"
        assert cols == VARS_SUBSET2

    def test_named_layout_is_returned_as_is(self):
        assert select_layout([], "licor_aux") == ("licor_aux", VARS_SUBSET2)

    def test_unknown_layout_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown column layout"):
            select_layout(list(VARS_SUBSET1), "nonsense")


class TestMeasureHz:
    def _series(self, n, hz):
        step = pd.Timedelta(seconds=1) / hz
        return pd.Series([pd.Timestamp("2024-06-01") + i * step for i in range(n)])

    def test_ten_hz(self):
        assert measure_hz(self._series(100, 10)) == pytest.approx(10.0)

    def test_twenty_hz(self):
        assert measure_hz(self._series(100, 20)) == pytest.approx(20.0)

    def test_single_row_returns_none(self):
        assert measure_hz(self._series(1, 10)) is None

    def test_empty_returns_none(self):
        assert measure_hz(pd.Series([], dtype="datetime64[ns]")) is None

    def test_none_returns_none(self):
        assert measure_hz(None) is None

    def test_constant_timestamps_return_none(self):
        stamps = pd.Series([pd.Timestamp("2024-06-01")] * 10)
        assert measure_hz(stamps) is None

    def test_median_ignores_a_single_gap(self):
        stamps = list(self._series(50, 10))
        stamps += [stamps[-1] + pd.Timedelta(hours=1)]
        assert measure_hz(pd.Series(stamps)) == pytest.approx(10.0)
