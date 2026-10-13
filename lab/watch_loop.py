#!/usr/bin/env python3
"""Observe the controller independently and save at least one health check per hour."""
import datetime,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'overnight'
pidfile=RUN/'controller.pid'
pid=int(pidfile.read_text())
started=pidfile.stat().st_mtime
next_check=0
while True:
    now=time.time()
    state=json.loads((RUN/'controller-state.json').read_text())
    try:
        os.kill(pid,0)
        live=True
    except ProcessLookupError:
        live=False
    fresh=datetime.datetime.fromisoformat(state['at']).timestamp()>=started
    terminal=fresh and state['state'] in ['finished','failed','stopped']
    if now>=next_check or terminal or not live:
        records_path=RUN/'experiments.jsonl'
        records=records_path.read_text().splitlines() if records_path.exists() else []
        row=dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),pid=pid,live=live,state=state,completed_attempts=len(records),keeps=sum(json.loads(r)['kept'] for r in records))
        with (RUN/'independent-health-checks.jsonl').open('a') as f:
            f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
        next_check=now+3500
    if terminal:break
    if not live:
        hook=os.environ.get('RESEARCH_STATUS_HOOK')
        if hook:subprocess.run(['python3',hook,'blocked','Controller exited without a terminal record; independent monitor stopped and saved its last check.'],check=True)
        break
    time.sleep(30)
