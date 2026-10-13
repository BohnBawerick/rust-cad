"""Compile candidates offline without mounting oracles, cases or credentials."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def command():
    return ['bwrap','--unshare-all','--die-with-parent',
            '--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
            '--symlink','usr/bin','/bin','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
            '--ro-bind',str(ROOT/'kernel/source'),'/work/kernel/source',
            '--ro-bind',str(ROOT/'probe'),'/work/probe',
            '--bind',str(ROOT/'cache/cargo'),'/cargo',
            '--bind',str(ROOT/'target'),'/target',
            '--setenv','CARGO_HOME','/cargo','--setenv','CARGO_TARGET_DIR','/target',
            '--setenv','TMPDIR','/tmp','--setenv','CARGO_BUILD_JOBS','4',
            '--setenv','RAYON_NUM_THREADS','1','--chdir','/work',
            '--','/usr/bin/cargo','run','--locked','--offline','--manifest-path','/work/probe/Cargo.toml','--','/missing-input.json']
ENV={'PATH':'/usr/bin:/bin','LC_ALL':'C'}
