#!/usr/bin/env node
/*
 * git_guard.js — the mechanical half of the `git-workflow` skill.
 *
 * The skill's §8 ("never, without an explicit instruction from the user") is a
 * procedure; this hook is its enforcement. This is a single-maintainer repo, so
 * server-side branch protection is effectively unavailable and every guard has to
 * be client-side.
 *
 * Runs as a PreToolUse hook on Bash. Reads the hook payload JSON on stdin
 * ({ tool_name, tool_input: { command } }) and either exits 0 silently (allow) or
 * prints a PreToolUse deny decision on stdout and exits 0.
 *
 * Every denial names the reason AND the correct alternative, so a block is
 * self-explaining rather than a wall.
 */

"use strict";

function readStdin() {
  const fs = require("fs");
  try {
    return fs.readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function deny(reason) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: reason,
      },
    })
  );
  process.exit(0);
}

function allow() {
  process.exit(0);
}

/*
 * Strip quoted strings so that a commit message like -m "no-verify note" or a
 * path literally containing "-A" cannot trigger a rule. Replaced with a single
 * space to preserve token boundaries.
 */
function stripQuoted(s) {
  return s
    .replace(/'(?:[^'\\]|\\.)*'/g, " ")
    .replace(/"(?:[^"\\]|\\.)*"/g, " ");
}

/* Split a compound command line into individually-checkable segments. */
function segments(cmd) {
  return cmd
    .split(/\n|;|&&|\|\||\||\$\(|`/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/* Tokenise a segment on whitespace, after quotes have been stripped. */
function tokens(seg) {
  return seg.split(/\s+/).filter(Boolean);
}

/* Does this segment invoke `<exe> <sub>` (allowing a leading env/path prefix)? */
function isCmd(tok, exe, sub) {
  const i = tok.findIndex((t) => t === exe || t.endsWith("/" + exe) || t.endsWith("\\" + exe));
  if (i === -1) return false;
  // The subcommand is the next token that is not a global flag.
  for (let j = i + 1; j < tok.length; j++) {
    if (tok[j].startsWith("-")) continue;
    return tok[j] === sub;
  }
  return false;
}

function has(tok, ...flags) {
  return tok.some((t) => flags.includes(t));
}

function checkSegment(seg) {
  const tok = tokens(seg);
  if (tok.length === 0) return;

  // ---- git add -A / . / --all -------------------------------------------
  if (isCmd(tok, "git", "add")) {
    if (has(tok, "-A", "--all", ".", "./", ":/")) {
      deny(
        "Blocked: bulk staging (`git add -A` / `git add .` / `git add --all`).\n" +
          "This repo sits next to gigabytes of .ghg archives and .csv outputs, and the QA " +
          "manifest is written into a data directory — bulk staging is how those get into git " +
          "permanently.\n" +
          "Instead: run `git status --short`, then `git add <explicit paths>`, then read " +
          "`git diff --cached` before committing. If something unwanted keeps appearing, fix " +
          ".gitignore rather than staging around it."
      );
    }
  }

  // ---- git commit --no-verify / -n --------------------------------------
  if (isCmd(tok, "git", "commit")) {
    if (has(tok, "--no-verify", "-n")) {
      deny(
        "Blocked: `git commit --no-verify`.\n" +
          "The pre-commit hooks (ruff, mypy, large-file guard) are the only client-side check " +
          "this single-maintainer repo has. A hook block is a correct answer, not an obstacle.\n" +
          "Instead: fix what the hook reported, or run `pre-commit run --all-files` to see it in " +
          "full, then commit normally."
      );
    }
  }

  // ---- git push ----------------------------------------------------------
  if (isCmd(tok, "git", "push")) {
    const forceWithLease = tok.some((t) => t.startsWith("--force-with-lease"));
    const hardForce = has(tok, "--force", "-f");
    const refs = tok.filter((t) => !t.startsWith("-"));
    const targetsMain = refs.some((t) => /(^|[:/])(main|master)$/.test(t));

    if (hardForce && !forceWithLease) {
      deny(
        "Blocked: `git push --force`.\n" +
          "An unconditional force-push can discard commits pushed from elsewhere, and on this " +
          "repo nothing server-side would stop it.\n" +
          "Instead: use `git push --force-with-lease` on your own non-main branch, and only when " +
          "the user has asked for a history rewrite. Once a PR is open, prefer a new `fix(...)` " +
          "commit over rewriting."
      );
    }
    if (forceWithLease && targetsMain) {
      deny(
        "Blocked: force-push targeting `main`.\n" +
          "`--force-with-lease` is permitted on your own topic branch only — never on main.\n" +
          "Instead: push the branch (`git push -u origin HEAD`) and open a PR with " +
          "`gh pr create --base main --fill`."
      );
    }
    if (targetsMain) {
      deny(
        "Blocked: `git push` targeting `main`/`master`.\n" +
          "Only docs-only (*.md) changes go directly to main, and those are pushed from main " +
          "itself without naming a refspec. Code, config.ini, pyproject.toml, .github/, .claude/ " +
          "and tests/ all go through a PR.\n" +
          "Instead: `git switch -c <type>/<slug>`, `git push -u origin HEAD`, " +
          "`gh pr create --base main --fill`, then `gh pr checks --watch`."
      );
    }
  }

  // ---- git reset --hard --------------------------------------------------
  if (isCmd(tok, "git", "reset") && has(tok, "--hard")) {
    deny(
      "Blocked: `git reset --hard`.\n" +
        "It destroys uncommitted work irreversibly, including edits another worker may have in " +
        "the tree right now.\n" +
        "Instead: `git stash push -- <paths>` to set changes aside, `git restore <path>` to " +
        "revert a specific file, or `git switch -c backup/<slug>` first if you want a way back."
    );
  }

  // ---- gh pr merge / close / reopen --------------------------------------
  if (isCmd(tok, "gh", "pr")) {
    const sub = tok[tok.findIndex((t) => t === "pr") + 1];
    if (sub === "merge") {
      deny(
        "Blocked: `gh pr merge`.\n" +
          "Merging is always the user's action. The git-workflow skill requires ending with a " +
          "recommendation block that states CI status and offers the exact command — never " +
          "running it.\n" +
          "Instead: report `gh pr checks --watch` results and hand the user the command, e.g. " +
          "`gh pr merge <n> --squash --delete-branch` (and warn if anything is stacked on this " +
          "branch, since --delete-branch silently auto-closes stacked PRs)."
      );
    }
    if (sub === "close" || sub === "reopen") {
      deny(
        "Blocked: `gh pr " +
          sub +
          "`.\n" +
          "Opening and closing PRs is the user's decision. Note also that a PR stranded by a " +
          "deleted base branch must NOT be reopened — the fix is a new PR from the same head " +
          "rebased onto main: `git rebase --onto origin/main <old-base> <head-branch>`.\n" +
          "Instead: explain the situation and give the user the command."
      );
    }
  }

  // ---- gh repo edit / delete ---------------------------------------------
  if (isCmd(tok, "gh", "repo")) {
    const sub = tok[tok.findIndex((t) => t === "repo") + 1];
    if (sub === "edit" || sub === "delete") {
      deny(
        "Blocked: `gh repo " +
          sub +
          "`.\n" +
          "Repository settings, visibility, secrets, and collaborators are never changed without " +
          "an explicit instruction from the user.\n" +
          "Instead: describe the change you think is needed and let the user run it, or make it " +
          "in the GitHub web UI."
      );
    }
  }
}

function main() {
  let payload;
  try {
    payload = JSON.parse(readStdin() || "{}");
  } catch {
    allow(); // Unparseable payload: do not block anything.
  }

  if (payload.tool_name !== "Bash") allow();

  const raw = (payload.tool_input && payload.tool_input.command) || "";
  if (typeof raw !== "string" || raw.trim() === "") allow();

  const cleaned = stripQuoted(raw);
  for (const seg of segments(cleaned)) checkSegment(seg);

  allow();
}

main();
