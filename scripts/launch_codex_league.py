"""Detach league verification from chat/terminal lifetime, preserving file-backed logs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.play_codex import save
from scripts.play_codex_league import DEFAULT_PLAN
from scripts.run_logging import emit


def now():
    return datetime.now(timezone.utc).isoformat()


def worker(plan, runner="pair"):
    root = plan.parent
    status = root/'verification-status.private.json'
    data = {'phase': 'running_games', 'pid': os.getpid(), 'at_utc': now()}
    save(status, data)
    try:
        script = {'pair': 'scripts/play_codex_league.py', 'trio': 'scripts/play_codex_trio.py',
                  'quartet': 'scripts/play_codex_quartet.py'}[runner]
        command = [sys.executable, '-u', script, '--plan', str(plan)]
        run = subprocess.run(command+['--run'])
        data['runner_exit_code'] = run.returncode
        rate = subprocess.run(command+['--rate'])
        data['rating_exit_code'] = rate.returncode
        results = json.loads((root/'results.json').read_text())
        data['returned_games'] = len(results['reports'])
        data['completed_games'] = sum(bool(r.get('all_checks_passed')) for r in results['reports'])
        data['phase'] = 'finished' if data['completed_games'] == results['scheduler']['scheduled_games'] and rate.returncode == 0 else 'stopped_on_failure'
    except Exception as error:
        data.update(phase='host_error', category=type(error).__name__)
    finally:
        data['at_utc'] = now()
        save(status, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=DEFAULT_PLAN)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--runner', choices=('pair', 'trio', 'quartet'), default='pair')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    plan = args.plan.resolve()
    if args.worker:
        os.chdir(repo)
        worker(plan, args.runner)
        return
    if not plan.exists():
        parser.error('Create the frozen plan first.')
    # Exclusive ownership marker prevents duplicate launches, even during startup.
    # It is retained after exit; resuming requires an explicit direct --run command.
    ownership = plan.parent/'verification-process.private.json'
    with ownership.open('x') as marker:
        with (plan.parent/'verification.log').open('x') as log:
            child = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()), '--worker', '--plan', str(plan), '--runner', args.runner],
                                     cwd=repo, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        data = {'pid': child.pid, 'process_group': child.pid, 'created_at_utc': now(), 'plan': str(plan),
                'log': str(plan.parent/'verification.log'), 'runner': args.runner}
        json.dump(data, marker)
        marker.write('\n')
    emit({'detached_pid': child.pid, 'plan': str(plan), 'log': data['log']})


if __name__ == '__main__':
    main()
