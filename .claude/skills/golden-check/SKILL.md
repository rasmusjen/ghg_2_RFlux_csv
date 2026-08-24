---
name: golden-check
description: Capture and verify the golden-output regression baseline for ghg2rflux. Use before and after any change to reader.py, pipeline.py, or report.py, when asked whether outputs are byte-identical, when a commit or PR needs a "Golden: N/N" line, or when the golden baseline needs recapturing after the scratch dir was cleared.
---

# golden-check

The project's prime invariant is that converted CSV bytes and HTML report fields do not change
unintentionally. The golden check is how that is proven. It runs one month of **real** data
through the code and diffs every output against a baseline captured from the pre-refactor
script.

It cannot run in CI — GitHub runners have no `D:\` drive — so it is marked
`@pytest.mark.golden` and deselected there (`pytest -m "not golden"`). Locally it is run with
`pytest -m golden`. Its result is stated in the commit body of any commit touching
`reader.py`, `pipeline.py`, or `report.py`:

```
Golden: 79/79 CSVs byte-identical
```

## The existing baseline

```
<scratchpad>\golden\
    L0_raw\GL-ZaF\2024\ec\raw\06\      96 real .ghg files (input tree)
    expected\GL-ZaF\2024\ec\rflux_csv\ expected outputs: 79 CSVs + manifest + sidecar
    baseline\                          the exact GHG2RFLUX.py + config.ini that produced them
```

Full path of `<scratchpad>` for this session:

```
C:\Users\au710242\AppData\Local\Temp\claude\C--Users-au710242-Code-Python-ghg-2-RFlux-csv\2c31f0bd-ae8d-4b7b-bda1-16c7d242c10d\scratchpad\golden
```

Provenance: GL-ZaF 2024-06, 96 real `.ghg` files → **79 `converted_full`** and **17
`excluded_disturbance`**. Those two numbers are the fingerprint of a correct run; if a candidate
run does not produce 79 + 17, stop and diff the manifest before diffing bytes.

**Scratch dirs are volatile.** That path lives under `Temp` and can vanish between sessions, so
the capture procedure below must stay repeatable and must never be the only copy of anything
that matters. If the baseline is missing, recapture it — do not skip the check.

## Capturing (or recapturing) a baseline

1. Verify no conversion is running (see the `run-conversion` skill, step 1).
2. Copy the input month **read-only** out of `D:\L0_raw`:
   `D:\L0_raw\GL-ZaF\2024\ec\raw\06\*.ghg` → `<scratch>\golden\L0_raw\GL-ZaF\2024\ec\raw\06\`.
   Copy only. Never write, move, or delete anything under `D:\L0_raw`.
3. Check out the reference code — the commit that produced the currently-published outputs —
   and keep a copy of `GHG2RFLUX.py` and `config.ini` in `<scratch>\golden\baseline\` so the
   baseline is self-describing.
4. Run that reference code with input root `<scratch>\golden\L0_raw` and output root
   `<scratch>\golden\expected`. Nothing may point at `D:\L0_raw_sc26`.
5. Record the counts (79 converted / 17 excluded) and the file total in the capture notes.

The baseline is data, not source: it lives in the scratch dir and **never enters git**.

## Diffing a candidate run

1. Run the candidate code over the same input tree into a fresh output dir, e.g.
   `<scratch>\golden\candidate`.
2. **File set first.** Compare the sorted relative paths of `expected` and `candidate`. A
   missing or extra CSV is a different (and more serious) failure than a changed byte, because
   it means the filename-ceiling or the rejection rule moved.
3. **CSVs byte-for-byte.** Compare raw bytes, not parsed frames — a parsed comparison hides
   line-ending, float-formatting, and column-order changes, which are exactly the regressions
   that break downstream RFlux. Report as `N/N byte-identical`.
4. **Sidecar CSV byte-for-byte** as well.
5. **HTML only after masking.** The manifest legitimately varies per run. Mask before
   comparing: run timestamps / generation date, the report hash, the git short hash, elapsed
   time, and any absolute paths that contain the output root. Everything else — counts, the
   configuration table, per-file reason strings — must match exactly.
6. On any mismatch, report the first differing file and the first differing line, plus the
   count of differing files. Do not summarise a mismatch as "minor".

## Reporting

State the result in the exact form used in commits and PRs:

- unchanged: `Golden: 79/79 CSVs byte-identical; sidecar identical; HTML identical after masking`
- intentionally changed: say which files changed, which fields, and why the new output is the
  correct one — then recapture the baseline as a separate, explicit step.

An unstated golden result on a change to `reader.py` / `pipeline.py` / `report.py` means the
change is incomplete.
