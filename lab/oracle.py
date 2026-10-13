"""Independent analytic values and integrals of emitted triangle coordinates.

Evaluator revision `oracle-v2`. `EVALUATOR-CHANGES.md` records what changed from the
round 1 oracle and why, with the re-baseline numbers.

A probe result is judged in three layers:

1. Mass properties. Volume, area and centroid of the emitted triangles against closed-form
   values. Boxes use an exact cell decomposition. Curved groups allow 1% error.
2. Each shell's mesh on its own. The probe reports one point and triangle range per B-rep
   shell. Zero-area triangles whose welded vertices coincide are dropped first: they carry no
   surface and only appear where a tessellator closes a seam at an apex. Every remaining edge
   must be used exactly twice with opposite winding, both as emitted and after collinear
   subdivisions of an edge are merged. The second count is what makes a result that glues two
   bodies along an edge into one shell fail: each shared sub-edge then has four uses.
3. Body count. Shells with positive signed volume are bodies, shells with negative signed
   volume are cavities. Both counts must match what the regularized operation produces.
   Two boxes that touch only along an edge or a vertex have a union with two bodies, each a
   closed manifold shell whose point sets touch. A union across a shared face is one body.
   A merged single shell, or the wrong number of bodies, fails.

Closure is judged on the merged sub-edges, so a mesh whose two sides subdivide an edge
differently (a T-junction) is closed. The as-emitted count is reported beside it: a shell
that is closed as emitted but open after merging is reported as `mesh_subdivided_contact`.
"""
import collections
import itertools
import math

WELD_DECIMALS = 8
LINE_DECIMALS = 6
BOOLEANS = ('difference', 'union', 'intersection')


def box_cells(c):
    """Cells of the box arrangement that belong to the regularized result."""
    a, b, op = c['a'], c['b'], c['op']
    p, d, q, e = a['origin'], a['size'], b['origin'], b['size']
    grid = [sorted({p[i], p[i] + d[i], q[i], q[i] + e[i]}) for i in range(3)]
    cells = {}
    for idx in itertools.product(*(range(len(g) - 1) for g in grid)):
        mid = [(grid[i][idx[i]] + grid[i][idx[i] + 1]) / 2 for i in range(3)]
        inside = lambda lo, sz: all(lo[i] < mid[i] < lo[i] + sz[i] for i in range(3))
        ia, ib = inside(p, d), inside(q, e)
        if {'difference': ia and not ib, 'union': ia or ib, 'intersection': ia and ib}[op]:
            cells[idx] = [grid[i][idx[i] + 1] - grid[i][idx[i]] for i in range(3)]
    return grid, cells


def neighbours(idx):
    for axis in range(3):
        for side in (-1, 1):
            nbr = list(idx)
            nbr[axis] += side
            yield tuple(nbr)


def components(cells):
    """Connected components of a cell set under face adjacency."""
    seen, count = set(), 0
    for start in cells:
        if start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            for nbr in neighbours(stack.pop()):
                if nbr in cells and nbr not in seen:
                    seen.add(nbr)
                    stack.append(nbr)
    return count


def analytic(c):
    a = c['a']
    op = c['op']
    p = a['origin']
    if a['kind'] == 'box':
        d = a['size']
        v = math.prod(d)
        area = 2 * sum(d[i] * d[j] for i, j in [(0, 1), (0, 2), (1, 2)])
        cen = [p[i] + d[i] / 2 for i in range(3)]
    else:
        r = a['radius']
        h = a['height']
        v = math.pi * r * r * h
        area = 2 * math.pi * r * (r + h)
        cen = [p[0], p[1], p[2] + h / 2]
    if op in BOOLEANS and a['kind'] == 'box':
        grid, cells = box_cells(c)
        v = 0.
        area = 0.
        moment = [0., 0., 0.]
        for idx, ds in cells.items():
            cv = math.prod(ds)
            v += cv
            for i in range(3):
                moment[i] += (grid[i][idx[i]] + grid[i][idx[i] + 1]) / 2 * cv
            for axis in range(3):
                for side in (-1, 1):
                    nbr = list(idx)
                    nbr[axis] += side
                    if tuple(nbr) not in cells:
                        area += math.prod(ds[j] for j in range(3) if j != axis)
        cen = [x / v for x in moment] if v else None
    elif op in BOOLEANS:
        b = c['b']
        q = b['origin']
        r = a['radius']
        h = a['height']
        dist = math.hypot(q[0] - p[0], q[1] - p[1])
        theta = math.acos(min(1, dist / (2 * r)))
        lens = 2 * r * r * theta - .5 * dist * math.sqrt(max(0, 4 * r * r - dist * dist))
        iv = lens * h
        ic = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2, p[2] + h / 2]
        bc = [q[0], q[1], q[2] + h / 2]
        if op == 'intersection':
            v = iv
            area = 2 * lens + 4 * r * theta * h
            cen = ic if v else None
        elif op == 'union':
            cen = [(v * cen[j] + v * bc[j] - iv * ic[j]) / (2 * v - iv) for j in range(3)]
            v = 2 * v - iv
            area = 2 * (2 * math.pi * r * r - lens) + (4 * math.pi * r - 4 * r * theta) * h
        else:
            cen = [(v * cen[j] - iv * ic[j]) / (v - iv) for j in range(3)] if v - iv > 1e-12 else None
            v -= iv
            area = 0 if v < 1e-12 else 2 * (math.pi * r * r - lens) + 2 * math.pi * r * h
    elif op in ['fillet', 'chamfer']:
        r = c['radius']
        h = d[2]
        if op == 'fillet':
            removed = (1 - math.pi / 4) * r * r * h
            area -= 2 * (1 - math.pi / 4) * r * r + (2 - math.pi / 2) * r * h
            rc = r * ((5 / 6 - math.pi / 4) / (1 - math.pi / 4))
        else:
            removed = .5 * r * r * h
            area -= r * r + (2 - math.sqrt(2)) * r * h
            rc = r / 3
        cen = [(v * cen[j] - removed * ([p[0] + rc, p[1] + rc, p[2] + h / 2][j])) / (v - removed) for j in range(3)]
        v -= removed
    elif op == 'hole':
        b = c['b']
        r = b['radius']
        removed = math.pi * r * r * d[2]
        cc = [*b['origin'][:2], p[2] + d[2] / 2]
        cen = [(v * cen[j] - removed * cc[j]) / (v - removed) for j in range(3)]
        v -= removed
        area += 2 * math.pi * r * d[2] - 2 * math.pi * r * r
    elif op == 'pattern':
        n = c['count']
        v *= n
        area *= n
        cen = [cen[j] + (n - 1) * c['step'][j] / 2 for j in range(3)]
    if cen is not None and c.get('rotation'):
        t = c['rotation']
        x, y, z = cen
        cen = [math.cos(t) * x - math.sin(t) * y, math.sin(t) * x + math.cos(t) * y, z]
    return dict(volume=v, area=area, centroid=cen)


def expected_topology(c):
    """Bodies, cavities and the Euler characteristic every shell must have."""
    op = c['op']
    a = c['a']
    bodies, cavities, euler = 1, 0, 2
    if op in BOOLEANS and a['kind'] == 'box':
        grid, cells = box_cells(c)
        bodies = components(cells)
        every = set(itertools.product(*(range(len(g) - 1) for g in grid)))
        complement = every - set(cells)
        boundary = {idx for idx in complement if any(idx[i] in (0, len(grid[i]) - 2) for i in range(3))}
        # Complement cells that reach the arrangement boundary are outside. Any other
        # complement component is enclosed by the result and so is a cavity.
        outside = set()
        stack = list(boundary)
        outside.update(boundary)
        while stack:
            for nbr in neighbours(stack.pop()):
                if nbr in complement and nbr not in outside:
                    outside.add(nbr)
                    stack.append(nbr)
        cavities = components(complement - outside)
    elif op in BOOLEANS:
        p, q, r = a['origin'], c['b']['origin'], a['radius']
        ratio = math.hypot(q[0] - p[0], q[1] - p[1]) / r
        if op == 'union':
            bodies = 1 if ratio < 2 else 2
        elif op == 'intersection':
            bodies = 1 if ratio < 2 else 0
        else:
            bodies = 0 if ratio == 0 else 1
    elif op == 'pattern':
        bodies = c['count']
    elif op == 'hole':
        euler = 0
    return dict(bodies=bodies, cavities=cavities, euler=euler)


def weld(points):
    """Map each point index to a welded vertex id, with the welded coordinates."""
    ids, index, welded = {}, [], []
    for p in points:
        key = tuple(round(x, WELD_DECIMALS) for x in p)
        if key not in ids:
            ids[key] = len(welded)
            welded.append(key)
        index.append(ids[key])
    return index, welded


def line_key(pa, pb):
    v = [pb[k] - pa[k] for k in range(3)]
    length = math.sqrt(sum(x * x for x in v))
    if not length:
        return None
    direction = [x / length for x in v]
    axis = max(range(3), key=lambda k: abs(direction[k]))
    if direction[axis] < 0:
        direction = [-x for x in direction]
    projection = sum(pa[k] * direction[k] for k in range(3))
    origin = [pa[k] - projection * direction[k] for k in range(3)]
    return tuple(round(x, LINE_DECIMALS) for x in direction + origin)


def shell_closure(points, triangles):
    """Closure of one shell's mesh, as emitted and with collinear subdivisions merged."""
    index, welded = weld(points)
    kept, degenerate = [], 0
    for f in triangles:
        if len(set(f)) != 3:
            raise ValueError('degenerate triangle indices')
        if len({index[i] for i in f}) != 3:
            degenerate += 1
            continue
        kept.append([index[i] for i in f])
    edges = collections.Counter()
    oriented = collections.Counter()
    lines = collections.defaultdict(set)
    for f in kept:
        for u, w in zip(f, f[1:] + f[:1]):
            edge = (min(u, w), max(u, w))
            edges[edge] += 1
            oriented[edge] += 1 if u < w else -1
            lines[line_key(welded[u], welded[w])].update((u, w))
    raw_closed = bool(kept) and all(n == 2 and oriented[e] == 0 for e, n in edges.items())
    segments = collections.Counter()
    winding = collections.Counter()
    subdivided = 0
    for (a, b), count in edges.items():
        pa, pb = welded[a], welded[b]
        v = [pb[k] - pa[k] for k in range(3)]
        length2 = sum(x * x for x in v)
        cuts = [(0., a), (1., b)]
        for i in lines[line_key(pa, pb)]:
            if i in (a, b):
                continue
            p = welded[i]
            t = sum((p[k] - pa[k]) * v[k] for k in range(3)) / length2
            if 1e-9 < t < 1 - 1e-9 and math.dist(p, [pa[k] + t * v[k] for k in range(3)]) < 2e-8:
                cuts.append((t, i))
        cuts.sort()
        subdivided += len(cuts) > 2
        for (_, u), (_, w) in zip(cuts, cuts[1:]):
            segment = (min(u, w), max(u, w))
            segments[segment] += count
            winding[segment] += oriented[(a, b)] * (1 if u < w else -1)
    bad = [dict(endpoints=[welded[a], welded[b]], uses=n, winding=winding[(a, b)])
           for (a, b), n in segments.items() if n != 2 or winding[(a, b)] != 0]
    return dict(closed=raw_closed, subdivision_closed=bool(kept) and not bad, subdivided_edges=subdivided,
                degenerate_triangles=degenerate, bad_segments=bad[:8], vertices=len(welded), triangles=len(kept))


def integrals(points, triangles):
    vol, area, m = 0., 0., [0., 0., 0.]
    ref = points[0] if points else [0., 0., 0.]
    cross = lambda u, v: [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    for f in triangles:
        a, b, c = [[points[i][j] - ref[j] for j in range(3)] for i in f]
        cr = cross(b, c)
        dv = sum(a[j] * cr[j] for j in range(3)) / 6
        vol += dv
        for j in range(3):
            m[j] += dv * (a[j] + b[j] + c[j]) / 4
        cr = cross([b[j] - a[j] for j in range(3)], [c[j] - a[j] for j in range(3)])
        area += math.sqrt(sum(x * x for x in cr)) / 2
    centroid = [m[j] / vol + ref[j] for j in range(3)] if abs(vol) > 1e-20 else None
    return vol, area, centroid


def shell_ranges(out):
    """Per-shell (points, triangles) ranges. A result without ranges is one shell."""
    shells = out.get('shells') or []
    if shells and all('points' in s and 'triangles' in s for s in shells):
        return [(tuple(s['points']), tuple(s['triangles'])) for s in shells]
    return [((0, len(out['points'])), (0, len(out['triangles'])))]


def mesh_metrics(out):
    pts, faces = out['points'], out['triangles']
    vol, area, centroid = integrals(pts, faces)
    shells = []
    for (p0, p1), (t0, t1) in shell_ranges(out):
        local = [[i - p0 for i in f] for f in faces[t0:t1]]
        closure = shell_closure(pts[p0:p1], local)
        signed, _, _ = integrals(pts[p0:p1], local)
        shells.append(dict(closure, signed_volume=signed))
    return dict(volume=vol, area=area, centroid=centroid,
                mesh_closed=all(s['subdivision_closed'] for s in shells),
                index_closed=all(s['closed'] for s in shells),
                subdivided_edges=sum(s['subdivided_edges'] for s in shells),
                degenerate_triangles=sum(s['degenerate_triangles'] for s in shells),
                bodies=sum(s['signed_volume'] > 1e-10 for s in shells),
                cavities=sum(s['signed_volume'] < -1e-10 for s in shells),
                mesh_vertices=sum(s['vertices'] for s in shells), triangles=len(faces), shells=shells)


def verdict(c, out):
    if out.get('status') != 'ok':
        return dict(pass_=False, reasons=[out.get('status', 'invalid_output') + ':' + out.get('error', '')])
    expected = analytic(c)
    topology = expected_topology(c)
    actual = mesh_metrics(out)
    reasons = []
    curved = c['group'] in ['cylinders', 'revolve', 'holes', 'fillet', 'chamfer']
    rel = .01 if curved else 1e-6
    for key in ['volume', 'area']:
        if not math.isfinite(actual[key]) or abs(actual[key] - expected[key]) > max(1e-8, abs(expected[key]) * rel):
            reasons.append(key)
    if expected['centroid'] is not None:
        if actual['centroid'] is None or any(not math.isfinite(v) for v in actual['centroid']):
            reasons.append('centroid')
        elif math.dist(actual['centroid'], expected['centroid']) > max(1e-7, abs(expected['volume']) ** (1 / 3) * rel):
            reasons.append('centroid')
    if expected['volume'] > 1e-10:
        if not out['shells'] or not out['triangles']:
            reasons.append('empty_geometry')
        else:
            if not out['consistent']:
                reasons.append('geometric_consistency')
            if not actual['mesh_closed']:
                # Closed edge by edge as emitted, but open once collinear subdivisions are
                # merged: the signature of two bodies glued along an edge into one shell.
                reasons.append('mesh_subdivided_contact' if actual['index_closed'] else 'mesh_closure')
            if actual['bodies'] != topology['bodies']:
                reasons.append('bodies')
            if actual['cavities'] != topology['cavities']:
                reasons.append('cavities')
            if any(abs(s['signed_volume']) <= 1e-10 for s in actual['shells']):
                reasons.append('degenerate_shell')
            for sh in out['shells']:
                if any(n != 2 or orient != 0 for n, orient in sh['edge_uses']):
                    reasons.append('manifold_edge_uses')
                if sh['euler'] != topology['euler']:
                    reasons.append('euler')
    elif out['shells'] or out['triangles']:
        reasons.append('expected_empty')
    expected.update(topology)
    return dict(pass_=not reasons, reasons=sorted(set(reasons)), expected=expected, actual=actual)
