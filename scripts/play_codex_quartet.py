"""Frozen six-game four-category comparison; existing pilots are unchanged."""
import argparse
from dataclasses import asdict
import fcntl
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_quartet import ENTRIES, schedule, validate_schedule, configs_for
from werewolf.ratings import POLICY
from scripts.play_codex import play, save
from scripts.play_codex_league import check_canaries, collect_existing, write_results, verify_trial
from scripts.play_codex_league import fingerprint as base_fingerprint
from scripts.play_league import scheduled_games
from scripts.run_logging import emit
from scripts.verify_codex import require

VERSION = 'codex-quartet-league-v1'
DEFAULT_PLAN = Path('artifacts/codex-quartet-v1/plan.private.json')


def fingerprint():
    digest = hashlib.sha256(base_fingerprint().encode())
    root = Path(__file__).resolve().parents[1]
    for name in ('werewolf/codex_quartet.py', 'scripts/play_codex_quartet.py'):
        digest.update(name.encode()+b'\0'+(root/name).read_bytes())
    return digest.hexdigest()


def create_plan(path, seed):
    if path.exists():
        raise ValueError('Do not overwrite a frozen plan.')
    matches = schedule(seed)
    plan = {'protocol': VERSION, 'source_fingerprint': fingerprint(), 'schedule_seed': seed,
            'matches': matches, 'entries': {e: {'model': m, 'effort': f} for e, (m, f) in ENTRIES.items()},
            'configs': {m['id']: [asdict(c) for c in configs_for(m)] for m in matches},
            'canary_digests': check_canaries(path.parent, ENTRIES), 'rating_policy': POLICY,
            'max_batches': 300, 'workers_per_game': 2, 'codex_turn_timeout_seconds': 600,
            'initial_gate_games': 1, 'parallel_games_after_gate': 2,
            'failure_policy': 'Retain every attempt; halt new games on failure; no replacements, default actions or thread recreation.'}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2); stream.write('\n')
    save(path.parent/'preregistration.json', {k: v for k, v in plan.items() if k not in ('matches', 'configs')}
         | {'scheduled_games': 6, 'seats_per_entry_per_game': 3, 'seats_per_entry': 18,
            'role_exposure_per_entry': {e: {role: sum(entry == e and r == role for match in matches for entry, r in zip(match['entries'], match['roles'])) for role in ('wolf', 'villager', 'seer', 'witch', 'hunter', 'idiot')} for e in ENTRIES},
            'schedule_digest': hashlib.sha256(json.dumps(matches, sort_keys=True).encode()).hexdigest(),
            'comparison': 'Four independent rating entries: Sol/medium, Sol/low, Terra/high, Terra/low. Same harness and prompts; model and effort remain fixed per seat.'})
    return plan


def verify_plan(plan, execution=False):
    require(plan['protocol'] == VERSION, 'Wrong comparison protocol.')
    require(plan['matches'] == schedule(plan['schedule_seed']), 'Frozen quartet schedule changed.')
    validate_schedule(plan['matches'])
    require(plan['entries'] == {e: {'model': m, 'effort': f} for e, (m, f) in ENTRIES.items()}, 'Entries changed.')
    require(plan['configs'] == {m['id']: [asdict(c) for c in configs_for(m)] for m in plan['matches']}, 'Fixed seat settings changed.')
    require(plan['rating_policy'] == POLICY, 'Rating policy changed.')
    require((plan['max_batches'], plan['workers_per_game'], plan['codex_turn_timeout_seconds'],
             plan['initial_gate_games'], plan['parallel_games_after_gate']) == (300, 2, 600, 1, 2), 'Execution settings changed.')
    if execution:
        require(plan['source_fingerprint'] == fingerprint(), 'Code changed since preregistration.')


def run_one(match, plan, root):
    verify_plan(plan, execution=True)
    stem = match['id']
    if any((root/f'{stem}{suffix}').exists() for suffix in ('.json', '.private.json')):
        raise ValueError('Existing paid evidence must not be overwritten.')
    with (root/f'{stem}.claim.private.json').open('x') as stream:
        json.dump({'match_id': stem}, stream)
    try:
        play(match['seed'], configs=configs_for(match), roles=match['roles'], artifact_stem=stem,
             output_dir=root, max_batches=plan['max_batches'], workers=plan['workers_per_game'])
        report = verify_trial(json.loads((root/f'{stem}.private.json').read_text()), match, plan)
    except Exception as error:
        report = {'status': 'host_or_audit_error', 'all_checks_passed': False,
                  'category': getattr(error, 'validation_details', {}).get('category', type(error).__name__)}
    report.update(match_id=stem, pair=match['pair'], seed=match['seed'])
    save(root/f'{stem}.json', report)
    return report


def run_season(plan, root):
    verify_plan(plan, execution=True)
    require(check_canaries(root, ENTRIES) == plan['canary_digests'], 'Canary evidence changed.')
    reports, remaining = collect_existing(plan, root)
    halted = any(not r.get('all_checks_passed') for r in reports)
    write_results(plan, root, reports, halted)
    if halted:
        return 1
    if not reports and remaining:
        gate = run_one(remaining.pop(0), plan, root)
        reports.append(gate); halted = not gate.get('all_checks_passed')
        write_results(plan, root, reports, halted)
        emit({'gate': gate['match_id'], 'passed': not halted})
    if not halted:
        for report, halted in scheduled_games(remaining, lambda m: run_one(m, plan, root), parallel_games=2):
            reports.append(report); write_results(plan, root, reports, halted)
            emit({'match_id': report['match_id'], 'status': report['status'], 'winner': report.get('winner'),
                  'all_checks_passed': report.get('all_checks_passed'), 'scheduling_halted': halted})
    return int(halted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=DEFAULT_PLAN)
    parser.add_argument('--seed', type=int, default=18000)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create-plan', action='store_true')
    group.add_argument('--run', action='store_true')
    group.add_argument('--rate', action='store_true')
    args = parser.parse_args()
    if args.create_plan:
        plan = create_plan(args.plan, args.seed)
        emit({'plan': str(args.plan), 'games': len(plan['matches']), 'entries': list(ENTRIES)})
        return
    plan = json.loads(args.plan.read_text()); root = args.plan.parent
    if args.rate:
        verify_plan(plan)
        reports, _ = collect_existing(plan, root)
        ratings = write_results(plan, root, reports, any(not r.get('all_checks_passed') for r in reports))
        emit({'valid_games': ratings['valid_games'], 'ratings': ratings['ratings']})
        return
    with (root/'worker-lock.private.json').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run_season(plan, root))


if __name__ == '__main__':
    main()
