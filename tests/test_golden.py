"""Golden regression against the captured baseline.

The baseline lives in a volatile scratch directory, so this test skips cleanly
when it is absent. Deselect it with ``-m 'not golden'``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from ghg2rflux.cli import main

pytestmark = pytest.mark.golden

REPO_ROOT = Path(__file__).resolve().parents[1]

GOLDEN_ROOT = Path(
    os.environ.get(
        "GHG2RFLUX_GOLDEN_ROOT",
        r"C:\Users\au710242\AppData\Local\Temp\claude"
        r"\C--Users-au710242-Code-Python-ghg-2-RFlux-csv"
        r"\2c31f0bd-ae8d-4b7b-bda1-16c7d242c10d\scratchpad\golden",
    )
)

SITE = "GL-ZaF"
YEAR = 2024
INPUT_ROOT = GOLDEN_ROOT / "L0_raw"
EXPECTED_DIR = GOLDEN_ROOT / "expected" / SITE / str(YEAR) / "ec" / "rflux_csv"


def load_comparer():
    """Import ``scripts/compare_golden.py`` rather than re-deriving its masks."""
    path = REPO_ROOT / "scripts" / "compare_golden.py"
    if not path.is_file():
        pytest.skip(f"comparison script not found: {path}")
    spec = importlib.util.spec_from_file_location("compare_golden", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_golden"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def baseline():
    if not INPUT_ROOT.is_dir() or not EXPECTED_DIR.is_dir():
        pytest.skip(f"golden baseline not present under {GOLDEN_ROOT}")
    return GOLDEN_ROOT


def test_golden_run_matches_the_baseline(baseline, tmp_path, capsys):
    output_root = tmp_path / "actual"
    exit_code = main(
        [
            "--config",
            str(REPO_ROOT / "config.ini"),
            "-site",
            SITE,
            "-years",
            str(YEAR),
            "--input-root",
            str(INPUT_ROOT),
            "--output-root",
            str(output_root),
        ]
    )
    actual_dir = output_root / SITE / str(YEAR) / "ec" / "rflux_csv"
    assert actual_dir.is_dir(), "the run produced no output directory"
    assert exit_code == 0

    expected_csvs = sorted(
        n for n in os.listdir(EXPECTED_DIR) if n.endswith(".csv") and "_qa_summary" not in n
    )
    actual_csvs = sorted(
        n for n in os.listdir(actual_dir) if n.endswith(".csv") and "_qa_summary" not in n
    )
    assert len(expected_csvs) == 79
    assert actual_csvs == expected_csvs

    comparer = load_comparer()
    problems: list[str] = []
    problems += comparer.compare_data_csvs(str(EXPECTED_DIR), str(actual_dir))
    problems += comparer.compare_sidecars(str(EXPECTED_DIR), str(actual_dir))
    problems += comparer.compare_html(str(EXPECTED_DIR), str(actual_dir))

    with capsys.disabled():
        for line in problems:
            print(line)
    assert problems == []


def test_golden_counts(baseline, tmp_path):
    """96 input archives -> 79 converted_full and 17 excluded_disturbance."""
    from ghg2rflux.pipeline import run_year
    from ghg2rflux.settings import FolderSettings, RunConfig

    cfg = RunConfig(
        site=SITE,
        years=(YEAR,),
        input_root=str(INPUT_ROOT),
        output_root=str(tmp_path / "counts"),
        base=FolderSettings(hz=10, averaging_minutes=30, file_id="F10"),
        config_path=str(REPO_ROOT / "config.ini"),
    )
    result = run_year(cfg, YEAR)

    assert result.error == ""
    assert result.discovered == 96
    assert result.converted_full == 79
    assert result.converted_padded == 0
    assert result.excluded_disturbance == 17
    assert result.rejected_missing == 0
    assert result.failed_parse == 0
    assert result.hz_mismatches == []
