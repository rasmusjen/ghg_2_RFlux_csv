# What and why

<!-- What changed, and what would silently break without it. Link the issue or the
     dataset/campaign that prompted it. One paragraph is usually enough. -->

# Risk

<!-- This is scientific data processing. A wrong Hz, a changed rounding rule, or an
     off-by-one in the padding threshold all pass a green test run and silently
     corrupt published flux data. State plainly:
       - Which outputs can change as a result of this PR (CSV bytes? report fields?
         file names? row counts? padded-row counts?)
       - Which sites/years/layouts were actually exercised, and which were not.
       - What a reviewer should look at hardest.
     If the answer is genuinely "no output can change", say so and say why. -->

# Verification

- [ ] `pytest -m "not golden"` passes locally
- [ ] `ruff check .` and `ruff format --check .` clean
- [ ] `mypy src` clean
- [ ] Golden regression test run locally against real data — outputs unchanged (or the change is intentional and described above)
- [ ] `--dry-run` inspected for any layout this PR affects (month folders / flat / date+Hz / date-range / nested)
- [ ] No data files, manifests, or paths under `D:\` or `E:\` are staged in this PR
