#!/usr/bin/env python3
"""Rejection controls for the evaluator.

The oracle must accept a valid cube and reject plausible but wrong outputs. The round 2
controls add the contact contract: the seven contact results round 1 credited, judged the way
round 1 judged them (one merged mesh), must fail; the same two-body geometry reported as two
closed shells must pass where two bodies are the right answer and fail where one body is.

Needs `target/baseline-probe` for the live cube. Everything else is synthetic or comes from
`research/2026-10-13-overnight/contact-audit/`.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

from oracle import analytic, expected_topology, mesh_metrics, verdict

ROOT = Path(__file__).resolve().parent
ROUND1 = ROOT.parent / 'research/2026-10-13-overnight/contact-audit'
checks = {}


def unit_cube(origin, order=None):
    """Twelve triangles of an axis-aligned unit cube, outward winding."""
    x, y, z = origin
    pts = [[x + i, y + j, z + k] for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for a, b, c, d in quads:
        tris += [[a, b, c], [a, c, d]]
    return pts, tris


def shell_record(points, triangles, point_base, triangle_base, edges=12, vertices=8):
    return dict(vertices=vertices, edges=edges, faces=6, face_cells=6, euler=2,
                edge_uses=[[2, 0]] * edges,
                points=[point_base, point_base + len(points)],
                triangles=[triangle_base, triangle_base + len(triangles)])


def two_cubes(origin_b, merged, subdivide=False):
    """Two unit cubes, reported as two shells or as one merged shell.

    With `subdivide`, the second cube splits the triangles along its edge from the origin
    corner in z at their midpoint, the way round 1's contact results subdivided one side of
    the shared edge, so the merged mesh is closed edge by edge as emitted.
    """
    pa, ta = unit_cube([0, 0, 0])
    pb, tb = unit_cube(origin_b)
    if subdivide:
        lo, hi = 0, 1  # cube corner indices of the z edge at the cube's origin corner
        mid = [(pb[lo][k] + pb[hi][k]) / 2 for k in range(3)]
        pb.append(mid)
        m = len(pb) - 1
        split = []
        for t in tb:
            if lo in t and hi in t:
                other = [i for i in t if i not in (lo, hi)][0]
                i, j = (t.index(lo), t.index(hi))
                # Keep winding: replace the lo-hi edge by lo-m-hi in the same order.
                first, second = (lo, hi) if (j - i) % 3 == 1 else (hi, lo)
                split += [[first, m, other], [m, second, other]]
            else:
                split.append(t)
        tb = split
    points = pa + pb
    triangles = ta + [[i + len(pa) for i in t] for t in tb]
    if merged:
        shells = [shell_record(points, triangles, 0, 0, edges=24, vertices=16)]
    else:
        shells = [shell_record(pa, ta, 0, 0), shell_record(pb, tb, len(pa), len(ta))]
    return dict(status='ok', consistent=True, shells=shells, points=points, triangles=triangles)


def recipe(relation, origin_b, size_b=(1, 1, 1)):
    return dict(id='control', group='boxes', op='union', relation=relation,
                a=dict(kind='box', origin=[0, 0, 0], size=[1, 1, 1]),
                b=dict(kind='box', origin=list(origin_b), size=list(size_b)))


# Live cube from the pinned kernel.
c = dict(id='control', group='extrude', op='extrude', a=dict(kind='box', origin=[0, 0, 0], size=[1, 1, 1]))
p = ROOT / 'tmp/oracle-control.json'
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps(c))
out = json.loads(subprocess.check_output([str(ROOT / 'target/baseline-probe'), str(p)]))
checks['valid_cube'] = verdict(c, out)['pass_']
empty = copy.deepcopy(out)
empty.update(points=[], triangles=[], shells=[])
checks['reject_empty'] = not verdict(c, empty)['pass_']
missing = copy.deepcopy(out)
missing['triangles'].pop()
missing['shells'][0]['triangles'][1] -= 1
checks['reject_missing_face'] = 'mesh_closure' in verdict(c, missing)['reasons']
shift = copy.deepcopy(out)
shift['points'] = [[x + 1, y, z] for x, y, z in shift['points']]
checks['reject_wrong_centroid'] = 'centroid' in verdict(c, shift)['reasons']
reverse = copy.deepcopy(out)
reverse['triangles'] = [list(reversed(t)) for t in reverse['triangles']]
checks['reject_inward_volume'] = 'volume' in verdict(c, reverse)['reasons']
bad = copy.deepcopy(out)
bad['shells'][0]['edge_uses'][0][0] = 1
checks['reject_open_brep'] = 'manifold_edge_uses' in verdict(c, bad)['reasons']
wrong_euler = copy.deepcopy(out)
wrong_euler['shells'][0]['euler'] = 0
checks['reject_wrong_euler'] = 'euler' in verdict(c, wrong_euler)['reasons']

# A zero-area triangle on a welded seam carries no surface and must not open the mesh,
# but it is counted.
seam = copy.deepcopy(out)
seam['points'].append(list(seam['points'][0]))
seam['triangles'].append([0, len(seam['points']) - 1, 1])
seam['shells'][0]['points'][1] += 1
seam['shells'][0]['triangles'][1] += 1
v = verdict(c, seam)
checks['accept_degenerate_seam_triangle'] = v['pass_'] and v['actual']['degenerate_triangles'] == 1

# A triangle subdivided differently on the two sides of an edge is still one closed surface.
split = copy.deepcopy(out)
pts, tris = split['points'], split['triangles']
a, b, c3 = tris.pop()
mid = [(pts[a][k] + pts[b][k]) / 2 for k in range(3)]
pts.append(mid)
m = len(pts) - 1
tris += [[a, m, c3], [m, b, c3]]
split['shells'][0]['points'][1] += 1
split['shells'][0]['triangles'][1] += 1
checks['accept_subdivided_edge'] = verdict(c, split)['pass_']

# Disjoint box formulas.
for op, vol, area in [('difference', 1, 6), ('union', 2, 12), ('intersection', 0, 0)]:
    q = {**c, 'op': op, 'b': dict(kind='box', origin=[2, 0, 0], size=[1, 1, 1])}
    z = analytic(q)
    checks['disjoint_formula_' + op] = z['volume'] == vol and z['area'] == area

# Expected body and cavity counts.
counts = {
    'disjoint': ((2, 0, 0), 'union', (2, 0)),
    'touch_face': ((1, 0, 0), 'union', (1, 0)),
    'touch_edge': ((1, 1, 0), 'union', (2, 0)),
    'touch_vertex': ((1, 1, 1), 'union', (2, 0)),
    'overlap': ((.4, 0, 0), 'union', (1, 0)),
    'contains_difference': ((.2, .2, .2), 'difference', (1, 1)),
    'contained_difference': ((-.2, -.2, -.2), 'difference', (0, 0)),
    'disjoint_intersection': ((2, 0, 0), 'intersection', (0, 0)),
}
for name, (origin_b, op, (bodies, cavities)) in counts.items():
    size_b = [.6] * 3 if name.startswith('contains') else [1.4] * 3 if name.startswith('contained') else [1, 1, 1]
    t = expected_topology({**recipe(name, origin_b, size_b), 'op': op})
    checks['topology_' + name] = (t['bodies'], t['cavities']) == (bodies, cavities)
cyl = dict(id='control', group='cylinders', op='union', a=dict(kind='cylinder', origin=[0, 0, 0], radius=1, height=1),
           b=dict(kind='cylinder', origin=[2, 0, 0], radius=1, height=1))
checks['topology_tangent_cylinders'] = expected_topology(cyl)['bodies'] == 2
checks['topology_hole_euler'] = expected_topology(dict(op='hole', a=dict(kind='box')))['euler'] == 0

# Contact contract on synthetic two-body meshes.
edge = recipe('touch_edge', (1, 1, 0))
checks['accept_two_closed_bodies_touching_at_edge'] = verdict(edge, two_cubes((1, 1, 0), merged=False))['pass_']
v = verdict(edge, two_cubes((1, 1, 0), merged=True))
checks['reject_bodies_merged_into_one_shell'] = {'mesh_closure', 'bodies'} <= set(v['reasons'])
checks['accept_two_bodies_one_side_subdivided'] = verdict(edge, two_cubes((1, 1, 0), merged=False, subdivide=True))['pass_']
v = verdict(edge, two_cubes((1, 1, 0), merged=True, subdivide=True))
checks['reject_merged_shell_closed_only_as_emitted'] = {'mesh_subdivided_contact', 'bodies'} <= set(v['reasons'])
face = recipe('touch_face', (1, 0, 0))
v = verdict(face, two_cubes((1, 0, 0), merged=False))
checks['reject_two_shells_where_one_body_expected'] = {'bodies', 'area'} <= set(v['reasons'])
disjoint = recipe('disjoint', (3, 0, 0))
checks['accept_two_disjoint_bodies'] = verdict(disjoint, two_cubes((3, 0, 0), merged=False))['pass_']
one_shell_disjoint = verdict(disjoint, two_cubes((3, 0, 0), merged=True))
checks['reject_disjoint_bodies_reported_as_one_shell'] = 'bodies' in one_shell_disjoint['reasons']

# Round 1 credited these seven contact unions on one merged mesh. Judged that way they fail.
# The eighth file is the disjoint-box control from the same audit and must still pass.
if ROUND1.exists():
    for case_id in ['public-007', 'public-046', 'public-085', 'public-124', 'public-166', 'public-178', 'public-229']:
        raw = json.loads((ROUND1 / f'{case_id}-raw.json').read_text())
        for shell in raw['shells']:
            shell.pop('points', None)
            shell.pop('triangles', None)
        case = json.loads((ROOT / 'corpus/public' / f'{case_id}.json').read_text())
        v = verdict(case, raw)
        checks[f'reject_round1_merged_{case_id}'] = not v['pass_'] and 'mesh_subdivided_contact' in v['reasons']
    raw = json.loads((ROUND1 / 'public-315-raw.json').read_text())
    case = json.loads((ROOT / 'corpus/public/public-315.json').read_text())
    checks['accept_round1_control_public-315'] = verdict(case, raw)['pass_']

print(json.dumps(checks, indent=2))
failed = [k for k, ok in checks.items() if not ok]
if failed:
    print('FAILED: ' + ', '.join(failed), file=sys.stderr)
    sys.exit(1)
