#!/usr/bin/env python3
"""Audit the retained source after the experiment window ends, with a fresh seed."""
import concurrent.futures,datetime,hashlib,json,random,secrets,shutil,subprocess,time
from pathlib import Path
import generate
from compile_command import command,ENV
from verify import evaluate,score
from check_identities import check
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'overnight'
OUT=ROOT/'final-audit'

def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def suite(paths,binary):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(lambda p:evaluate(p,binary),paths))
    return dict(score(rows),rows=rows)
def main():
    state=json.loads((RUN/'controller-state.json').read_text())
    if state['state']!='finished':raise SystemExit('final audit requires a finished controller')
    if OUT.exists():raise SystemExit('final-audit already exists; preserve the completed audit')
    OUT.mkdir()
    t=time.monotonic()
    clean_target=ROOT/'clean-target'
    if clean_target.exists():raise SystemExit('clean-target already exists; do not reuse build artifacts')
    clean_target.mkdir()
    cmd=command();cmd[cmd.index(str(ROOT/'target'))]=str(clean_target)
    with (OUT/'build.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=ENV,check=True,timeout=240)
    final=ROOT/'target/final-probe';shutil.copy2(clean_target/'debug/kernel-probe',final)
    seed=secrets.randbits(64);rng=random.Random(seed)
    generate.generate('sealed',seed,52)
    # Avoid the repeated fixed STEP recipes in the exploratory public/validation split.
    for p in sorted((ROOT/'corpus/sealed').glob('*.json')):
        c=json.loads(p.read_text())
        if c['op']=='step_roundtrip':
            c['a']=generate.box([rng.uniform(-20,20) for _ in range(3)],[rng.uniform(.3,8) for _ in range(3)])
            p.write_text(json.dumps(c,sort_keys=True)+'\n')
    # Scale and aspect-ratio challenges outside the initial seed's scale choices.
    for i in range(36):
        scale=[.01,.1,10.,100.][i%4]
        origin=[rng.uniform(-10,10)*scale for _ in range(3)]
        dims=[scale*rng.uniform(.3,4) for _ in range(3)]
        b=origin.copy();b[i%3]+=dims[i%3]+scale*rng.choice([.2,1,4])
        c=dict(id=f'sealed-extra-{i:03d}',group='boxes',op=['difference','union','intersection'][i%3],a=generate.box(origin,dims),b=generate.box(b,dims),rotation=rng.choice([.13,.51,1.2]),boolean_tol=.05,mesh_tol=.002,relation='fresh_scale_disjoint')
        (ROOT/'corpus/sealed'/(c['id']+'.json')).write_text(json.dumps(c,sort_keys=True)+'\n')
    cases=sorted((ROOT/'corpus/sealed').glob('*.json'))
    save(OUT/'seal-manifest.json',dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),seed=seed,total=len(cases),recipes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in cases},baseline_binary_sha256=hashlib.sha256((ROOT/'target/baseline-probe').read_bytes()).hexdigest(),final_binary_sha256=hashlib.sha256(final.read_bytes()).hexdigest()))
    baseline=suite(cases,ROOT/'target/baseline-probe');save(OUT/'sealed-baseline.json',baseline)
    candidate=suite(cases,final);save(OUT/'sealed-final.json',candidate)
    regressions=sorted({r['id'] for r in baseline['rows'] if r['pass']}-{r['id'] for r in candidate['rows'] if r['pass']})
    unsafe=lambda result:{r['id'] for r in result['rows'] if not r['pass'] and 'actual' in r}
    save(OUT/'sealed-comparison.json',dict(baseline_score=baseline['score'],final_score=candidate['score'],baseline_passed=baseline['passed'],final_passed=candidate['passed'],total=len(cases),regressions=regressions,new_incorrect_successes=sorted(unsafe(candidate)-unsafe(baseline)),seconds=time.monotonic()-t))
    for split in ['public','heldout']:
        verified=suite(sorted((ROOT/'corpus'/split).glob('*.json')),final);verified['split']=split
        save(OUT/(split+'.json'),verified)
        expected=json.loads((RUN/f'best-{split}.json').read_text())
        if {r['id']:r['pass'] for r in expected['rows']}!={r['id']:r['pass'] for r in verified['rows']}:raise RuntimeError('rebuilt retained source differs from kept verdicts')
        save(OUT/(split+'-identities.json'),check(verified))
        repeat=suite(sorted((ROOT/'corpus'/split).glob('*.json')),final);repeat['split']=split
        save(OUT/(split+'-repeat.json'),repeat)
        if {r['id']:(r['pass'],r['reasons']) for r in verified['rows']}!={r['id']:(r['pass'],r['reasons']) for r in repeat['rows']}:raise RuntimeError('fresh rebuild repeat changed verdicts or reasons')
    (OUT/'retained.patch').write_text(subprocess.check_output(['git','-C',str(ROOT/'kernel/source'),'diff','--','*.rs'],text=True))
    save(OUT/'complete.json',dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),seconds=time.monotonic()-t,verdict='fresh cases expose regressions; do not promote as hardened' if regressions or unsafe(candidate)-unsafe(baseline) else 'no regressions found in this fresh sample'))
    print((OUT/'sealed-comparison.json').read_text())
if __name__=='__main__':main()
