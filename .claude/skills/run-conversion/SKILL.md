---
name: run-conversion
description: Safe procedure for launching a real .ghg to RFlux CSV conversion run. Use when asked to run, launch, start, or re-run a conversion for a site/year, to process a station-year, or when checking whether a conversion is already in progress or how a finished run went.
---

# run-conversion

A conversion writes thousands of CSVs into `D:\L0_raw_sc26\{site}\{year}\ec\rflux_csv` and can
run for hours. Two runs writing the same tree corrupt each other's outputs and each other's QA
manifest. Follow these steps in order.

## 1. Verify no conversion is already running

```powershell
Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
  Select-Object ProcessId, CommandLine
```

Read the `CommandLine` of every hit. If any of them is `GHG2RFLUX.py` or `ghg2rflux`, **stop**:
report the site/year it is working on and the PID, and ask the user before doing anything else.
Also check the target output dir for recently-modified CSVs (`Get-ChildItem ... | Sort-Object
LastWriteTime -Descending | Select-Object -First 3`) — a run started outside this session still
shows up there.

**Never launch a run over a tree that another run is writing.** Not a different year of the same
site — a different *tree*. Two years of one site are independent output dirs and are fine
sequentially, but do not parallelise them without the user asking.

## 2. Always `--dry-run` first

```
ghg2rflux -site GL-ZaF -years 2024 --dry-run
```

This discovers files, resolves settings, and writes nothing. Read the per-folder table before
proceeding and check:

- **file counts** per folder are plausible (a half-hourly year is ~17 500 files);
- **hz** per folder, and **which layer it came from** (marker / CLI / config.ini / default) —
  a folder resolving to a CLI-supplied Hz when you expected a marker means the marker is missing
  or misplaced;
- **averaging_minutes** and **layout** per folder;
- **excluded folders** are the ones you intended to exclude and no others;
- the input root exists — 0 discovered files is a failure, not a quiet success.

If anything in that table is surprising, fix it with a marker file (see the `onboard-dataset`
skill) and re-run `--dry-run`. Do not proceed on a table you cannot explain.

## 3. The real run

```
ghg2rflux -site GL-ZaF -years 2024
```

Multi-year is a loop of independent single-year runs:
`ghg2rflux -site GL-ZaF -years 2020 2021 2022`. Long runs should go in the background so the
session stays usable; report progress from the tqdm output rather than polling the filesystem.

## 4. Where the outputs land

Everything goes into the **output data directory**, never into the repo:

- CSVs → `D:\L0_raw_sc26\{site}\{year}\ec\rflux_csv\`
- HTML QA manifest → the same directory, named `{site}_ghg2rluxcsv_report_{timestamp}.html`
  (the `ghg2rluxcsv` spelling is a deliberate, preserved typo)
- sidecar CSV → the same directory, alongside the manifest

If a `GL-*_ghg2rluxcsv_report_*.html` shows up in `git status`, the `--output-root` was wrong.
Investigate the run; do not stage the file.

## 5. Read the exit code

```powershell
echo $LASTEXITCODE
```

- **0** — every requested year completed and no Hz mismatch was detected.
- **nonzero** — *either* a year failed *or* a declared-vs-measured **Hz mismatch** was detected.
  The run still completed; that is by design, because the warning has to survive the terminal
  scrolling away. Open the HTML manifest and read the red banner at the top: it names the
  folder, the declared Hz, the measured Hz, the affected file count, and the concrete
  consequence (e.g. "1204 files padded with 18000 rows of -9999").

A nonzero exit is never something to shrug off — an Hz mismatch means part of the output is
very likely wrong. Report it to the user with the banner contents before anyone uses the data.

## 6. After the run

Summarise: discovered / converted / excluded / rejected / failed per year, the manifest path,
and the exit code. If any counts differ materially from the `--dry-run` plan, say so explicitly.
