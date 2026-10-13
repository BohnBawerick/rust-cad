#!/usr/bin/env python3
"""Shrink a failing recipe to the simplest variant that still fails the same way.

Round 1 showed the agent raw failing recipes with six-digit random coordinates. A failure is
easier to reason about at the origin, unrotated, with round dimensions. Each step below is
applied in turn and kept only if the simplified recipe still fails with the same reasons under
the same probe, so every minimized recipe the agent sees is a real failure of the current
kernel, judged by the real evaluator.

Results are cached per (recipe, probe) so an unchanged kernel does not pay twice.

    python3 lab/minimize.py lab/corpus/public/public-315.json [--binary lab/target/debug/kernel-probe]
"""
import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path

from verify import evaluate

ROOT = Path(__file__).resolve().parent


def translate(recipe, offset):
    r = copy.deepcopy(recipe)
    for key in ('a', 'b'):
        if key in r:
            r[key]['origin'] = [r[key]['origin'][i] + offset[i] for i in range(3)]
    return r


def drop_rotation(recipe):
    if not recipe.get('rotation'):
        return None
    r = copy.deepcopy(recipe)
    r['rotation'] = 0
    return r


def move_to_origin(recipe):
    origin = recipe['a']['origin']
    if all(x == 0 for x in origin):
        return None
    return translate(recipe, [-x for x in origin])


def tidy(x, places=1):
    """Round to `places` decimals but never to zero."""
    rounded = round(x, places)
    return rounded if rounded else round(x, places + 2) or x


def round_dimensions(recipe):
    r = copy.deepcopy(recipe)
    a = r['a']
    b = r.get('b')
    if a['kind'] == 'box':
        a['size'] = [tidy(x) for x in a['size']]
        if b and b['kind'] == 'box':
            # Keep the exact relation of b to a on every axis: a shared plane stays shared,
            # a gap or overlap is rounded on its own.
            for i in range(3):
                old_a_end = recipe['a']['origin'][i] + recipe['a']['size'][i]
                size = tidy(b['size'][i]) if abs(b['size'][i] - recipe['a']['size'][i]) > 1e-12 else a['size'][i]
                if abs(b['origin'][i] - old_a_end) < 1e-12:
                    b['origin'][i] = a['origin'][i] + a['size'][i]
                elif abs(b['origin'][i] + b['size'][i] - recipe['a']['origin'][i]) < 1e-12:
                    b['origin'][i] = a['origin'][i] - size
                else:
                    b['origin'][i] = a['origin'][i] + tidy(b['origin'][i] - recipe['a']['origin'][i], 2)
                b['size'][i] = size
    else:
        ratio = None
        if b and b['kind'] == 'cylinder':
            ratio = (b['origin'][0] - a['origin'][0]) / a['radius']
        a['radius'] = tidy(a['radius'])
        a['height'] = tidy(a['height'])
        if b and b['kind'] == 'cylinder':
            b['radius'] = a['radius']
            b['height'] = a['height']
            b['origin'] = [a['origin'][0] + ratio * a['radius'], a['origin'][1], a['origin'][2]]
    if b and b['kind'] == 'cylinder' and a['kind'] == 'box':
        b['radius'] = tidy(b['radius'], 2)
        b['origin'] = [a['origin'][0] + a['size'][0] / 2, a['origin'][1] + a['size'][1] / 2, a['origin'][2] - .2]
        b['height'] = a['size'][2] + .4
    if 'radius' in r and isinstance(r['radius'], (int, float)):
        r['radius'] = tidy(r['radius'], 2)
    if 'step' in r:
        r['step'] = [tidy(x) for x in r['step']]
    return None if r == recipe else r


STEPS = [('drop_rotation', drop_rotation), ('move_to_origin', move_to_origin), ('round_dimensions', round_dimensions)]


def judge(recipe, binary):
    with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as td:
        path = Path(td) / 'case.json'
        path.write_text(json.dumps(recipe))
        return evaluate(path, binary)


def same_failure(before, after):
    return not after['pass'] and after['reasons'] == before['reasons']


def summarize(result):
    """What the agent needs from a verdict, without the full mesh."""
    out = {k: result.get(k) for k in ('pass', 'reasons')}
    if 'expected' in result:
        out['expected'] = result['expected']
    if 'actual' in result:
        a = result['actual']
        out['actual'] = {k: a.get(k) for k in ('volume', 'area', 'centroid', 'mesh_closed', 'index_closed',
                                               'degenerate_triangles', 'bodies', 'cavities', 'triangles')}
        out['actual']['shells'] = [{k: s.get(k) for k in ('signed_volume', 'closed', 'subdivision_closed',
                                                           'degenerate_triangles', 'bad_segments')} for s in a.get('shells', [])]
    return out


def minimize(recipe, binary, cache=None):
    """Return the minimized recipe, the steps that held and the summarized verdict."""
    key = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode() + Path(binary).read_bytes()).hexdigest()[:24]
    if cache:
        cached = Path(cache) / f'{key}.json'
        if cached.exists():
            return json.loads(cached.read_text())
    original = judge(recipe, binary)
    current, applied = recipe, []
    if not original['pass']:
        for name, step in STEPS:
            candidate = step(current)
            if candidate is None:
                continue
            if same_failure(original, judge(candidate, binary)):
                current, applied = candidate, applied + [name]
    final = judge(current, binary) if applied else original
    record = dict(original_id=recipe.get('id'), group=recipe.get('group'), op=recipe.get('op'),
                  recipe={k: v for k, v in current.items() if k not in ('id', 'group')},
                  steps=applied, result=summarize(final))
    if cache:
        Path(cache).mkdir(parents=True, exist_ok=True)
        (Path(cache) / f'{key}.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('recipe', type=Path)
    p.add_argument('--binary', type=Path, default=ROOT / 'target/debug/kernel-probe')
    a = p.parse_args()
    record = minimize(json.loads(a.recipe.read_text()), a.binary)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
