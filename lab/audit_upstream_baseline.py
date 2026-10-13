#!/usr/bin/env python3
"""Compare upstream tests with the pinned file, then restore the retained source."""
import json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
source=ROOT/'kernel/source/monstertruck-solid/src/transversal/classic/mod.rs'
retained=source.read_bytes()
base=subprocess.check_output(['git','-C',str(ROOT/'kernel/source'),'show','HEAD:./monstertruck-solid/src/transversal/classic/mod.rs'])
env=os.environ.copy();env.update(CARGO_HOME=str(ROOT/'cache/cargo'),CARGO_TARGET_DIR=str(ROOT/'upstream-target'),TMPDIR=str(ROOT/'tmp'),CARGO_BUILD_JOBS='4',RAYON_NUM_THREADS='1')
cmd=['cargo','test','--locked','--offline','--manifest-path',str(ROOT/'kernel/source/Cargo.toml'),'-p','monstertruck-solid','--lib','--','--test-threads=2']
t=time.monotonic()
try:
 source.write_bytes(base)
 with (ROOT/'logs/upstream-unit-baseline.log').open('w') as out:
  p=subprocess.Popen(cmd,stdout=out,stderr=subprocess.STDOUT,env=env,start_new_session=True)
  (ROOT/'upstream-baseline.pid').write_text(str(p.pid)+'\n')
  try:rc=p.wait(timeout=120)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();rc=124
finally:source.write_bytes(retained)
assert source.read_bytes()==retained
(ROOT/'results/upstream-unit-baseline.json').write_text(json.dumps({'command':cmd,'exit':rc,'seconds':time.monotonic()-t,'retained_source_restored':True},indent=2)+'\n')
print('baseline unit exit',rc)
