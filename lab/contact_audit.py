#!/usr/bin/env python3
"""Diagnostic after a search: judge the contact cases shell by shell and as one merged mesh.

Round 1 credited seven contact unions on a merged mesh whose shared edges were subdivided
differently on the two sides. This prints, for each case, the oracle-v2 verdict (one mesh per
shell) next to the merged-mesh closure that round 1 saw. Expects `target/final-probe`.
"""
import json,subprocess,tempfile
from pathlib import Path
from oracle import shell_closure,verdict
ROOT=Path(__file__).resolve().parent
CASES=['public-007','public-046','public-085','public-124','public-166','public-178','public-229','public-315']

def raw(case_id):
    with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
        folder=Path(folder);c=json.loads((ROOT/'corpus/public'/(case_id+'.json')).read_text())
        (folder/'case.json').write_text(json.dumps(c))
        cmd=['prlimit','--as=4294967296','--cpu=8','--','bwrap','--unshare-all','--die-with-parent','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(ROOT/'target/final-probe'),'/probe','--ro-bind',str(folder/'case.json'),'/case.json','--','/probe','/case.json']
        return c,json.loads(subprocess.check_output(cmd,timeout=8,env={'PATH':'/usr/bin:/bin','LC_ALL':'C','RAYON_NUM_THREADS':'1'}))

def main():
    out=ROOT/'contact-audit';out.mkdir(exist_ok=True)
    results=[]
    for case_id in CASES:
        c,geometry=raw(case_id);(out/(case_id+'-raw.json')).write_text(json.dumps(geometry)+'\n')
        v=verdict(c,geometry)
        merged=shell_closure(geometry['points'],geometry['triangles']) if geometry.get('status')=='ok' else None
        results.append(dict(id=case_id,relation=c.get('relation'),op=c['op'],pass_=v['pass_'],reasons=v['reasons'],shells=len(geometry.get('shells',[])),
            expected_bodies=v.get('expected',{}).get('bodies'),merged_mesh_closed_as_emitted=merged and merged['closed'],merged_mesh_closed_after_subdivision_merge=merged and merged['subdivision_closed']))
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
