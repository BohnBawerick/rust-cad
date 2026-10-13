"""Mount the candidate source and a private scratch home for the coding agent."""
import os
import shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent
EDIT = Path('monstertruck-solid/src/transversal/classic/mod.rs')
ENV = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'USER': os.environ.get('USER', 'researcher'), 'LC_ALL': 'C', 'TMPDIR': '/tmp'}

def command(prompt, editable=None):
    binary_dir = Path(shutil.which('codex')).resolve().parent
    resolver = Path('/etc/resolv.conf').resolve()
    args = ['bwrap', '--unshare-all', '--share-net', '--die-with-parent',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--symlink', 'usr/bin', '/bin', '--ro-bind', '/etc', '/etc',
            '--ro-bind', str(resolver), str(resolver), '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--bind', str(ROOT/'agent-home'), str(Path.home()), '--ro-bind', str(ROOT/'kernel/source'), '/work/kernel']
    for path in editable or [EDIT]:
        args += ['--bind', str(ROOT/'kernel/source'/path), '/work/kernel/'+str(path)]
    args += ['--bind', str(ROOT/'agent-scratch'), '/work/scratch', '--ro-bind', str(binary_dir), '/opt/codex',
             '--chdir', '/work/kernel', '--', '/opt/codex/codex', 'exec', '--ignore-user-config', '--ephemeral',
             '--json', '--skip-git-repo-check', '-s', 'danger-full-access', '-c', 'approval_policy="never"',
             '-m', 'gpt-6-astra', '-c', 'model_reasoning_effort="xhigh"', '-c', 'web_search="disabled"',
             '-c', 'features.apps=false', '-o', '/work/scratch/last-message.txt', prompt]
    return args
