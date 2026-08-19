# ghg_2_RFlux_csv

Read raw LI-COR `.ghg` files and write `.csv` files formatted for RFlux, plus an HTML QA manifest
and a sidecar CSV for every run.

## What it does

For each station-year it walks the raw tree, opens every `.ghg` archive, extracts and renames the
sonic and gas-analyser columns, checks completeness against the expected row count, and writes one
CSV per averaging period named `{SITE}_EC_{YYYYMMDDHHMM}_{FILE_ID}.csv`. Files inside a declared
disturbance window are skipped, files missing more than 10% of their rows are rejected, and files
missing less than 10% are padded with `-9999`.

## Install

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Usage

```powershell
# one year
ghg2rflux -site GL-ZaF -years 2024

# several years, or a range
ghg2rflux -site GL-ZaF -years 2020 2021 2022
ghg2rflux -site GL-ZaF -years 2020-2022

# see what would happen, write nothing
ghg2rflux -site GL-Dsk -years 2020 --dry-run

# inspect a tree and get marker files proposed for it
ghg2rflux scan -site GL-Dsk -years 2020
```

Each year gets its own output directory, HTML manifest and sidecar CSV. The exit code is non-zero if
any year failed **or** if any acquisition-frequency mismatch was detected.

`python GHG2RFLUX.py` still works and behaves as it always did: it reads `config.ini` and converts
the single station-year named there.

### Options

| Flag | Meaning |
|---|---|
| `-site` / `--site` | Station ID. Defaults to `station_ID` in `config.ini`. |
| `-years` / `--years` | One or more years; ranges like `2020-2022` are expanded. |
| `-hz` / `--hz` | Acquisition frequency **for folders without a marker** — markers win. |
| `--averaging-minutes` | Averaging period. Default 30. |
| `--layout` | Column layout name, or `auto` (default) to detect it. |
| `--file-id` | Identifier used in output filenames. |
| `--input-root` / `--output-root` | Override the roots from `[paths]`. |
| `--config` | Path to `config.ini`. |
| `--dry-run` | Resolve settings and print the plan; write nothing. |
| `--overwrite` | Replace existing output files (default: skip them). |
| `--stop-on-error` | Abort the whole run when a year fails. |

## Configuration

```ini
[settings]
station_ID = GL-ZaF
year = 2024          ; or: years = 2020 2021 2022
file_ID = F10
hz = 10              ; default for folders without a marker

[paths]
input_root = D:\L0_raw
output_root = D:\L0_raw_sc26
```

Input is read from `{input_root}\{site}\{year}\ec\raw` and output written to
`{output_root}\{site}\{year}\ec\rflux_csv`.

### Per-folder settings (directory markers)

Raw trees are not uniform — some years use month folders `01`..`12`, some are flat, some split by
acquisition period. Discovery is depth-agnostic, so **if every file in a year shares the same
settings you need no configuration at all**, whatever the folder arrangement.

When one part of a year genuinely differs, drop a `ghg2rflux.dir.ini` into that folder. It governs
that folder and everything below it, merged per key over any marker above it:

```ini
; D:\L0_raw\GL-Dsk\2020\ec\raw\20200708_10Hz\ghg2rflux.dir.ini
[dir]
hz   = 10
note = switched to 10 Hz after the 2020-07-08 service visit

; all optional, all inherited when omitted:
; averaging_minutes = 30
; layout            = licor_std
; file_ID           = F10
; exclude           = true
```

Resolution order, highest first:

1. **directory marker** — nearest at or above the file
2. **CLI flags** — the default for folders with *no* marker
3. **`config.ini`**
4. **built-in defaults** (`hz=10`, `averaging_minutes=30`, `layout=auto`)

Markers deliberately beat CLI flags: a marker is a durable, reviewed fact about that data, while
`-hz` is a convenience default. That ordering is what makes `-hz` safe to pass across a multi-year
run — it can never silently override a period you already documented.

**The folder is always the unit.** A settings change always coincides with a folder boundary, so
there are no date ranges to configure. If a delivered dataset turns out to be internally mixed,
`scan` will say so, and the fix is to split the folder.

`exclude = true` prunes a subtree entirely — useful for scratch directories or archives that were
accidentally unpacked in place.

### Worked example: GL-Dsk 2020

That year ran at 20 Hz until 2020-07-08, 10 Hz until 2020-09-24, then 20 Hz again, and the folders
are named accordingly. Three markers describe it completely:

| folder | files | hz |
|---|---|---|
| `20200101_20Hz` | 8917 | 20 |
| `20200708_10Hz` | 3736 | 10 |
| `20200924_20Hz` | 4734 | 20 |

Without them, a single `hz` value is wrong for part of the year: at `-hz 20` every 10 Hz file is
rejected as >10% incomplete; at `-hz 10` the 20 Hz files convert with no check that they should have.

### Verification

The declared frequency is authoritative, but every file's actual sampling interval is measured from
its own clock. If a folder disagrees, the run still completes and reports:

- a red banner at the top of the HTML manifest, naming the folder and the consequence,
- a console summary,
- exit code 1.

### Disturbance windows

Create `disturbance.txt` in the year's `raw` directory:

```text
date_start,date_end,comment
202507150000,202507300900,exchange of SF2
```

Datetimes are `yyyymmddhhmm` and both ends are inclusive. Multiple rows are allowed and overlapping
windows are merged.

## Development

```powershell
pytest -m "not golden"    # fast synthetic suite
pytest -m golden          # regression against real data (needs the captured baseline)
ruff check --fix .
ruff format .
mypy src
```

The golden test asserts that converted CSVs stay **byte-identical** to a captured baseline. Any
change to `reader.py`, `pipeline.py` or `report.py` must state its golden result — see `CLAUDE.md`
and `CONTRIBUTING.md`.

## Troubleshooting

**PowerShell execution policy** — if activation is blocked:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Everything reported as failed on a re-run** — outputs are never overwritten by default, so a second
run over the same year finds its own previous output in place. Use `--overwrite` to replace it.

## License

Not yet declared.
