#!/usr/bin/env python3
"""Frozen evaluator. Candidate code runs with one recipe and no corpus access."""
import argparse, concurrent.futures, hashlib, json, os, signal, subprocess, tempfile, time
from pathlib import Path
from oracle import analytic,mesh_metrics,verdict
ROOT=Path(__file__).resolve().parent
GROUPS=['boxes','cylinders','extrude','revolve','fillet','chamfer','holes','patterns','step']
TIMEOUT=8

def evaluate(path, binary=None):
    c=json.loads(Path(path).read_text());start=time.monotonic()
    # Only operation inputs enter the candidate's namespace, with no split or id.
    inputs={k:v for k,v in c.items() if k in ['op','a','b','radius','step','count','boolean_tol','mesh_tol','rotation']}
    with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as td:
        td=Path(td);(td/'case.json').write_text(json.dumps(inputs))
        cmd=['prlimit','--as=4294967296','--fsize=16777216','--cpu=8','--','bwrap','--unshare-all','--die-with-parent',
             '--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev',
             '--tmpfs','/tmp','--ro-bind',str(binary or ROOT/'target/debug/kernel-probe'),'/probe','--ro-bind',str(td/'case.json'),'/case.json']
        if c['op']=='step_import':cmd+=['--ro-bind',str(ROOT/'fixtures'/c['fixture']),'/fixture.stp']
        cmd+=['--','/probe','/case.json']
        try:
            with (td/'stdout').open('wb') as stdout,(td/'stderr').open('wb') as stderr:
                p=subprocess.Popen(cmd,stdout=stdout,stderr=stderr,start_new_session=True,env={'PATH':'/usr/bin:/bin','RAYON_NUM_THREADS':'1','LC_ALL':'C'})
                try:p.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();raise
            if p.returncode:out={'status':'crash','error':str(p.returncode)}
            else:out=json.loads((td/'stdout').read_text())
            if c['op']=='step_import' and out.get('status')=='ok':
                ok=out['input_solids']>0 and out['import_shells']>0 and out['import_triangles']>0
                result=dict(pass_=ok,reasons=[] if ok else ['empty_success'],actual=out)
            else:
                result=verdict(c,out)
                if c['op']=='step_roundtrip' and out.get('status')=='ok':
                    rt=out.get('roundtrip')
                    if not rt or not rt['lossless'] or not rt['triangles']:result['reasons'].append('roundtrip_loss')
                    else:
                        m=mesh_metrics(rt);expected=analytic(c)
                        if any(abs(m[k]-expected[k])>max(1e-8,expected[k]*1e-6) for k in ['volume','area']) or not m['mesh_closed']:result['reasons'].append('roundtrip_geometry')
                        result['roundtrip']=m
                    result['pass_']=not result['reasons']
        except subprocess.TimeoutExpired:result=dict(pass_=False,reasons=['timeout'])
        except Exception as e:result=dict(pass_=False,reasons=['evaluator_error:'+str(e)])
    result.update(id=c['id'],group=c['group'],op=c['op'],seconds=round(time.monotonic()-start,4))
    result['pass']=result.pop('pass_');return result

def score(rows):
    groups={g:dict(passed=sum(r['pass'] for r in rows if r['group']==g),total=sum(r['group']==g for r in rows)) for g in GROUPS}
    present=[v for v in groups.values() if v['total']]
    return dict(score=100*sum(v['passed']/v['total'] for v in present)/len(present),passed=sum(r['pass'] for r in rows),total=len(rows),groups=groups)

def suite(split,output,binary=None):
    paths=sorted((ROOT/'corpus'/split).glob('*.json'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(lambda p:evaluate(p,binary),paths))
    result=score(rows);result.update(split=split,rows=rows)
    Path(output).write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    c=s.add_parser('case');c.add_argument('path');c.add_argument('--binary',type=Path)
    c=s.add_parser('suite');c.add_argument('split',choices=['public','heldout']);c.add_argument('--out',required=True);c.add_argument('--binary',type=Path)
    a=p.parse_args()
    if a.command=='case':r=evaluate(a.path,a.binary);print(json.dumps(r));raise SystemExit(0 if r['pass'] else 1)
    else:r=suite(a.split,a.out,a.binary);print(json.dumps({k:v for k,v in r.items() if k!='rows'}))
