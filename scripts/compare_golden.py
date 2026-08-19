"""Compare a candidate run against the captured golden baseline.

Usage::

    python scripts/compare_golden.py <expected_dir> <actual_dir>

CSV outputs are compared byte-for-byte. The sidecar CSV is compared after
dropping the ``processing_datetime`` column (which is the wall clock) and any
columns added since the baseline was captured. The HTML manifest is compared
after masking the fields that legitimately vary between two runs of identical
code: run timestamps, hashes, git metadata, and the paths of the run itself.
"""

from __future__ import annotations

import csv
import os
import re
import sys

#: Fields that legitimately differ between two runs of identical code: wall
#: clocks, hashes, git metadata, and the absolute paths of the run itself.
HTML_MASKS = (
    (re.compile(r"\\"), "/"),
    (re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"), "<TIMESTAMP>"),
    (re.compile(r"[A-Za-z]:/[^\"'<>]*"), "<PATH>"),
    (re.compile(r"https?://[^\"'<> ]*"), "<URL>"),
    (re.compile(r"Script version: [^<]*"), "Script version: <VERSION>"),
    (
        re.compile(
            r'<tr><th class="kv-key">(Git [^<]*|Script SHA256|Config SHA256|Report hash)'
            r"</th><td[^>]*>.*?</td></tr>"
        ),
        "<PROVENANCE_ROW>",
    ),
    # Intentional change: the original fabricated this string as
    # "python <scriptname>"; the package records the real argv.
    (
        re.compile(r'<th class="kv-key">Command used</th><td[^>]*>.*?</td>'),
        "<COMMAND_ROW>",
    ),
    (re.compile(r"_report_\d{12}_\d{12}_\d{14}"), "_report_<TOKENS>"),
    (re.compile(r"[0-9a-f]{40,64}"), "<HASH>"),
)

#: Sidecar columns that are wall-clock or absolute paths.
SIDECAR_VOLATILE = {"processing_datetime", "file_path", "output_file"}


def data_csvs(directory: str) -> dict[str, str]:
    return {
        name: os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.endswith(".csv") and "_qa_summary" not in name
    }


def find_one(directory: str, suffix: str) -> str | None:
    hits = sorted(n for n in os.listdir(directory) if n.endswith(suffix))
    return os.path.join(directory, hits[0]) if hits else None


def compare_data_csvs(expected_dir: str, actual_dir: str) -> list[str]:
    problems: list[str] = []
    expected = data_csvs(expected_dir)
    actual = data_csvs(actual_dir)

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        problems.append(f"{len(missing)} expected CSV(s) missing, e.g. {missing[:3]}")
    if extra:
        problems.append(f"{len(extra)} unexpected CSV(s), e.g. {extra[:3]}")

    identical = 0
    for name in sorted(set(expected) & set(actual)):
        with open(expected[name], "rb") as f:
            a = f.read()
        with open(actual[name], "rb") as f:
            b = f.read()
        if a == b:
            identical += 1
        else:
            problems.append(f"CSV differs: {name} ({len(a)} vs {len(b)} bytes)")

    print(f"  data CSVs: {identical}/{len(expected)} byte-identical")
    return problems


def compare_sidecars(expected_dir: str, actual_dir: str) -> list[str]:
    problems: list[str] = []
    e_path = find_one(expected_dir, "_qa_summary.csv")
    a_path = find_one(actual_dir, "_qa_summary.csv")
    if not e_path or not a_path:
        return ["sidecar CSV missing on one side"]

    def load(path: str) -> list[dict[str, str]]:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    e_rows, a_rows = load(e_path), load(a_path)
    if len(e_rows) != len(a_rows):
        problems.append(f"sidecar row count {len(e_rows)} vs {len(a_rows)}")
        return problems

    shared = [c for c in e_rows[0] if c in a_rows[0] and c not in SIDECAR_VOLATILE]
    diffs = 0
    for i, (e, a) in enumerate(zip(e_rows, a_rows, strict=True)):
        for col in shared:
            if e[col] != a[col]:
                diffs += 1
                if diffs <= 5:
                    problems.append(f"sidecar row {i} col {col}: {e[col]!r} vs {a[col]!r}")
    if diffs > 5:
        problems.append(f"...and {diffs - 5} further sidecar differences")

    print(f"  sidecar : {len(e_rows)} rows, {len(shared)} shared columns, {diffs} difference(s)")
    return problems


def mask(text: str) -> str:
    for pattern, replacement in HTML_MASKS:
        text = pattern.sub(replacement, text)
    return text


def compare_html(expected_dir: str, actual_dir: str) -> list[str]:
    e_path = find_one(expected_dir, ".html")
    a_path = find_one(actual_dir, ".html")
    if not e_path or not a_path:
        return ["HTML manifest missing on one side"]

    with open(e_path, encoding="utf-8") as f:
        e = mask(f.read())
    with open(a_path, encoding="utf-8") as f:
        a = mask(f.read())

    if e == a:
        print("  HTML    : identical after masking volatile fields")
        return []

    import difflib

    diff = [
        line
        for line in difflib.unified_diff(
            e.splitlines(), a.splitlines(), "expected", "actual", n=1, lineterm=""
        )
    ]
    print(f"  HTML    : {len(diff)} diff line(s) after masking")
    return ["HTML differs:", *diff[:40]]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    expected_dir, actual_dir = argv[1], argv[2]
    print(f"expected: {expected_dir}\nactual  : {actual_dir}\n")

    problems: list[str] = []
    problems += compare_data_csvs(expected_dir, actual_dir)
    problems += compare_sidecars(expected_dir, actual_dir)
    problems += compare_html(expected_dir, actual_dir)

    if problems:
        print("\nFAIL")
        for p in problems:
            print(f"  {p}")
        return 1
    print("\nPASS - outputs are equivalent to the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
