# Round 2 preparation, 13 October 2026

What this directory records: the first run's kept patches judged again under the round 2
evaluator and gates, and the decision on what round 2 starts from. The evaluator change
itself is recorded in [`lab/EVALUATOR-CHANGES.md`](../../lab/EVALUATOR-CHANGES.md).

## Re-validation of the round 1 patches

`lab/revalidate_round1.py` applied the 12 kept patches of the first run as cumulative
prefixes to a clean copy of `monstertruck-solid/src/transversal/classic/mod.rs`, built the probe,
ran both suites under `oracle-v2`, compared them with the frozen baseline the way the loop does,
and ran the round 2 gates for the crates the file affects (`monstertruck-solid` and
`monstertruck`): the kernel's own tests and `cargo check --release` with warnings denied.
`revalidation.json` is the full record; the per-prefix suite verdicts and gate logs were kept
under `lab/tmp/` and are not committed.

Baseline under `oracle-v2`: public 122/318, held-out 39/102, combined score 59.7364373100.

| Last patch | Patches | File lines | Public | Held-out | Combined score | Kernel tests failing | Release check | Passes all gates |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| 3 | 1 | 497 | 184/318 | 53/102 | 64.6844849051 | punched_cube | pass | no |
| 4 | 2 | 795 | 222/318 | 69/102 | 68.9014280926 | punched_cube | pass | no |
| 6 | 3 | 1174 | 260/318 | 81/102 | 71.5723682635 | punched_cube | pass | no |
| 9 | 4 | 1181 | 262/318 | 82/102 | 71.7326246738 | adjacent_cubes_or, punched_cube | pass | no |
| 10 | 5 | 1317 | 263/318 | 83/102 | 71.9504895975 | adjacent_cubes_or, punched_cube | pass | no |
| 20 | 6 | 1389 | 266/318 | 83/102 | 72.1107460078 | adjacent_cubes_or, punched_cube | pass | no |
| 27 | 7 | 2107 | 281/318 | 89/102 | 74.3983277072 | adjacent_cubes_or, punched_cube | pass | no |
| 30 | 8 | 2119 | 284/318 | 89/102 | 74.7251250928 | adjacent_cubes_or, punched_cube | pass | no |
| 43 | 9 | 2243 | 292/318 | 90/102 | 80.6074780339 | adjacent_cubes_or | pass | no |
| 46 | 10 | 2496 | 297/318 | 93/102 | 85.8362362039 | adjacent_cubes_or | fail | no |
| 58 | 11 | 2603 | 301/318 | 94/102 | 86.1033302210 | adjacent_cubes_or | fail | no |
| 59 | 12 | 2770 | 302/318 | 96/102 | 86.4301276066 | adjacent_cubes_or | fail | no |

No prefix regressed a case, produced a new incorrect success or a new runtime failure on
either split. Every prefix fails the kernel's own `monstertruck-solid` tests:

- `punched_cube` (`integrate/tests.rs`) fails from the first kept patch (attempt 3, the
  winding and complement change) through attempt 30, and passes again from attempt 43.
- `adjacent_cubes_or` fails from attempt 9 (planar arrangement before marching) to the end:
  30 faces where the test wants 12, as the round 1 audit found.
- The release check fails from attempt 46 on. The two unnecessary qualifications the audit
  reported at lines 2614 and 2620 were introduced by attempt 27 but only become errors once
  attempt 46 changes how those paths are used.

Under `oracle-v2` the full stack reaches 398/420 (86.4301276065) against the 381/420 round 1
reported under `oracle-v1`. The gain is the revolve group and the contact unions that the new
evaluator judges correctly (see the evaluator log); it is not new kernel behaviour.

## Decision: round 2 starts from the unpatched kernel

The option was to start from the longest prefix that passes every round 2 gate. There is no
such prefix: the kernel test gate rejects the stack from its first patch, and the gate is not
negotiable, because a boolean change that breaks the kernel's own boolean tests is not an
improvement whatever the corpus says. Dropping the later patches does not help, and editing the
patches to pass would make them new, unreviewed changes rather than re-validated ones.

So round 2 starts from monstertruck `d2ad1ed7` unpatched, with `lab/results/frozen-baseline-*.json`
re-recorded under `oracle-v2` on that source (public 122/318, held-out 39/102, combined 161/420,
score 59.7364373100). The ideas in the round 1 stack stay in the research record; the agent
cannot see it and must derive what it needs again under gates that would have stopped round 1
at attempt 3.

Two consequences for reading round 2's numbers:

- Any keep in the planar lane is already a stronger result than round 1's keeps, because it
  passed `punched_cube` and `adjacent_cubes_or`.
- The revolve lane has one visible failure, not thirteen. Round 1's revolve count measured the
  evaluator, not the kernel.

## Files

| File | What it holds |
| --- | --- |
| `revalidation.json` | Evaluator revision, gate packages, baseline numbers, and one record per prefix with suite counts, per-group passes, regressions and gate exits. |
| `smoke-run/` | The harness proof: the attempts of the short smoke run described in `ROUND2.md`, with prompts, diffs, logs and verdicts, paths redacted. |
