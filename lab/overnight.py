#!/usr/bin/env python3
"""Controller-owned evaluator, bounded proposals, append-only experiment records."""
import datetime, difflib, fcntl, hashlib, json, os, signal, subprocess, time, traceback
from pathlib import Path
from agent_command import ROOT, command, ENV
from verify import score
from compile_command import command as compile_command, ENV as COMPILE_ENV
KERNEL = ROOT/'kernel/source'
RUN = ROOT/'overnight'
RUN.mkdir(exist_ok=True)
CONFIG = ROOT/'loop-config.json'
EVAL_ENV = os.environ.copy()
EVAL_ENV.update(CARGO_HOME=str(ROOT/'cache/cargo'),CARGO_TARGET_DIR=str(ROOT/'target'),TMPDIR=str(ROOT/'tmp'),XDG_CACHE_HOME=str(ROOT/'cache'),CARGO_BUILD_JOBS='4',RAYON_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
CHILD = None
CURRENT = None
RESTORE = {}

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(data):return hashlib.sha256(data).hexdigest()
def write_json(path,obj):
    temp=path.with_suffix('.new');temp.write_text(json.dumps(obj,indent=2)+'\n');temp.replace(path)
def append(path,obj):
    with path.open('a') as f:f.write(json.dumps(obj)+'\n');f.flush();os.fsync(f.fileno())
def status(state,message):
    hook=os.environ.get('RESEARCH_STATUS_HOOK')
    if hook:subprocess.run(['python3',hook,state,message],check=True)
def stopped(signum,frame):
    global CHILD
    if CHILD and CHILD.poll() is None:
        try:os.killpg(CHILD.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        CHILD.wait()
    for path,data in RESTORE.items():path.write_bytes(data)
    write_json(RUN/'controller-state.json',dict(state='stopped',at=now(),attempt=CURRENT,signal=signum))
    raise SystemExit(128+signum)
for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,stopped)
def run(cmd,log,budget,env,deadline):
    global CHILD
    limit=min(budget,max(0,deadline-time.time()))
    if limit<1:return 124,0
    start=time.monotonic()
    with log.open('wb') as out:
        CHILD=subprocess.Popen(cmd,stdout=out,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        write_json(RUN/'child.json',dict(pid=CHILD.pid,at=now(),log=str(log.relative_to(ROOT)),budget=limit))
        try:rc=CHILD.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(CHILD.pid,signal.SIGKILL);CHILD.wait();rc=124
    CHILD=None
    return rc,round(time.monotonic()-start,3)
def fingerprint(editable):
    paths=[ROOT/p for p in ['oracle.py','verify.py','generate.py','agent_command.py','compile_command.py','overnight.py','probe/Cargo.toml','probe/Cargo.lock']]
    paths += list((ROOT/'probe/src').glob('*.rs'))+list((ROOT/'corpus').rglob('*.json'))+list((ROOT/'fixtures').glob('*'))
    paths += [KERNEL/p for p in subprocess.check_output(['git','-C',str(KERNEL),'ls-files'],text=True).splitlines() if p not in editable and (KERNEL/p).is_file()]
    return {str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted(paths)}
def regress(old,new):return sorted({r['id'] for r in old['rows'] if r['pass']}-{r['id'] for r in new['rows'] if r['pass']})
def unsafe(rows):return {r['id'] for r in rows if not r['pass'] and 'actual' in r}
def runtime_failures(rows):return {r['id'] for r in rows if any(s=='timeout' or s.startswith(('crash:','panic:','evaluator_error:')) for s in r['reasons'])}
def pass_map(result):return {r['id']:r['pass'] for r in result['rows']}
def suite(directory,split,suffix,cfg,deadline):
    path=directory/f'{suffix}-{split}.json'
    rc,seconds=run(['python3',str(ROOT/'verify.py'),'suite',split,'--out',str(path)],directory/f'{suffix}-{split}.log',cfg['suite_seconds'],EVAL_ENV,deadline)
    if rc:return None,dict(exit=rc,seconds=seconds)
    return json.loads(path.read_text()),dict(exit=rc,seconds=seconds)
def compact_feedback(public,history,attempt):
    failed=[r for r in public['rows'] if not r['pass'] and r['group'] in ['boxes','cylinders']]
    selected=failed[(attempt*7)%len(failed):][:8] if failed else []
    details=[]
    for row in selected:
        c=json.loads((ROOT/'corpus/public'/f"{row['id']}.json").read_text())
        details.append(dict(case=c,result={k:v for k,v in row.items() if k!='seconds'}))
    return dict(score=public['score'],passed=public['passed'],total=public['total'],groups=public['groups'],selected_visible_failures=details,history=history[-8:])
def prompt(cfg,attempt):
    allowed=', '.join('/work/kernel/'+p for p in cfg['editable'])
    return f'''You are the experimental coding subject in a bounded kernel repair loop, attempt {attempt}. Work yourself; do not delegate or contact anyone.
Task: {cfg['focus']}
Definition: boolean difference A minus B preserves A when solids are disjoint, is empty when A is contained in B, and preserves cavity orientation when B is contained in A. Union and intersection must keep their usual regularized solid meanings. Empty valid outputs differ from failed operations. Shapes can have multiple oriented shells.
Editable files: {allowed}. Change no other source, tests, dependency files, or configuration. Do not commit. The controller owns evaluation and keep/revert.
Start by reading /work/scratch/feedback.json. The last rejected patch, when available, is /work/scratch/last-candidate.patch and can be revised rather than rebuilt from memory. It contains visible results, selected visible recipes, and recent experiment summaries. The full corpus, evaluator, hidden cases and host home are absent. Hidden cases veto regressions. Do not seek them. No web or network tool calls. Use local source and derive the algorithm independently.
Initial reproducer: difference of A=[0,1]^3 and B=[2,3]x[0,1]x[0,1] at tolerance .05 returns empty instead of A, volume 1, area 6, centroid [.5,.5,.5].
Does not count: blanket refusal or unchanged inputs to hide failed operations; rejecting an independently detected invalid result is legitimate but remains a failing case; geometry-specific answer tables; case-id checks; changing tolerances, tests, output metrics or the evaluator; an explanation without a source patch. A bounding-box shortcut based only on vertices is not a proof that curved surfaces are separated. Do not silently replace exact B-rep with a mesh approximation.
Verification: after you finish, the controller compiles and runs independent volume, area, centroid, topology and mesh-closure checks. One scalar is maximized: the mean pass rate over nine operation groups. A keep additionally requires no previously passing case to fail, no new incorrect successes, no new timeouts or crashes, and identical repeated pass/fail results. The evaluator and oracle are immutable to you. Kernel geometric consistency is only a supplemental check.
Write one coherent implementation hypothesis. Read nearby source as needed but do not build here; build caches and the harness are intentionally absent. If a previous patch failed compilation, use the error feedback to repair that hypothesis. If there was no gain, choose a materially different hypothesis instead of repeating an unchanged patch.
Budget: {cfg['agent_seconds']} seconds, at most 30 tool calls, roughly 16000 tokens. Use the budget for a concrete artifact. If near budget or outside scope, write partial findings to /work/scratch/partial.txt and return a short summary. Redirect output longer than 2000 tokens to scratch and read selectively.
Return after writing the candidate, with at most 300 words covering modified files, mathematical reason, expected scope and unresolved risks. Never claim tests passed here. The controller will decide retention.'''

def main():
    global CURRENT,RESTORE
    lock=(RUN/'controller.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    (RUN/'controller.pid').write_text(str(os.getpid())+'\n')
    records=[]
    if (RUN/'experiments.jsonl').exists():
        if os.environ.get('RESEARCH_RESUME')!='1':raise RuntimeError('existing run: set RESEARCH_RESUME=1 for explicit recovery')
        records=[json.loads(line) for line in (RUN/'experiments.jsonl').read_text().splitlines()]
    public=json.loads((RUN/'best-public.json' if records else ROOT/'results/frozen-baseline-public.json').read_text())
    hidden=json.loads((RUN/'best-heldout.json' if records else ROOT/'results/frozen-baseline-heldout.json').read_text())
    write_json(RUN/'best-public.json',public);write_json(RUN/'best-heldout.json',hidden)
    history=json.loads((RUN/'public-history.json').read_text()) if (RUN/'public-history.json').exists() else []
    keeps=sum(r['kept'] for r in records);last_revision=records[-1]['revision'] if records else None;last_hour=time.time();failures=0
    start_attempt=records[-1]['attempt']+1 if records else 1
    for i in range(start_attempt,10000):
        CURRENT=i;cfg=json.loads(CONFIG.read_text());deadline=datetime.datetime.fromisoformat(cfg['deadline_utc'].replace('Z','+00:00')).timestamp()
        if time.time()>=deadline or i>cfg['max_attempts']:break
        while (RUN/'pause-between-rounds').exists() and time.time()<deadline:
            write_json(RUN/'controller-state.json',dict(state='between_rounds',at=now(),attempt=i));time.sleep(5)
        if time.time()>=deadline:break
        directory=RUN/f'attempt-{i:03d}';directory.mkdir()
        allowed=cfg['editable']
        for path in allowed:
            if '..' in Path(path).parts or Path(path).is_absolute() or not path.endswith('.rs') or '/tests/' in path:raise ValueError('invalid editable path')
        frozen=fingerprint(allowed);write_json(directory/'frozen-manifest.json',frozen);write_json(directory/'config.json',cfg)
        if cfg['revision']!=last_revision:
            append(RUN/'design-changes.jsonl',dict(at=now(),revision=cfg['revision'],config=cfg));last_revision=cfg['revision']
        RESTORE={KERNEL/p:(KERNEL/p).read_bytes() for p in allowed}
        write_json(ROOT/'agent-scratch/feedback.json',compact_feedback(public,history,i))
        text=prompt(cfg,i);(directory/'prompt.txt').write_text(text)
        write_json(RUN/'controller-state.json',dict(state='proposing',at=now(),attempt=i,keeps=keeps))
        summary_path=ROOT/'agent-scratch/last-message.txt'
        if summary_path.exists():summary_path.unlink()
        started=now();rc,seconds=run(command(text,allowed),directory/'agent.jsonl',cfg['agent_seconds'],ENV,deadline)
        summary_path=ROOT/'agent-scratch/last-message.txt'
        summary=summary_path.read_text()[:5000] if summary_path.exists() else ''
        (directory/'agent-summary.txt').write_text(summary)
        after={p:p.read_bytes() for p in RESTORE}
        diffs=[''.join(difflib.unified_diff(RESTORE[p].decode().splitlines(True),after[p].decode().splitlines(True),fromfile='a/'+str(p.relative_to(KERNEL)),tofile='b/'+str(p.relative_to(KERNEL)))) for p in RESTORE]
        diff=''.join(diffs);(directory/'candidate.patch').write_text(diff)
        record=dict(attempt=i,started=started,agent_exit=rc,agent_seconds=seconds,revision=cfg['revision'],changed=bool(diff),patch_sha256=digest(diff.encode()),kept=False,heldout_result='not_evaluated')
        if fingerprint(allowed)!=frozen:raise RuntimeError('protected file changed')
        newpub=newhid=None
        if rc or not diff:record['reason']='agent_timeout_or_failure' if rc else 'no_change'
        else:
            write_json(RUN/'controller-state.json',dict(state='compiling',at=now(),attempt=i,keeps=keeps))
            build_rc,build_s=run(compile_command(),directory/'build.log',cfg['compile_seconds'],COMPILE_ENV,deadline)
            record.update(build_exit=build_rc,build_seconds=build_s)
            if build_rc:record['reason']='build_failed'
            else:
                write_json(RUN/'controller-state.json',dict(state='evaluating',at=now(),attempt=i,keeps=keeps))
                newpub,ep=suite(directory,'public','first',cfg,deadline);newhid,eh=suite(directory,'heldout','first',cfg,deadline)
                record.update(public_run=ep,hidden_run=eh)
                if newpub is None or newhid is None:record['reason']='evaluation_failed'
                else:
                    rp=regress(public,newpub);rh=regress(hidden,newhid)
                    nu=sorted(unsafe(newpub['rows']+newhid['rows'])-unsafe(public['rows']+hidden['rows']))
                    nr=sorted(runtime_failures(newpub['rows']+newhid['rows'])-runtime_failures(public['rows']+hidden['rows']))
                    base=score(public['rows']+hidden['rows']);sc=score(newpub['rows']+newhid['rows'])
                    record.update(score_before=base['score'],score_after=sc['score'],public_score=newpub['score'],public_passed=newpub['passed'],heldout_score=newhid['score'],heldout_passed=newhid['passed'],public_regressions=rp,heldout_regressions=rh,new_incorrect_successes=nu,new_runtime_failures=nr,heldout_result='evaluated')
                    gain=newpub['score']>public['score'] and sc['score']>base['score'] and not rp and not rh and not nu and not nr
                    record['reason']='regression_or_no_gain'
                    if gain:
                        repeatpub,ep2=suite(directory,'public','repeat',cfg,deadline);repeathid,eh2=suite(directory,'heldout','repeat',cfg,deadline)
                        stable=repeatpub is not None and repeathid is not None and pass_map(newpub)==pass_map(repeatpub) and pass_map(newhid)==pass_map(repeathid)
                        record.update(repeat_public_run=ep2,repeat_hidden_run=eh2,stable=stable,kept=stable,reason='improved_without_regression' if stable else 'unstable_or_repeat_failed')
        if record['kept']:
            public=newpub;hidden=newhid;keeps+=1
            write_json(RUN/'best-public.json',public);write_json(RUN/'best-heldout.json',hidden)
            (directory/'kept.patch').write_text(diff)
            if keeps==1:status('working',f"First Astra xhigh improvement kept: score {record['score_before']:.6f} to {record['score_after']:.6f}; no held-out regressions, repeat stable.")
        else:
            for p,data in RESTORE.items():p.write_bytes(data)
        RESTORE={}
        if fingerprint(allowed)!=frozen:raise RuntimeError('protected file changed after evaluation')
        record.update(finished=now(),keeps=keeps);append(RUN/'experiments.jsonl',record);print(json.dumps(record),flush=True)
        feedback={k:v for k,v in record.items() if k in ['attempt','agent_exit','build_exit','reason','kept','public_score','public_passed','public_regressions']}
        feedback['hypothesis']=summary[:2000]
        if record['reason']=='build_failed':feedback['build_error']='\n'.join((directory/'build.log').read_text().splitlines()[-65:])[-7000:]
        if newpub is not None and not record['kept']:
            changed_ids=set(record.get('public_regressions',[]))|{x for x in record.get('new_incorrect_successes',[])+record.get('new_runtime_failures',[]) if x.startswith('public-')}
            feedback['visible_vetoes']=[dict(case=json.loads((ROOT/'corpus/public'/(r['id']+'.json')).read_text()),result=r) for r in newpub['rows'] if r['id'] in changed_ids][:8]
        history.append(feedback)
        write_json(RUN/'public-history.json',history)
        (ROOT/'agent-scratch/last-candidate.patch').write_text(diff)
        failures=failures+1 if record['reason']=='agent_timeout_or_failure' else 0
        if failures>=2:raise RuntimeError('two consecutive agent failures; supervisor intervention required')
        if time.time()-last_hour>=3600:
            append(RUN/'hourly-checks.jsonl',dict(at=now(),attempt=i,keeps=keeps,score=score(public['rows']+hidden['rows'])['score'],controller_pid=os.getpid()))
            last_hour=time.time()
    final_patch=subprocess.check_output(['git','-C',str(KERNEL),'diff','--relative','--','*.rs'],text=True)
    (RUN/'kept.patch').write_text(final_patch)
    write_json(RUN/'controller-state.json',dict(state='finished',at=now(),attempts=CURRENT-1,keeps=keeps,score=score(public['rows']+hidden['rows'])['score']))
    status('working','Overnight experiment window finished; results are ready for final audit and public-safe packaging.')

if __name__=='__main__':
    try:main()
    except Exception as e:
        if CHILD and CHILD.poll() is None:
            try:os.killpg(CHILD.pid,signal.SIGKILL);CHILD.wait()
            except ProcessLookupError:pass
        for path,data in RESTORE.items():path.write_bytes(data)
        write_json(RUN/'controller-state.json',dict(state='failed',at=now(),attempt=CURRENT,error=str(e)))
        status('blocked',f'Overnight controller stopped: {e}. Evidence is in lab/overnight.')
        traceback.print_exc();raise
