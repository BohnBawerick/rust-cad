# Evaluator changes

Every change to `oracle.py`, `verify.py` or the probe is an experiment of its own: it gets a
revision name in `evaluator.json`, an entry here with the reason, the controls that prove it,
and the baseline re-recorded under it. The loop and the CI gate refuse to compare results
across revisions. Review an evaluator change separately from any kernel change it travels
with, because a kernel patch judged by a changed evaluator proves nothing about the kernel.

## oracle-v1 (round 1, 12 to 13 October 2026)

The frozen evaluator of the first overnight run. One welded mesh per result, closure counted
by vertex pairs, Euler characteristic bounded above by two, no body count. Baseline on the
pinned kernel: public 108/318 (48.2012267044), held-out 33/102 (48.8562091503), combined
141/420 (48.8987047811).

## oracle-v2 (13 October 2026, before round 2)

### What changed

1. **One mesh per B-rep shell.** The probe reports a point and triangle range for every shell
   and the checker judges each shell's closure on its own. Shells may touch; they are never
   welded together.
2. **Closure is invariant to edge subdivision.** Within a shell, every edge is cut at the
   welded vertices lying on it and each resulting sub-edge must be used exactly twice with
   opposite winding. A T-junction is closed. Two bodies glued along an edge into one shell
   have four uses on every shared sub-edge and fail with `mesh_subdivided_contact`. Round 1's
   count by vertex pairs called that closed.
3. **Zero-area triangles are dropped before the count** and reported as
   `degenerate_triangles`. A triangle whose welded vertices coincide carries no surface. Every
   round 1 revolve case emitted eight of them at the two axis apexes and failed only there.
4. **Body and cavity counts.** Shells with positive signed volume are bodies, negative are
   cavities, and both must match the regularized result: a union across a shared face is one
   body, across an edge or vertex two bodies, a difference with B inside A has one cavity,
   tangent cylinders are two bodies. This is the contract for "separate bodies touching along
   a boundary versus one manifold solid": separate bodies are separate closed shells and the
   expected count says which answer is right.
5. **Euler characteristic is exact.** Two for every genus-zero shell, zero for the through
   hole. Round 1 accepted any even value up to two.
6. Mass properties, tolerances, timeouts and the STEP checks are unchanged. `analytic()`
   returns byte-identical values for all 770 recipes (`lab/tmp` comparison during the change).

### Controls

`python3 lab/test_oracle.py` passes 37 checks: the round 1 controls, the new topology
expectations, synthetic two-cube results reported as two shells (accepted where two bodies
are expected, rejected where one is) and as one merged shell (rejected), and the seven round 1
contact results from `research/2026-10-13-overnight/contact-audit/` judged as one merged mesh
(all rejected with `mesh_subdivided_contact`) with the disjoint control still accepted.

### Re-baseline on the unpatched kernel

| Split | oracle-v1 | oracle-v2 | Verdicts that changed |
| --- | ---: | ---: | --- |
| public | 108/318, 48.2012267044 | 122/318, 58.7425372457 | 12 revolve and 2 tangent-cylinder unions pass |
| held-out | 33/102, 48.8562091503 | 39/102, 60.6481481481 | 4 revolve, 1 edge-touching box union, 1 tangent-cylinder union pass |
| combined | 141/420, 48.8987047811 | 161/420, 59.7364373100 | no case that passed under v1 fails under v2 |

Per group under v2 (combined): boxes 57/208, cylinders 31/102, extrude 17/17, revolve 16/17,
fillet 0/18, chamfer 17/17, holes 0/17, patterns 17/17, step 6/7.

Two findings follow from the change and both are kernel facts, not evaluator leniency:

- **Revolve was never broken in the way round 1 reported.** 16 of 17 revolve results are
  closed, consistent, genus-zero shells with the right mass properties once the eight
  zero-area apex triangles are ignored. Round 1 could not have fixed them from the boolean
  file. The one remaining revolve failure (`public-289`) has a volume 22% too small and is a
  real defect.
- **The unpatched kernel already returns touching unions as two closed shells** for
  `heldout-007` (boxes touching along an edge) and three tangent-cylinder unions. Round 1
  failed them by welding the two shells together. The seven contact passes round 1 credited to
  attempts 58 and 59 were two closed shells each as well; what was wrong was the judgement,
  which saw one merged mesh, not the geometry.
