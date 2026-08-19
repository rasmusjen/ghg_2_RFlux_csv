"""Read one ``.ghg`` archive into the RFlux column set.

Transplanted from GHG2RFLUX.py:584-613. Three quirks are load-bearing and must
not be "cleaned up":

* the +100 ms ``DateOffset`` applied to every timestamp (:591);
* ``Anemometer Diagnostics`` overwritten with ``-9999`` wholesale (:597);
* the authoritative timestamp is the **last** row of the file, not the first
  (:607) -- which is why output filenames are ceilinged rather than floored.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass

import pandas as pd
from pandas.tseries.offsets import DateOffset

from .columns import AUTO, VARS_RENAME, select_layout


@dataclass
class ReadResult:
    """Outcome of reading one archive."""

    frame: pd.DataFrame | None
    timestamp: str | None
    error: str | None
    layout: str = ""
    #: Frequency measured from the file's own clock, or None when undeterminable.
    measured_hz: float | None = None


def measure_hz(datetimes: pd.Series) -> float | None:
    """Sampling frequency from the *median* inter-sample interval.

    Median rather than a row count on purpose: a file truncated when the
    instrument stopped mid-interval has far fewer rows than a full period but is
    still sampled at its nominal rate. Counting rows would report those as
    frequency mismatches on every run, and a check that cries wolf is a check
    that gets ignored.
    """
    if datetimes is None or len(datetimes) < 2:
        return None

    deltas = datetimes.diff().dropna()
    if deltas.empty:
        return None

    median_seconds = float(deltas.dt.total_seconds().median())
    if median_seconds <= 0:
        return None
    return 1.0 / median_seconds


def process_ghg_file(file_path: str, layout: str = AUTO) -> ReadResult:
    """Extract, parse and rename the ``.data`` member of a ``.ghg`` archive."""
    try:
        with zipfile.ZipFile(file_path, "r") as archive:
            data_file_name = next((f for f in archive.namelist() if f.endswith(".data")), None)
            if data_file_name is None:
                raise ValueError("archive contains no .data member")
            with archive.open(data_file_name) as data_file:
                df = pd.read_csv(data_file, header=[0], skiprows=7, delimiter="\t")
                # DateOffset takes integers only, hence milliseconds rather than seconds.
                df["Datetime"] = (
                    pd.to_datetime(df["Seconds"], unit="s")
                    + pd.to_timedelta(df["Nanoseconds"], unit="ns")
                ) + DateOffset(milliseconds=100)
                df.index = df["Datetime"]
                df["TIMESTAMP"] = df["Datetime"].dt.strftime("%Y%m%d%H%M%S.%f")
                df["TIMESTAMP"] = pd.to_numeric(df["TIMESTAMP"])
                df["Anemometer Diagnostics"] = -9999

        layout_name, input_columns = select_layout(list(df.columns), layout)
        df1 = df.loc[:, input_columns]
        df1 = df1.rename(columns=dict(zip(input_columns, VARS_RENAME, strict=True)))

        # Use Datetime directly to avoid float/string formatting issues from the
        # numeric TIMESTAMP conversion.
        timestamp = df["Datetime"].iloc[-1].strftime("%Y%m%d%H%M")
        return ReadResult(
            frame=df1,
            timestamp=timestamp,
            error=None,
            layout=layout_name,
            measured_hz=measure_hz(df["Datetime"]),
        )

    except Exception as e:  # one bad archive must not abort the run
        # Some exceptions stringify to "" (an IndexError from a zip carrying no
        # .data member, for one). An empty error would read as "no error" to any
        # caller testing `if result.error:`, so always keep it non-empty.
        message = str(e) or f"{type(e).__name__} (no message)"
        print(f"Error processing file {file_path}: {message}")
        return ReadResult(frame=None, timestamp=None, error=message)
