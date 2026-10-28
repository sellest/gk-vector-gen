"""Pull main in place; finish dependency installation at the next startup."""
from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys

REPOSITORY = "https://github.com/sellest/gk-vector-gen.git"
CHECKOUT = Path(__file__).resolve().parents[2]
PENDING_FILE = '.gk-vector-update.json'


def _canonical_remote(url: str) -> str:
    value=url.strip().rstrip('/')
    if value.startswith('git@github.com:'):
        value='https://github.com/'+value.split(':',1)[1]
    elif value.startswith('ssh://git@github.com/'):
        value='https://github.com/'+value.split('github.com/',1)[1]
    return value.removesuffix('.git').casefold()


def _run(command: list[str], root: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    environment={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'Never'}
    return subprocess.run(command,cwd=root,env=environment,capture_output=True,
                          text=True,encoding='utf-8',errors='replace',timeout=timeout)


def update_tool(root: str | Path = CHECKOUT, runner=None) -> dict:
    """Only update this checkout from origin/main; never stash/reset user changes."""
    root=Path(root).resolve()
    runner=runner or _run
    before=None
    stage='preflight'
    def execute(command,timeout=120):
        process=runner(command,root,timeout)
        if process.returncode:
            message=(process.stderr or process.stdout or 'Command failed').strip()
            raise RuntimeError(message[-5000:])
        return process.stdout.strip()
    try:
        top=Path(execute(['git','rev-parse','--show-toplevel'])).resolve()
        if top!=root:
            raise ValueError('Run the updater from the gk-vector repository checkout.')
        if execute(['git','symbolic-ref','--short','HEAD'])!='main':
            raise ValueError('Switch this checkout to main before updating.')
        if _canonical_remote(execute(['git','remote','get-url','origin']))!=_canonical_remote(REPOSITORY):
            raise ValueError('origin must point to sellest/gk-vector-gen before updating.')
        if execute(['git','status','--porcelain','--untracked-files=no']):
            raise ValueError('Local tracked files have changes. Commit or move those changes before updating; nothing was overwritten.')
        before=execute(['git','rev-parse','HEAD'])
        stage='pull'
        execute(['git','pull','--ff-only','origin','main'])
        current=execute(['git','rev-parse','HEAD'])
        stage='schedule_install'
        (root/PENDING_FILE).write_text(json.dumps({'commit':current}),encoding='utf-8')
        return {'status':'updated' if current!=before else 'up_to_date',
                'branch':'main','previous_commit':before,'current_commit':current,
                'dependencies_pending':True,'restart_required':True,
                'message':'Main pulled. Restart the app or MCP connection; startup will install dependencies and load the update.'}
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        return {'status':'blocked' if stage=='preflight' else 'failed','stage':stage,
                'previous_commit':before,'restart_required':stage=='schedule_install','error':str(error),
                'message':'Update did not finish; no reset or cleanup was performed.'}


def install_pending_update(root: str | Path = CHECKOUT, runner=None) -> bool:
    """Install before native image libraries are imported (important on Windows)."""
    root=Path(root).resolve()
    marker=root/PENDING_FILE
    if not marker.exists():return False
    runner=runner or _run
    commands=[([sys.executable,'-m','pip','--isolated','install','--disable-pip-version-check',
                '-r',str(root/'requirements-lock.txt')],600),
              ([sys.executable,'-m','pip','--isolated','install','--disable-pip-version-check',
                '--no-deps','--no-build-isolation','-e',str(root)],600),
              ([sys.executable,'-m','pip','check'],120)]
    for command,timeout in commands:
        print('gk-vector: finishing update before startup...',file=sys.stderr,flush=True)
        result=runner(command,root,timeout)
        if result.returncode:
            raise RuntimeError('Update dependency installation failed; restart to retry: '+(result.stderr or result.stdout)[-5000:])
    marker.unlink()
    return True


def cli():
    if sys.argv[1:]==['update']:
        result=update_tool()
        print(json.dumps(result,indent=2))
        if result['status'] in ('blocked','failed'):raise SystemExit(2)
        return
    install_pending_update()
    from .cli import main
    main()


def serve():
    install_pending_update()
    from .server import main
    main()
