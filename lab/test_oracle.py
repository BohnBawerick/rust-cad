"""Check that the independent evaluator rejects plausible but wrong outputs."""
import copy,json,subprocess
from pathlib import Path
from oracle import analytic,verdict
ROOT=Path(__file__).resolve().parent
c=dict(id='control',group='extrude',op='extrude',a=dict(kind='box',origin=[0,0,0],size=[1,1,1]))
p=ROOT/'tmp/oracle-control.json';p.write_text(json.dumps(c))
out=json.loads(subprocess.check_output([str(ROOT/'target/baseline-probe'),str(p)]))
checks={}
checks['valid_cube']=verdict(c,out)['pass_']
empty=copy.deepcopy(out);empty.update(points=[],triangles=[],shells=[])
checks['reject_empty']=not verdict(c,empty)['pass_']
missing=copy.deepcopy(out);missing['triangles'].pop()
checks['reject_missing_face']=not verdict(c,missing)['pass_']
shift=copy.deepcopy(out);shift['points']=[[x+1,y,z] for x,y,z in shift['points']]
checks['reject_wrong_centroid']='centroid' in verdict(c,shift)['reasons']
reverse=copy.deepcopy(out);reverse['triangles']=[list(reversed(t)) for t in reverse['triangles']]
checks['reject_inward_volume']='volume' in verdict(c,reverse)['reasons']
bad=copy.deepcopy(out);bad['shells'][0]['edge_uses'][0][0]=1
checks['reject_open_brep']='manifold_edge_uses' in verdict(c,bad)['reasons']
for op,v,a in [('difference',1,6),('union',2,12),('intersection',0,0)]:
 q={**c,'op':op,'b':dict(kind='box',origin=[2,0,0],size=[1,1,1])};z=analytic(q)
 checks['disjoint_formula_'+op]=z['volume']==v and z['area']==a
print(json.dumps(checks,indent=2));assert all(checks.values())
