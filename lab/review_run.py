#!/usr/bin/env python3
"""Summarize the completed run and verify retained patch replay."""
import collections,csv,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'overnight'
records=[json.loads(line) for line in (RUN/'experiments.jsonl').read_text().splitlines()]
file='monstertruck-solid/src/transversal/classic/mod.rs'
replay=ROOT/'patch-replay';target=replay/file;target.parent.mkdir(parents=True,exist_ok=True)
target.write_bytes(subprocess.check_output(['git','-C',str(ROOT/'kernel/source'),'show','HEAD:./'+file]))
keeps=[r for r in records if r['kept']]
with (ROOT/'logs/patch-replay.log').open('w') as log:
 for r in keeps:subprocess.run(['patch','-p1','--directory',str(replay),'--input',str(RUN/f"attempt-{r['attempt']:03d}/kept.patch")],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=10)
assert target.read_bytes()==(ROOT/'kernel/source'/file).read_bytes()
assert (RUN/'kept.patch').read_bytes()==(ROOT/'final-audit/retained.patch').read_bytes()
metrics={}
for split in ['public','heldout']:
 before=json.loads((ROOT/f'results/frozen-baseline-{split}.json').read_text());after=json.loads((ROOT/f'final-audit/{split}.json').read_text())
 metrics[split]=dict(before={k:before[k] for k in ['passed','total','score','groups']},after={k:after[k] for k in ['passed','total','score','groups']},failures=[dict(id=r['id'],group=r['group'],reasons=r['reasons']) for r in after['rows'] if not r['pass']])
summary=dict(attempts=len(records),keeps=len(keeps),kept_attempts=[r['attempt'] for r in keeps],dispositions=dict(collections.Counter(r['reason'] for r in records)),patch_replay_matches=True,final_source_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),final_patch_sha256=hashlib.sha256((RUN/'kept.patch').read_bytes()).hexdigest(),kept_public_regressions=[r for r in keeps if r.get('public_regressions')],kept_private_regressions=[r for r in keeps if r.get('heldout_regressions')],metrics=metrics)
(ROOT/'results/run-review.json').write_text(json.dumps(summary,indent=2)+'\n')
with (RUN/'score-over-time.csv').open('w',newline='') as out:
 fields=['attempt','started','finished','revision','score_before','score_after','public_passed','heldout_passed','kept','reason','agent_seconds']
 writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(records)
print(json.dumps({k:v for k,v in summary.items() if k!='metrics'},indent=2))
