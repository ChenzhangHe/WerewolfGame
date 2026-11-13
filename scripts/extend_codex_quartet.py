"""Twelve fresh four-setting games, plus an audited cumulative eighteen-game fit."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import fcntl
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_quartet import ENTRIES, schedule, validate_schedule, configs_for
from werewolf.ratings import POLICY, fit_ratings
from scripts.play_codex import play, save
from scripts.play_codex_quartet import fingerprint as base_fingerprint, verify_plan as verify_baseline
from scripts.play_codex_league import check_canaries, collect_existing, verify_trial
from scripts.play_league import scheduled_games
from scripts.run_logging import emit
from scripts.verify_codex import require

VERSION = 'codex-quartet-extension-v1'
DEFAULT_PLAN = Path('artifacts/codex-quartet-extension-v1/plan.private.json')
BASELINE = Path('artifacts/codex-quartet-v1/plan.private.json')


def fingerprint():
    return hashlib.sha256((base_fingerprint()+Path(__file__).read_text()).encode()).hexdigest()


def continuation_schedule():
    entries = list(ENTRIES)
    matches = []
    for seed, shift in ((19000, 1), (20000, 2)):
        batch = schedule(seed)
        mapping = {entry: entries[(i+shift)%4] for i, entry in enumerate(entries)}
        for m in batch:
            m['entries'] = [mapping[e] for e in m['entries']]
        validate_schedule(batch)
        for m in batch:
            m['pair'] = f"{seed}:{m['pair']}"
        matches.extend(batch)
    return matches


def baseline_evidence(path):
    require(path == BASELINE, 'The continuation uses the declared first quartet pilot.')
    plan = json.loads(path.read_text()); verify_baseline(plan)
    root = path.parent
    reports, remaining = collect_existing(plan, root)
    require(not remaining and len(reports) == 6 and all(r['all_checks_passed'] for r in reports), 'Baseline must contain six audited completions.')
    paths = [path, root/'results.json']+[root/f"{m['id']}.private.json" for m in plan['matches']]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    matches = deepcopy(plan['matches'])
    for m in matches:
        m['pair'] = f"18000:{m['pair']}"
    return matches, reports, hashes


def create_plan(path):
    if path.exists():
        raise ValueError('Do not overwrite the frozen continuation plan.')
    _, _, baseline_hashes = baseline_evidence(BASELINE)
    matches = continuation_schedule()
    plan = {'protocol': VERSION, 'source_fingerprint': fingerprint(), 'matches': matches,
            'baseline': str(BASELINE), 'baseline_hashes': baseline_hashes,
            'entries': {e: {'model': m, 'effort': f} for e, (m, f) in ENTRIES.items()},
            'configs': {m['id']: [asdict(c) for c in configs_for(m)] for m in matches},
            'canary_digests': check_canaries(path.parent, ENTRIES), 'rating_policy': POLICY,
            'max_batches': 300, 'workers_per_game': 2, 'codex_turn_timeout_seconds': 600,
            'initial_gate_games': 1, 'parallel_games_after_gate': 2,
            'failure_policy': 'Retain every attempt; halt new games on failure; no replacements, default actions or thread recreation.'}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2); stream.write('\n')
    save(path.parent/'preregistration.json', {k: v for k, v in plan.items() if k not in ('matches', 'configs')}
         | {'additional_games': 12, 'total_games_with_baseline': 18,
            'entry_rotation': {'19000': 1, '20000': 2},
            'additional_role_exposure': {e: {role: sum(entry == e and r == role for m in matches for entry, r in zip(m['entries'], m['roles'])) for role in ('wolf', 'villager', 'seer', 'witch', 'hunter', 'idiot')} for e in ENTRIES},
            'schedule_digest': hashlib.sha256(json.dumps(matches, sort_keys=True).encode()).hexdigest(),
            'cumulative_policy': 'Refit all audited outcomes once with unchanged priors; namespace layout groups by cohort; no averaging of batch ratings.'})
    return plan


def verify_plan(plan, execution=False):
    require(plan['protocol'] == VERSION and plan['matches'] == continuation_schedule(), 'Continuation schedule changed.')
    require(plan['entries'] == {e: {'model': m, 'effort': f} for e, (m, f) in ENTRIES.items()}, 'Entries changed.')
    require(plan['configs'] == {m['id']: [asdict(c) for c in configs_for(m)] for m in plan['matches']}, 'Fixed seat settings changed.')
    require(plan['rating_policy'] == POLICY and plan['baseline'] == str(BASELINE), 'Rating policy or baseline changed.')
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


def write_results(plan, root, reports, halted, baseline):
    matches, old_reports = baseline
    save(root/'results.json', {'protocol': VERSION, 'reports': sorted(reports, key=lambda r: r['match_id']),
         'scheduler': {'halted_on_failure': halted, 'scheduled_games': 12, 'returned_games': len(reports),
                       'unattempted': [m['id'] for m in plan['matches'] if m['id'] not in {r['match_id'] for r in reports}]}})
    save(root/'ratings.json', fit_ratings(plan['matches'], reports))
    cumulative = fit_ratings(matches+plan['matches'], old_reports+reports)
    cumulative['baseline_hashes'] = plan['baseline_hashes']
    save(root/'cumulative-ratings.json', cumulative)


def run_season(plan, root):
    verify_plan(plan, execution=True)
    require(check_canaries(root, ENTRIES) == plan['canary_digests'], 'Canary evidence changed.')
    matches, old_reports, hashes = baseline_evidence(Path(plan['baseline']))
    require(hashes == plan['baseline_hashes'], 'Baseline evidence changed.')
    baseline = matches, old_reports
    reports, remaining = collect_existing(plan, root)
    halted = any(not r.get('all_checks_passed') for r in reports)
    write_results(plan, root, reports, halted, baseline)
    if halted:
        return 1
    if not reports:
        gate = run_one(remaining.pop(0), plan, root)
        reports.append(gate); halted = not gate.get('all_checks_passed')
        write_results(plan, root, reports, halted, baseline)
        emit({'gate': gate['match_id'], 'passed': not halted})
    if not halted:
        for report, halted in scheduled_games(remaining, lambda m: run_one(m, plan, root), parallel_games=2):
            reports.append(report); write_results(plan, root, reports, halted, baseline)
            emit({'match_id': report['match_id'], 'status': report['status'], 'all_checks_passed': report.get('all_checks_passed')})
    return int(halted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=DEFAULT_PLAN)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create-plan', action='store_true')
    group.add_argument('--run', action='store_true')
    group.add_argument('--rate', action='store_true')
    args = parser.parse_args()
    if args.create_plan:
        create_plan(args.plan); emit({'additional_games': 12, 'plan': str(args.plan)}); return
    plan = json.loads(args.plan.read_text()); root = args.plan.parent
    if args.rate:
        verify_plan(plan)
        matches, baseline, hashes = baseline_evidence(Path(plan['baseline']))
        require(hashes == plan['baseline_hashes'], 'Baseline evidence changed.')
        reports, _ = collect_existing(plan, root)
        write_results(plan, root, reports, any(not r.get('all_checks_passed') for r in reports), (matches, baseline))
        emit({'valid_games': json.loads((root/'cumulative-ratings.json').read_text())['valid_games']}); return
    with (root/'worker-lock.private.json').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run_season(plan, root))


if __name__ == '__main__':
    main()
