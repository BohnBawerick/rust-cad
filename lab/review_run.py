#!/usr/bin/env python3
"""Summarize a completed run and verify that replaying the kept patches reproduces the source."""
import collections,csv,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'overnight'
KERNEL=ROOT/'kernel/source'
records=[json.loads(line) for line in (RUN/'experiments.jsonl').read_text().splitlines()]
keeps=[r for r in records if r['kept']]
files=sorted({f for r in keeps for f in r['files_changed']})
replay=ROOT/'patch-replay'
for f in files:
    target=replay/f;target.parent.mkdir(parents=True,exist_ok=True)
    shown=subprocess.run(['git','-C',str(KERNEL),'show','HEAD:./'+f],capture_output=True)
    if shown.returncode==0:target.write_bytes(shown.stdout)
    elif target.exists():target.unlink()
(ROOT/'logs').mkdir(exist_ok=True)
with (ROOT/'logs/patch-replay.log').open('w') as log:
    for r in keeps:subprocess.run(['patch','-p1','--directory',str(replay),'--input',str(RUN/f"attempt-{r['attempt']:03d}/kept.patch")],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=10)
for f in files:
    replayed=(replay/f).read_bytes() if (replay/f).exists() else None
    current=(KERNEL/f).read_bytes() if (KERNEL/f).exists() else None
    assert replayed==current,f'replay differs from the retained source for {f}'
if (ROOT/'final-audit/retained.patch').exists():assert (RUN/'kept.patch').read_bytes()==(ROOT/'final-audit/retained.patch').read_bytes()
metrics={}
for split in ['public','heldout']:
    before=json.loads((ROOT/f'results/frozen-baseline-{split}.json').read_text())
    after_path=ROOT/f'final-audit/{split}.json' if (ROOT/f'final-audit/{split}.json').exists() else RUN/f'best-{split}.json'
    after=json.loads(after_path.read_text())
    metrics[split]=dict(before={k:before[k] for k in ['passed','total','score','groups']},after={k:after[k] for k in ['passed','total','score','groups']},failures=[dict(id=r['id'],group=r['group'],reasons=r['reasons']) for r in after['rows'] if not r['pass']])
summary=dict(attempts=len(records),keeps=len(keeps),kept_attempts=[r['attempt'] for r in keeps],lanes=dict(collections.Counter(r.get('lane') for r in records)),
    dispositions=dict(collections.Counter(r['reason'] for r in records)),files_changed=files,patch_replay_matches=True,
    final_patch_sha256=hashlib.sha256((RUN/'kept.patch').read_bytes()).hexdigest(),
    kept_public_regressions=[r for r in keeps if r.get('public_regressions')],kept_private_regressions=[r for r in keeps if r.get('heldout_regressions')],metrics=metrics)
(ROOT/'results').mkdir(exist_ok=True)
(ROOT/'results/run-review.json').write_text(json.dumps(summary,indent=2)+'\n')
with (RUN/'score-over-time.csv').open('w',newline='') as out:
    fields=['attempt','lane','started','finished','revision','score_before','score_after','public_passed','heldout_passed','kept','reason','agent_seconds']
    writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(records)
print(json.dumps({k:v for k,v in summary.items() if k!='metrics'},indent=2))
