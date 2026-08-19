---
name: git-workflow
description: The git and GitHub procedure for this repo. Use whenever staging, committing, branching, pushing, opening a PR, reacting to CI failures or review comments, or deciding what to do with an open PR — including the phrases "commit this", "push", "open a PR", "what should happen to this PR", "CI is red", or any request to merge, close, or reopen a pull request.
---

# git-workflow

The remote is `git@github.com:rasmusjen/ghg_2_RFlux_csv.git` — a personal repo with a **single
maintainer**. Server-side branch protection is therefore effectively unavailable: **every guard
here is client-side, which means the procedure *is* the enforcement.** Rationale for all of it
lives in `CONTRIBUTING.md`; this file is procedural.

## 1. Decide the path before touching anything

```
Only *.md files change?  ──yes──▶  commit directly on main
        │
        no
        ▼
  branch → commit → push → PR → (the user merges, after a recommendation)
```

`config.ini`, `pyproject.toml`, `.github/`, `.claude/`, `tests/`, and all code are **not** docs.
A change that touches one `.md` and one `.py` takes the branch path.

## 2. Branch

```
git switch main && git pull --ff-only
git switch -c <type>/<slug>        # type in feat|fix|docs|chore|refactor|test|ci
```

One coherent change per branch. If the work turns out to span both "package split" and "Hz
periods", say so and split it rather than widening the branch.

## 3. Stage deliberately

```
git status --short
git add <explicit paths>
git diff --cached          # read it before committing
```

**Never `git add -A`, `git add .`, or `git add --all`.** Stage explicit paths, always.

Refuse to stage the following, and fix `.gitignore` instead of staging around it:

- anything under `D:\` or `E:\` — source and output data are outside the repo and stay there
- `*.ghg` (~1.5 MB each), `*.csv` (~1.8 MB each), `*.html` run manifests
- `venv/`, `.venv/`, `__pycache__/`, `.mypy_cache/`
- `.env`, `config.local.ini`, `*.code-workspace`

**The specific hazard in this repo:** the QA manifest and its sidecar CSV are written **into the
output data directory**, and a mistyped `--output-root` can land them inside the working tree. A
stray `GL-*_ghg2rluxcsv_report_*.html` (note the deliberate `ghg2rluxcsv` typo) appearing in
`git status` means the run was misconfigured. Investigate the run — do not stage the file.

## 4. Commit

Conventional Commits, imperative, scope from the module names in the package layout: `config`,
`discovery`, `reader`, `pipeline`, `report`, `cli`, `disturbance`, `timestamps`.

```
<type>(<scope>): <what changed, imperative, no trailing period>

<why — especially what would silently break without this>
```

Rules:

- one coherent working change per commit;
- `pytest -m "not golden"` passes at **every** commit, not just at the tip;
- formatting churn is never bundled with logic;
- **never `git commit --no-verify` (or `-n`)**.

**Repo-specific rule with teeth:** any commit touching `reader.py`, `pipeline.py`, or
`report.py` **must state the golden-test result in its body** —

```
Golden: 79/79 CSVs byte-identical
```

— or an explicit description of why the output changed on purpose. A commit in those files
without that line is incomplete. This is the mechanical expression of the project's prime
invariant, and CI cannot check it because runners have no `D:\`.

## 5. Push and open the PR

```
git push -u origin HEAD
gh pr create --base main --fill
gh pr checks --watch
```

Fill the template properly — particularly **Risk**. This is scientific data processing: a wrong
Hz breakpoint, a half-hour rounding change, or an off-by-one in the padding threshold all pass a
green test run and silently corrupt years of flux data.

If CI fails, fix it on the same branch with a new commit (`fix(ci): ...`). Do not amend and
force-push once the PR is open unless the user asks.

## 6. Stacked PRs — avoid them

Branching B off an open, unmerged PR branch A is a footgun here: merging A with
`--delete-branch` makes GitHub **silently auto-close B**, because B's base ref is gone. Nothing
in the merge output flags it.

Default: wait for the base PR to merge, then branch from `main`. If stacking is genuinely
unavoidable:

1. name the base PR in the stacked PR's body;
2. put an explicit warning line in the **base** PR's recommendation block;
3. after any merge in a chain, check for open PRs whose base branch no longer exists —
   `gh pr list --json number,baseRefName` cross-checked against `git ls-remote --heads`.

The fix for a stranded PR is a **new PR** from the same head rebased onto current `main`:

```
git rebase --onto origin/main <old-base> <head-branch>
```

Never reopen the closed one.

The refactor in flight is naturally stack-shaped — package split, then Hz periods, then
multi-year CLI — so this section will be exercised. Prefer sequential merges over a stack.

## 7. Always end with a recommendation — required, and never merge yourself

Whenever a PR exists, has been updated, or the user asks about one, close the reply with a block
in this form:

```
PR #3 — refactor(pipeline): split GHG2RFLUX into ghg2rflux package   ·   CI: 6/6 green

Recommended: squash-merge and delete the branch.
  gh pr merge 3 --squash --delete-branch

Alternatives:
  - Merge commit, if you want the 4 move-then-fix commits kept separate for bisecting
    a future output regression:  gh pr merge 3 --merge --delete-branch
  - Hold: the Hz-period branch is stacked on this one — retarget or hold PR #4 before
    using --delete-branch here.

Watch for: golden test covers GL-ZaF 2024-06 only. GL-Dsk's flat 2021 layout (16904 files
in raw/) and GL-ZaH's date-range folders are untested by it — worth one dry-run each before
this is used for a real reprocessing campaign.
```

The recommendation must be **specific and reasoned**: CI status, what merging commits the
project to, and what still needs a human eye. A bare "looks good, merge it" is not a
recommendation. Merging is always the user's action — offer the exact command, never run it.

## 8. Never, without an explicit instruction from the user

- merge, close, reopen, or mark ready a PR;
- push non-documentation commits to `main`;
- force-push anything (`--force-with-lease` on your own branch only, never on `main`);
- `git reset --hard`, rebase a pushed branch, or rewrite history;
- change repository settings, visibility, secrets, or collaborators (`gh repo edit`,
  `gh repo delete`);
- `git commit --no-verify`.

A hook block is a correct answer, not an obstacle to route around. `.claude/hooks/git_guard.js`
is the mechanical half of this section; if it denies a command, the fix is the alternative it
names, not a workaround.

## 9. Before the first commit on any branch

```
pre-commit run --all-files
pytest -m "not golden"
```
