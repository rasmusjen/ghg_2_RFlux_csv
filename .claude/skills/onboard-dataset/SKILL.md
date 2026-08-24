---
name: onboard-dataset
description: Procedure for onboarding a newly delivered legacy dataset or a newly discovered special case (mixed acquisition Hz, unusual folder layout, non-30-minute averaging, stray extracted directories). Use when asked to add a new site/year, to work out why a year looks odd, to propose or place ghg2rflux.dir.ini markers, or before the first conversion run of data nobody has processed before.
---

# onboard-dataset

New legacy data is assumed heterogeneous until measured. The goal of onboarding is to turn
detective work into a **review task**: `scan` measures, a human reads, markers record the
finding with a reason, and every later run is reproducible without anyone remembering anything.

**Never guess from folder names.** The layouts on disk include month folders `01..12`, flat
`raw/` dirs with 16 904 files, date+Hz folders, date-range folders, ad-hoc `2019_1`/`2019_2`,
nested `2023/01..12`, and stray extracted `data/`, `metadata/`, `status/` dirs. No naming
convention covers them, which is exactly why marker files exist.

## 1. Scan (read-only, never writes)

```
ghg2rflux scan -site GL-Dsk -years 2020
```

`scan` samples ~5 files per folder (first, last, middle, plus random) and reports per folder:
file count, **measured** Hz, detected column layout, measured file duration, and timestamp
range. It proposes markers and prints them; it never writes them.

Measured Hz comes from the **median sample interval** (`Seconds` + `Nanoseconds`), not the row
count. Files where the instrument stopped mid-interval are simply truncated (e.g. 2318 and 6658
rows) and a row-count check would wrongly flag them as Hz mismatches.

## 2. Read the proposed markers

Two findings mean the folder must be **split**, not configured around — the resolution model
has "the folder is always the unit" as an axiom and no concept of a date breakpoint:

- a folder whose sampled files do **not** share one Hz;
- a file duration that is not the folder's declared `averaging_minutes`.

Anything else is a normal marker.

## 3. Place markers by hand, each with a `note`

Write `ghg2rflux.dir.ini` into the folder it describes. It governs that folder and everything
below it, merged per key over any ancestor marker. Markers beat CLI flags.

```ini
; D:\L0_raw\GL-Dsk\2020\ec\raw\20200708_10Hz\ghg2rflux.dir.ini
[dir]
hz   = 10
note = LI-7200 switched to 10 Hz after the 2020-07-08 service visit

; all optional, all inherited if omitted:
; averaging_minutes = 30
; layout            = licor_std
; file_ID           = F10
; exclude           = true
```

The `note` is reproduced verbatim in the HTML manifest. Write **why**, not what — "hz = 10" is
already in the file above it. A note that only restates the setting is a wasted note; the point
is that in five years someone can tell a deliberate configuration from a mistake.

Set only the keys that actually differ. A marker that sets just `hz` inherits everything else.

## 4. Re-scan to confirm clean

```
ghg2rflux scan -site GL-Dsk -years 2020
```

Every folder should now resolve to its marker with no proposals outstanding and no split
warnings.

## 5. `--dry-run`, then the real run

```
ghg2rflux -site GL-Dsk -years 2020 --dry-run
ghg2rflux -site GL-Dsk -years 2020
```

In the dry-run table, check that each folder's Hz is sourced from the **marker** layer, not from
the CLI or config default. Then follow the `run-conversion` skill for the real run and the exit
code.

## Worked example — GL-Dsk 2020

The live case this design exists for. The year ran at 20 Hz until 2020-07-08, 10 Hz until
2020-09-24, then 20 Hz again, in three date+Hz folders:

| Folder | hz | files | averaging | span |
|---|---|---|---|---|
| `raw\20200101_20Hz` | 20 | 8917 | 30 min | 2020-01-01 .. 2020-07-08 |
| `raw\20200708_10Hz` | 10 | 3737 | 30 min | 2020-07-08 .. 2020-09-24 |
| `raw\20200924_20Hz` | 20 | 4734 | 30 min | 2020-09-24 .. 2020-12-31 |

Three markers, one per folder, `hz = 20 / 10 / 20`. No main-config entry, no CLI flag, no code
aware of the year.

Why it matters: processed at a single `hz = 20`, all 3737 of the 10 Hz files would be silently
padded with 18 000 rows of `-9999`; at `hz = 10` the 20 Hz files convert with no check that they
should have. Both produce plausible output. That is a data-correctness bug, not an ergonomics
gap.

Acceptance for this year: 20 Hz files yield 36 000-row CSVs with **zero** padded rows, 10 Hz
files 18 000 rows with zero padding; the two truncated changeover files (2318 and 6658 rows) are
rejected by the 90 % rule and **not** flagged as Hz mismatches; and re-running with `-hz 10`
leaves the 20 Hz folders unaffected because markers win.

## Excluding stray directories

`GL-ZaF/2021/06` contains extracted `data/`, `metadata/`, `status/` dirs alongside the `.ghg`
files. Drop `exclude = true` (with a `note`) into each: the tree is pruned from the walk and
reported as **deliberately excluded** rather than silently walked. That is the difference
between a documented decision and a coincidence.
