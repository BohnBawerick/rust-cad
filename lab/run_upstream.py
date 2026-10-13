#!/usr/bin/env python3
"""Run the pinned upstream smoke tests with bounded lifetime and saved evidence."""
import json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
cmd=['cargo','test','--manifest-path',str(ROOT/'kernel/source/Cargo.toml'),'-p','monstertruck-solid','--test','boolean_smoke']
env=os.environ.copy();env.update(CARGO_HOME=str(ROOT/'cache/cargo'),CARGO_TARGET_DIR=str(ROOT/'upstream-target'),TMPDIR=str(ROOT/'tmp'),CARGO_BUILD_JOBS='4',RAYON_NUM_THREADS='1')
t=time.monotonic()
with (ROOT/'logs/upstream-smoke-online.log').open('w') as out:
 p=subprocess.Popen(cmd,stdout=out,stderr=subprocess.STDOUT,env=env,start_new_session=True)
 (ROOT/'upstream-test.pid').write_text(str(p.pid)+'\n')
 try:code=p.wait(timeout=300)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();code=124
(ROOT/'results/upstream-smoke-online.json').write_text(json.dumps({'command':cmd,'exit':code,'seconds':time.monotonic()-t},indent=2)+'\n')
print('upstream smoke exit',code)
