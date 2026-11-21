"""Run preregistered Sol-version cohorts in sequence and update pooled ratings."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.play_codex import save
from scripts.play_codex_trio import verify_plan
from scripts.rate_replays import replay_inputs
from werewolf.ratings import fit_ratings
from werewolf.win_rates import win_rates


def update_ratings(seeds, output):
    matches, reports = [], []
    for seed in seeds:
        batch_matches, batch_reports, _, _ = replay_inputs(
            Path('artifacts') / f'codex-sol-versions-{seed}' / 'replays'
        )
        matches.extend(batch_matches)
        reports.extend(batch_reports)
    ratings = fit_ratings(matches, reports)
    ratings['win_rates'] = win_rates(matches, reports)
    save(output, ratings)


def run(queue, root):
    scored_seeds = list(queue['historical_seeds'])
    state = {'phase': 'validating', 'batches': [], 'requested_games': 6 * len(queue['seeds'])}

    def heartbeat(**fields):
        state.update(fields, updated_at=datetime.now(timezone.utc).isoformat())
        save(root / 'status.json', state)

    try:
        heartbeat()
        update_ratings(scored_seeds, root / 'ratings.json')
        for seed in queue['seeds']:
            batch_root = Path('artifacts') / f'codex-sol-versions-{seed}'
            plan = batch_root / 'plan.private.json'
            declared = json.loads(plan.read_text())
            verify_plan(declared, execution=True)
            if declared['profile'] != 'sol-versions' or declared['schedule_seed'] != seed:
                raise ValueError('Queue and batch declaration differ.')
            with (batch_root / 'verification.log').open('x') as log:
                child = subprocess.Popen(
                    [sys.executable, '-u', 'scripts/play_codex_trio.py', '--plan', str(plan), '--run'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                )
                heartbeat(phase='running', active_seed=seed, worker_pid=child.pid)
                while child.poll() is None:
                    time.sleep(10)
                    heartbeat()
            ledger = json.loads((batch_root / 'results.json').read_text())
            reports = ledger['reports']
            valid = {report['match_id'] for report in reports if report['all_checks_passed']}
            exported = {path.stem for path in (batch_root / 'replays').glob('*.json')}
            state['batches'].append({
                'seed': seed, 'returned_games': len(reports), 'verified_games': len(valid),
                'worker_exit_code': child.returncode,
            })
            heartbeat(phase='scoring', worker_pid=None)
            if valid != exported:
                raise RuntimeError('Verified outcomes and exported replays differ.')
            scored_seeds.append(seed)
            update_ratings(scored_seeds, root / 'ratings.json')
            if child.returncode not in (0, 1) or len(reports) != 6 or not valid:
                raise RuntimeError('Worker did not return a complete ledger with a verified game.')
        heartbeat(phase='finished', active_seed=None)
    except Exception as error:
        heartbeat(phase='stopped', error=str(error))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('queue', type=Path)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    queue_path = args.queue.resolve()
    root = queue_path.parent
    if args.worker:
        run(json.loads(queue_path.read_text()), root)
        return
    with (root / 'verification.log').open('x') as log:
        process = subprocess.Popen(
            [sys.executable, '-u', str(Path(__file__).resolve()), str(queue_path), '--worker'],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    save(root / 'process.private.json', {'pid': process.pid})
    print(json.dumps({'pid': process.pid}))


if __name__ == '__main__':
    main()
