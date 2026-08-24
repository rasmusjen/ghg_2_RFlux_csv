# CLAUDE.md — ghg_2_RFlux_csv

## Purpose

`ghg2rflux` converts raw LI-COR `.ghg` archives into RFlux-ready `.csv` files. It walks
`D:\L0_raw\{site}\{year}\ec\raw` for `.ghg` archives, reads the `.data` member of each,
subsets and renames columns, rejects or pads against `expected_rows = 60 * averaging_minutes * hz`,
and writes one CSV per averaging period to `D:\L0_raw_sc26\{site}\{year}\ec\rflux_csv`.
Each run also writes an HTML QA manifest and a sidecar CSV into that same output directory.

## Prime invariant

**Converted CSV bytes and HTML report fields must not change unintentionally.** These outputs
feed published flux products; a silent change is worse than a crash.

Any PR touching `src/ghg2rflux/reader.py`, `pipeline.py`, or `report.py` **must state the
golden-test result** in the commit body and the PR description, e.g.
`Golden: 79/79 CSVs byte-identical` — or an explicit description of why the output changed on
purpose. CI cannot check this (no `D:\` on runners), so the message is the only evidence.

## Commands

```
ghg2rflux -site GL-ZaF -years 2024        # run a station-year
ghg2rflux -site GL-Dsk -years 2020 --dry-run
ghg2rflux scan -site GL-Dsk -years 2020   # read-only; proposes markers, never writes
pytest -m "not golden"                    # synthetic suite; must pass at every commit
pytest -m golden                          # real-data regression; local only
ruff check --fix . && ruff format .
mypy src
pre-commit run --all-files
```

## Data safety

- `D:\L0_raw` is **read-only source data**. `D:\L0_raw_sc26` is **output data**. Never write,
  move, or delete under either from a code edit, a script, or a shell command.
- No data ever enters the repo: no `.ghg`, no converted `.csv`, no run manifest `.html`.
- The QA manifest and sidecar are written *into the output data dir*. A stray
  `GL-*_ghg2rluxcsv_report_*.html` appearing in `git status` means a run was misconfigured —
  investigate it, do not stage it.

## Conventions

- Docs-only (`*.md`) changes: commit directly on `main`. Everything else — code, `config.ini`,
  `pyproject.toml`, `.github/`, `.claude/`, `tests/` — goes branch → commit → push → PR.
- Branches `<type>/<slug>`, types `feat|fix|docs|chore|refactor|test|ci`.
- Conventional Commits, scope from the module name (`config`, `discovery`, `reader`,
  `pipeline`, `report`, `cli`, `disturbance`, `timestamps`).
- Never `git add -A` / `git add .`; never `--no-verify`; never merge a PR yourself.
- Full procedure: `.claude/skills/git-workflow/SKILL.md`. Rationale: `CONTRIBUTING.md`.
- Single-maintainer repo, so branch protection is effectively unavailable — every guard is
  client-side and the procedure *is* the enforcement.

## Known quirks to preserve

These are deliberate. Do not "fix" them without an explicit decision from the user, and never
in the same commit as unrelated work.

- **`Anemometer Diagnostics` is overwritten with `-9999`** (`GHG2RFLUX.py:597`).
- **A `+100 ms` `DateOffset` is applied to timestamps** (`:591`).
- **The authoritative timestamp for a file is taken from its *last* row** (`:607`).
- **The output filename is ceilinged to the next averaging boundary** (`:162-168`), including
  the `23:45 → next day 00:00` rollover.
- **Padding rows set *every* column to `-9999`** (`:717`), including `TIMESTAMP`-adjacent
  fields. Intentional; preserved.
- **The report filename contains the typo `ghg2rluxcsv`** (not `ghg2rfluxcsv`). Kept
  deliberately — downstream tooling may match on it. Flag it to the user rather than silently
  fixing it.
- Plotly is loaded from a CDN, so manifests render blank offline. Left as-is; the report must
  stay identical.
- `expected_files_per_day = 48` is correct today (48 half-hours/day regardless of Hz) and
  becomes `1440 / averaging_minutes`. Do not "simplify" it back to a constant.

## Environment

Windows, venv at `.\venv\Scripts\python.exe` (Python 3.13). pandas 3.x / numpy 2.x are
installed while `pyproject.toml` pins `pandas>=2.0,<4.0`; `DateOffset(milliseconds=100)` and
`pd.date_range(...).to_pydatetime()` sit in areas pandas 3.0 changed, so treat a pandas
upgrade as a golden-test-gated change.
