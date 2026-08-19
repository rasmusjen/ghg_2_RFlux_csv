# Contributing to ghg_2_RFlux_csv

This file explains *why* the procedure is what it is. The procedure itself lives in
`.claude/skills/git-workflow/SKILL.md` (for agents) and in the PR template (for humans);
this document is the rationale those two link back to.

## What this project actually is

`ghg2rflux` converts raw LI-COR `.ghg` archives into RFlux-ready `.csv` files and writes an
HTML QA manifest plus a sidecar CSV per station-year. The outputs are an input to published
eddy-covariance flux products. That single fact drives every rule below: a defect here does
not crash, it produces plausible-looking numbers that are wrong, and nobody finds out for a
year.

## Why data files never enter the repo

Inputs live under `D:\L0_raw`, outputs under `D:\L0_raw_sc26`. Neither is inside the working
tree, and neither may be written, moved, or deleted by a code change.

- Size: a single `.ghg` is ~1.5 MB and a converted `.csv` ~1.8 MB. A month is gigabytes.
  Git stores them forever, in every clone, and there is no clean way back out.
- Provenance: the raw archives are the instrument record. The repo is not their custodian and
  must not become a second, diverging copy of them.
- The specific hazard here: the QA manifest and its sidecar are written *into the output data
  directory*, not into the repo. So a mistyped `--output-root` can land them in the working
  tree. If `GL-*_ghg2rluxcsv_report_*.html` ever shows up in `git status`, that is not a file
  to stage — it is evidence that a run was misconfigured. Investigate the run.

`check-added-large-files` (512 kB) and the `git_guard.js` hook exist to make this mechanical,
because "remember not to" is not a control. `git add -A` and `git add .` are blocked outright:
they are the only realistic way a stray gigabyte gets committed by accident.

## Why the golden test gates `reader.py`, `pipeline.py`, `report.py`

The project's prime invariant is that **converted CSV bytes and HTML report fields do not
change unintentionally**. Those three modules are the only ones that can violate it:

- `reader.py` decides what rows come out of an archive — including the padding and the 90%
  rejection rule.
- `pipeline.py` decides which files are processed, how they are named, and what is skipped.
- `report.py` decides what the manifest and sidecar record about all of it.

Unit tests cannot protect this. The behaviour that matters is the exact byte content of files
produced from real, messy instrument data — truncated changeover files, mixed column layouts,
stray extracted directories. So there is a golden baseline: one real month (GL-ZaF 2024-06,
96 files → 79 converted + 17 excluded), captured from the pre-refactor script, diffed
byte-for-byte. The HTML is compared after masking the fields that legitimately vary per run
(timestamps, hashes, git short hash).

Because CI runners have no `D:\` drive, the golden test cannot run there. That is why any
commit touching those three files must state the golden result in its body, e.g.
`Golden: 79/79 CSVs byte-identical`. The commit message is the only place that evidence can
live. A commit in those files without that line is incomplete, not merely undocumented.

## Why markers beat CLI flags

Per-folder settings come from a `ghg2rflux.dir.ini` marker dropped into the folder it
describes. Resolution order, deepest wins, merged per key:

1. directory marker → 2. CLI flags → 3. `config.ini` → 4. built-in defaults.

The marker outranking the CLI is deliberate. A marker is a durable, reviewed statement about
that data, written once by someone who measured it and left a `note` saying why. A `-hz 10`
on the command line is a convenience default typed in a hurry. Inverting the order would mean
a habitual flag could silently override a period someone had already documented — exactly the
GL-Dsk 2020 failure mode this design exists to prevent (20 Hz until 2020-07-08, 10 Hz until
2020-09-24, 20 Hz after; processing it at one scalar Hz mass-pads thousands of files with
`-9999`).

Related rule: **the folder is always the unit.** If a folder turns out to contain internally
mixed data, split the folder — do not try to configure around it. The resolution model has no
concept of a date breakpoint and should not grow one.

## Why Conventional Commits

Scopes are the module names: `config`, `discovery`, `reader`, `pipeline`, `report`, `cli`,
`disturbance`, `timestamps`. Two reasons this is worth the small ceremony:

- **Bisecting an output regression.** When a downstream consumer reports that a year's CSVs
  changed, the question is always "which commit did that". `refactor(reader):` versus
  `docs(readme):` answers it at a glance, and the scope points straight at the golden-gated
  set above.
- **Reviewability.** One coherent change per commit, formatting churn never bundled with
  logic, and `pytest -m "not golden"` green at *every* commit — not just at the tip — so any
  commit is a valid bisect point.

## Working rules, in short

- Docs-only (`*.md`) changes go straight to `main`. Everything else — including `config.ini`,
  `pyproject.toml`, `.github/`, `.claude/`, and `tests/` — goes through a branch and a PR.
- Branch names: `<type>/<slug>`, type in `feat|fix|docs|chore|refactor|test|ci`.
- Never `--no-verify`. A hook block is a correct answer, not an obstacle to route around.
- Avoid stacked PRs. Merging a base branch with `--delete-branch` makes GitHub silently
  auto-close anything stacked on it, and nothing in the merge output tells you.
- This is a single-maintainer repo, so server-side branch protection is effectively
  unavailable. Every guard is client-side, which means the procedure *is* the enforcement.

## Before your first commit on a branch

```
pre-commit run --all-files
pytest -m "not golden"
```

And if you touched `reader.py`, `pipeline.py`, or `report.py`, also `pytest -m golden`.
