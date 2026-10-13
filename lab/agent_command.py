"""Build the sandboxed coding-agent command for the configured harness.

The agent sees the kernel source read-only except the lane's editable paths, its private
scratch directory, a read-only copy of the probe source (so it can see exactly how a recipe
becomes geometry) and a private home that holds only its own subscription login. It has
network access because the subscription login needs it; the prompt forbids using it for
anything else.

Harnesses:

- `codex`: `codex exec` on a ChatGPT subscription. `agent-home/.codex/auth.json` must hold a
  ChatGPT login and no API key. Model and reasoning effort come from the config.
- `claude`: `claude -p` on a Claude subscription. `agent-home/.claude/.credentials.json` must
  hold the login. Model and effort come from the config.

Neither harness ever receives an API key: the environment is a fixed allow-list and
`forbid_api_keys` refuses to start when one is present in the agent home or the process
environment, so a rate limit can only back off or stop, never fall through to a paid key.
The agent home is the only credential source the sandbox can see.
"""
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = ROOT / 'agent-home'
SCRATCH = ROOT / 'agent-scratch'
ENV = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'USER': os.environ.get('USER', 'researcher'),
       'LC_ALL': 'C', 'TMPDIR': '/tmp'}
API_KEY_VARIABLES = ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CODEX_API_KEY')
# Messages the harnesses print when the subscription is throttled or exhausted. Matched
# case-insensitively against the agent's event log.
RATE_LIMIT_PATTERN = re.compile(
    r'rate.?limit|usage.?limit|usage_limited|budget_limited|too many requests|\b429\b|'
    r'insufficient_quota|quota exceeded|exceeded your current quota|try again (later|in|after)',
    re.IGNORECASE)


def forbid_api_keys(harness):
    for name in API_KEY_VARIABLES:
        if os.environ.get(name):
            raise RuntimeError(f'{name} is set in the environment; the loop runs on a subscription login only')
    auth = HOME / '.codex/auth.json'
    if harness == 'codex':
        if not auth.exists():
            raise RuntimeError(f'{auth} is missing; copy a ChatGPT login there with mode 600')
        data = json.loads(auth.read_text())
        if data.get('OPENAI_API_KEY'):
            raise RuntimeError(f'{auth} holds an API key; the loop runs on a ChatGPT login only')
    if harness == 'claude' and not (HOME / '.claude/.credentials.json').exists():
        raise RuntimeError(f'{HOME}/.claude/.credentials.json is missing; copy a Claude login there with mode 600')


def binary_dir(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f'{name} is not on PATH')
    return Path(path).resolve().parent


def sandbox(editable, harness):
    resolver = Path('/etc/resolv.conf').resolve()
    args = ['bwrap', '--unshare-all', '--share-net', '--die-with-parent',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--symlink', 'usr/bin', '/bin', '--ro-bind', '/etc', '/etc',
            '--ro-bind', str(resolver), str(resolver), '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--bind', str(HOME), str(Path.home()),
            '--ro-bind', str(ROOT / 'kernel/source'), '/work/kernel']
    for path in editable:
        args += ['--bind', str(ROOT / 'kernel/source' / path), '/work/kernel/' + str(path)]
    args += ['--ro-bind', str(ROOT / 'probe/src'), '/work/probe',
             '--bind', str(SCRATCH), '/work/scratch',
             '--ro-bind', str(binary_dir(harness)), '/opt/agent',
             '--chdir', '/work/kernel', '--']
    return args


def codex(agent, prompt):
    return ['/opt/agent/codex', 'exec', '--ignore-user-config', '--ephemeral', '--json', '--skip-git-repo-check',
            '-s', 'danger-full-access', '-c', 'approval_policy="never"',
            '-m', agent['model'], '-c', f'model_reasoning_effort="{agent["effort"]}"',
            '-c', 'web_search="disabled"', '-c', 'features.apps=false',
            '-o', '/work/scratch/last-message.txt', prompt]


def claude(agent, prompt):
    return ['/opt/agent/claude', '-p', '--bare', '--dangerously-skip-permissions',
            '--model', agent['model'], '--effort', agent['effort'],
            '--output-format', 'stream-json', '--verbose', prompt]


HARNESSES = {'codex': codex, 'claude': claude}


def command(agent, prompt, editable):
    """The full sandboxed command line for one attempt."""
    harness = agent['harness']
    if harness not in HARNESSES:
        raise ValueError(f'unknown harness {harness!r}; choose one of {sorted(HARNESSES)}')
    return sandbox(editable, harness) + HARNESSES[harness](agent, prompt)


def summary(agent, log):
    """The agent's final message for one attempt, at most 5000 characters."""
    if agent['harness'] == 'codex':
        path = SCRATCH / 'last-message.txt'
        return path.read_text()[:5000] if path.exists() else ''
    text = ''
    for line in Path(log).read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'result':
            text = event.get('result') or ''
    return text[:5000]


def usage(agent, log):
    """Token usage summed over the attempt's turns, when the harness reports it."""
    totals = {}
    path = Path(log)
    if not path.exists():
        return totals
    for line in path.read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        report = event.get('usage') if agent['harness'] == 'codex' and event.get('type') == 'turn.completed' else None
        if agent['harness'] == 'claude' and event.get('type') == 'result':
            report = event.get('usage')
        for key, value in (report or {}).items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
    return totals


def rate_limited(log):
    """True when the agent log shows the subscription was throttled or exhausted."""
    path = Path(log)
    if not path.exists():
        return False
    return bool(RATE_LIMIT_PATTERN.search(path.read_text(errors='replace')))
