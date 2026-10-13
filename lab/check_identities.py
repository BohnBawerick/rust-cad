"""Cross-case boolean identities. This diagnostic does not change the score."""
import json,sys
from pathlib import Path
from oracle import analytic
ROOT=Path(__file__).resolve().parent

def check(result):
    recipes={}
    for row in result['rows']:
        if row['op'] not in ['difference','union','intersection']:continue
        case=json.loads((ROOT/'corpus'/result['split']/(row['id']+'.json')).read_text())
        # A common rigid rotation leaves volume unchanged.
        key=json.dumps([case['a'],case['b'],case['boolean_tol']],sort_keys=True)
        recipes.setdefault(key,{}).update({case['op']:(case,row)})
    rows=[]
    for ops in recipes.values():
        if set(ops)!=set(['difference','union','intersection']):continue
        ids=[r['id'] for c,r in ops.values()]
        if not all('actual' in r and 'volume' in r['actual'] for c,r in ops.values()):
            rows.append(dict(ids=ids,verdict='operation_failed'));continue
        c=ops['difference'][0];va=analytic({**c,'op':'primitive'})['volume'];vb=analytic({**c,'a':c['b'],'op':'primitive'})['volume']
        d,u,i=[ops[op][1]['actual']['volume'] for op in ['difference','union','intersection']]
        tol=max(1e-8,max(va,vb)*(.01 if c['group']=='cylinders' else 1e-6))
        rows.append(dict(ids=ids,verdict='pass' if abs(d+i-va)<=tol and abs(u+i-va-vb)<=tol else 'identity_failed',difference_plus_intersection_error=d+i-va,union_plus_intersection_error=u+i-va-vb))
    return dict(total=len(rows),passed=sum(r['verdict']=='pass' for r in rows),operation_failed=sum(r['verdict']=='operation_failed' for r in rows),identity_failed=sum(r['verdict']=='identity_failed' for r in rows),rows=rows)
if __name__=='__main__':print(json.dumps(check(json.loads(Path(sys.argv[1]).read_text())),indent=2))
