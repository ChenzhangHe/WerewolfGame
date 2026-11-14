"""Run a frozen Codex configuration league; no DeepSeek or archive inputs."""
import argparse
from dataclasses import asdict
import fcntl
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_league import ENTRIES, selected_entries, schedule, validate_schedule, configs_for
from werewolf.ratings import POLICY, fit_ratings
from scripts.play_codex import play, save, audit_match
from scripts.play_league import scheduled_games, source_fingerprint as core_fingerprint
from scripts.run_logging import emit
from scripts.verify_codex import audit_trial, require

VERSION = 'codex-configuration-league-v1'
DUEL_VERSION = 'codex-sol-terra-v1'
DEFAULT_PLAN = Path('artifacts/codex-sol-medium-terra-low-v1/plan.private.json')


def fingerprint():
    digest = hashlib.sha256(core_fingerprint().encode())
    root = Path(__file__).resolve().parents[1]
    for name in ('werewolf/codex_league.py', 'scripts/play_codex_league.py', 'werewolf/ratings.py', 'scripts/rate_replays.py', 'werewolf/replays.py'):
        digest.update(name.encode()+b'\0'+(root/name).read_bytes())
    return digest.hexdigest()


def check_canaries(root, entries=None):
    evidence = {}
    for entry, (model, effort) in (entries or ENTRIES).items():
        path = root/f'canary-{entry}.private.json'
        raw = path.read_bytes()
        trial = json.loads(raw)
        require(trial['test_kind'] == 'synthetic-seat-snapshots-not-a-full-AI-game', 'Use fresh synthetic canaries.')
        require(trial.get('exercise_tools_requested') is True, 'Canary must exercise tools.')
        require(len(trial['players']) == 1, 'Canary must use one isolated seat.')
        player = trial['players'][0]
        require(player['config']['model'] == model and player['config']['effort'] == effort, 'Canary configuration changed.')
        require(len(player['decisions']) == 2, 'Canary requires two decisions.')
        report = audit_trial(trial)
        require(report['all_checks_passed'] and report['players_with_successful_thread_reuse'] == 1,
                'Canary failed tool or thread-reuse audit.')
        evidence[entry] = hashlib.sha256(raw).hexdigest()
    return evidence


def validated_pair_baseline(*, audit=False):
    root = Path('artifacts/codex-sol-medium-terra-low-v1')
    baseline = json.loads((root/'plan.private.json').read_text()); verify_plan(baseline)
    status = json.loads((root/'verification-status.private.json').read_text())
    require(status['phase'] == 'finished' and status['completed_games'] == 6 and status.get('runner_exit_code') == 0,
            'Parallel comparison requires a completed baseline.')
    if audit:
        reports, remaining = collect_existing(baseline, root)
        require(not remaining and len(reports) == 6 and all(r['all_checks_passed'] for r in reports), 'Baseline failed re-audit.')
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [root/'plan.private.json', root/'results.json']+[root/f"{m['id']}.json" for m in baseline['matches']]}


def create_plan(path, seed, games=6, profile="pair", *, parallel_games=2):
    entries = selected_entries(profile)
    if parallel_games not in (2, 6) or (parallel_games == 6 and profile != "sol-terra"):
        raise ValueError("Six-way execution is reserved for the validated Sol/Terra profile.")
    if path.exists():
        raise ValueError('Do not overwrite an existing frozen plan.')
    canaries = check_canaries(path.parent, entries)
    matches = schedule(seed, games=games, profile=profile)
    plan = {'protocol': DUEL_VERSION if profile == 'sol-terra' else VERSION, 'source_fingerprint': fingerprint(), 'schedule_seed': seed, 'games': games, 'profile': profile,
            'matches': matches, 'configs': {m['id']: [asdict(c) for c in configs_for(m)] for m in matches},
            'entries': {e: {'model': m, 'effort': effort} for e, (m, effort) in entries.items()},
            'canary_digests': canaries, 'rating_policy': POLICY, 'max_batches': 300, 'workers_per_game': 2,
            'codex_turn_timeout_seconds': 600, 'initial_gate_games': 0 if parallel_games == 6 else 1, 'parallel_games_after_gate': parallel_games,
            'failure_policy': 'Retain every attempt; halt new games on failure; no replacement, default action or thread recreation.'}
    if parallel_games == 6:
        plan['validated_baseline'] = validated_pair_baseline(audit=True)
    if profile == 'sol-terra':
        replay_root = Path('replays')
        plan['historical_replays'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(replay_root.glob('*.json'))}
        plan['scoring_grouping'] = 'model-family'
        prefixes = {Path(name).stem.rsplit('-',1)[0] for name in plan['historical_replays']}
        attempts = {}
        for ledger in Path('artifacts').glob('*/results.json'):
            for report in json.loads(ledger.read_text()).get('reports', []):
                if report['match_id'].rsplit('-',1)[0] in prefixes:
                    attempts[report['match_id']] = report
        plan['historical_reliability'] = {'attempts':len(attempts), 'valid_games':len(plan['historical_replays']),
            'excluded':[{'match_id':r['match_id'],'status':r['status']} for r in attempts.values() if not r.get('all_checks_passed')]}
    # Exclusive creation preserves the preregistration even if two launchers race.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    save(path.parent/'preregistration.json', {k: v for k, v in plan.items() if k not in ('matches', 'configs')}
         | {'scheduled_games': games,
            'role_exposure_per_entry': {e: {role: sum(entry == e and r == role for match in matches for entry, r in zip(match['entries'], match['roles'])) for role in ('wolf', 'villager', 'seer', 'witch', 'hunter', 'idiot')} for e in entries},
            'schedule_digest': hashlib.sha256(json.dumps(matches, sort_keys=True).encode()).hexdigest()})
    return plan


def verify_plan(plan, execution=False):
    require(plan['protocol'] in (VERSION, DUEL_VERSION), 'Wrong league protocol.')
    require((plan['profile'] == 'sol-terra') == (plan['protocol'] == DUEL_VERSION), 'Scoring profile changed.')
    require(plan['matches'] == schedule(plan['schedule_seed'], games=plan['games'], profile=plan['profile']), 'Frozen rotation schedule changed.')
    validate_schedule(plan['matches'])
    require(plan['entries'] == {e: {'model': m, 'effort': f} for e, (m, f) in selected_entries(plan['profile']).items()}, 'Entries changed.')
    require(plan['configs'] == {m['id']: [asdict(c) for c in configs_for(m)] for m in plan['matches']}, 'Fixed seat settings changed.')
    require(plan['rating_policy'] == POLICY, 'Rating policy changed.')
    six_way = plan['protocol'] == DUEL_VERSION and plan['parallel_games_after_gate'] == 6
    expected = (300, 2, 600, 0, 6) if six_way else (300, 2, 600, 1, 2)
    require((plan['max_batches'], plan['workers_per_game'], plan['codex_turn_timeout_seconds'],
             plan['initial_gate_games'], plan['parallel_games_after_gate']) == expected, 'Execution settings changed.')
    if execution and six_way:
        require(plan['validated_baseline'] == validated_pair_baseline(), 'Baseline changed.')
    if plan['profile'] == 'sol-terra':
        require(plan.get('scoring_grouping') == 'model-family' and bool(plan.get('historical_replays')), 'Historical scoring basis changed.')
    if execution:
        require(plan['source_fingerprint'] == fingerprint(), 'Code changed since preregistration.')


def verify_trial(trial, match, plan):
    require(trial['source_seed'] == match['seed'], 'Game seed changed.')
    require([p['role'] for p in sorted(trial['game']['players'], key=lambda p: p['seat'])] == match['roles'], 'Roles changed.')
    require([p['config'] for p in sorted(trial['players'], key=lambda p: p['config']['seat'])] == plan['configs'][match['id']],
            'Game configurations differ from frozen plan.')
    return audit_match(trial)


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


def collect_existing(plan, root):
    reports, remaining = [], []
    for match in plan['matches']:
        stem = match['id']; summary = root/f'{stem}.json'; raw = root/f'{stem}.private.json'
        if summary.exists():
            report = json.loads(summary.read_text())
            require(report['match_id'] == stem, 'Result game ID changed.')
            if report.get('all_checks_passed'):
                audited = verify_trial(json.loads(raw.read_text()), match, plan)
                require(audited['all_checks_passed'] and audited['winner'] == report['winner'], 'Saved result failed replay.')
            reports.append(report)
        elif raw.exists() or (root/f'{stem}.claim.private.json').exists():
            # An uncertain paid attempt is retained, never restarted as a fresh thread.
            report = {'match_id': stem, 'seed': match['seed'], 'pair': match['pair'],
                      'status': 'interrupted', 'all_checks_passed': False}
            save(summary, report); reports.append(report)
        else:
            remaining.append(match)
    return reports, remaining


@lru_cache(maxsize=4)
def historical_inputs(file_hashes):
    from scripts.rate_replays import replay_inputs
    replay_root = Path('replays')
    for name, expected in file_hashes:
        require(Path(name).name == name and hashlib.sha256((replay_root/name).read_bytes()).hexdigest() == expected,
                'Frozen historical replay changed.')
    matches, reports, _, exposures = replay_inputs(replay_root, grouping='model-family', filenames=[n for n,_ in file_hashes])
    return matches, reports, exposures


def write_results(plan, root, reports, halted):
    save(root/'results.json', {'protocol': plan['protocol'], 'reports': sorted(reports, key=lambda r: r['match_id']),
         'scheduler': {'halted_on_failure': halted, 'scheduled_games': len(plan['matches']),
                       'returned_games': len(reports),
                       'unattempted': [m['id'] for m in plan['matches'] if m['id'] not in {r['match_id'] for r in reports}]}})
    ratings = fit_ratings(plan['matches'], reports)
    if plan.get('profile') == 'sol-terra':
        save(root/'batch-ratings.json', ratings)
        old_matches, old_reports, exposures = historical_inputs(tuple(sorted(plan['historical_replays'].items())))
        current = [{**m, 'pair':str(plan['schedule_seed'])+':'+str(m['pair'])} for m in plan['matches']]
        ratings = fit_ratings(old_matches+current, old_reports+reports)
        ratings.update(entry_grouping='model-family', historical_thinking_effort_exposure=exposures,
                       historical_reliability=plan['historical_reliability'],
                       scheduled_attempts=plan['historical_reliability']['attempts']+len(plan['matches']),
                       interpretation='Retains all valid historical outcomes; historical thinking efforts differ. New Sol uses medium, new Terra uses low.')
    save(root/'ratings.json', ratings)
    return ratings


def run_season(plan, root):
    verify_plan(plan, execution=True)
    require(check_canaries(root, selected_entries(plan['profile'])) == plan['canary_digests'], 'Canary evidence changed.')
    if plan['parallel_games_after_gate'] == 6:
        require(plan['validated_baseline'] == validated_pair_baseline(audit=True), 'Baseline changed.')
    reports, remaining = collect_existing(plan, root)
    halted = any(not r.get('all_checks_passed') for r in reports)
    write_results(plan, root, reports, halted)
    if halted:
        return 1
    if not reports and remaining and plan['initial_gate_games']:
        gate = run_one(remaining.pop(0), plan, root)
        reports.append(gate); halted = not gate.get('all_checks_passed')
        write_results(plan, root, reports, halted)
        emit({'gate': gate['match_id'], 'passed': not halted})
    if not halted:
        for report, halted in scheduled_games(remaining, lambda m: run_one(m, plan, root), parallel_games=plan['parallel_games_after_gate']):
            reports.append(report)
            write_results(plan, root, reports, halted)
            emit({'match_id': report['match_id'], 'status': report['status'], 'winner': report.get('winner'),
                  'all_checks_passed': report.get('all_checks_passed'), 'scheduling_halted': halted})
    return int(halted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=DEFAULT_PLAN)
    parser.add_argument('--seed', type=int, default=16000)
    parser.add_argument('--games', type=int, choices=(6, 14), default=6)
    parser.add_argument('--profile', choices=('pair', 'seven', 'sol-terra'), default='pair')
    parser.add_argument('--parallel-games', type=int, choices=(2, 6), default=2)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create-plan', action='store_true')
    group.add_argument('--run', action='store_true')
    group.add_argument('--rate', action='store_true')
    args = parser.parse_args()
    if args.create_plan:
        plan = create_plan(args.plan, args.seed, args.games, args.profile, parallel_games=args.parallel_games)
        emit({'plan': str(args.plan), 'games': len(plan['matches'])})
        return
    plan = json.loads(args.plan.read_text())
    root = args.plan.parent
    if args.rate:
        verify_plan(plan)
        reports, _ = collect_existing(plan, root)
        ratings = write_results(plan, root, reports, any(not r.get('all_checks_passed') for r in reports))
        emit({'valid_games': ratings['valid_games'], 'ratings': ratings['ratings']})
        return
    # OS-owned lock releases on process exit. Independent launchers cannot share a season.
    with (root/'worker-lock.private.json').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run_season(plan, root))


if __name__ == '__main__':
    main()
