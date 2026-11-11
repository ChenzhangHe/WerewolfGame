"""Run the frozen twelve-game mixed-provider pilot, retaining every paid attempt."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from dataclasses import asdict
import argparse
from functools import partial
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf import providers as p
from werewolf.codex_harness import CodexGameHarness, CodexPlayer, PROTOCOL as CODEX_PROTOCOL
from werewolf.credentials import load_local_credentials
from werewolf.league import PROTOCOL, PROTOCOL_V2, PROTOCOL_V3, SOL, DEEPSEEK, SOL_V2, DEEPSEEK_V13, DEEPSEEK_V14, schedule, configs_for, scoreboard, validate_schedule, season_entries
from scripts.audit_tools import audit_records, require
from scripts.play_codex import play, save, audit_match
from scripts.verify_codex import audit_trial


class DeepSeekSeat:
    """Stateless v12 decision context plus own committed notes, with no idle inference."""
    transport = 'deepseek-native-tools-v12'
    generation_count = 0

    def __init__(self, config, prompt_version='player-tools-v14'):
        self.prompt_version = prompt_version
        self.transport = 'deepseek-native-tools-'+prompt_version.removeprefix('player-tools-')
        self.config = config
        self.binding = str(uuid.uuid4())  # Host routing only; not a conversation ID.
        self.deliveries = []

    def feed(self, observation):
        # DeepSeek reads a fresh, seat-local snapshot on demand during decide().
        return []

    def decide(self, observation, decision, notes=''):
        self.last_request = p.build_request(self.config, observation, decision, notes,
                                            tool_prompt_version=self.prompt_version)
        self.last_wire_request = p.wire_request(self.config, self.last_request)
        return p.decide(self.config, self.last_request)


class MixedHarness:
    def __init__(self, game_id, codex_factory=CodexGameHarness, prompt_version='player-tools-v14'):
        self.codex = codex_factory(game_id)
        self.prompt_version = prompt_version

    def __enter__(self):
        self.codex.__enter__()
        return self

    def __exit__(self, *args):
        return self.codex.__exit__(*args)

    def bind(self, config):
        return self.codex.bind(config) if isinstance(config, CodexPlayer) else DeepSeekSeat(config, self.prompt_version)


def audit_players(trial):
    require(trial['protocol'] in (PROTOCOL, PROTOCOL_V2, PROTOCOL_V3), 'Unknown mixed-game protocol.')
    version = {PROTOCOL: 'player-tools-v12', PROTOCOL_V2: 'player-tools-v13', PROTOCOL_V3: 'player-tools-v14'}[trial['protocol']]
    transport = 'deepseek-native-tools-'+version.removeprefix('player-tools-')
    codex_players = [player for player in trial['players'] if player['transport'] == CODEX_PROTOCOL]
    deepseek_players = [player for player in trial['players'] if player['transport'] == transport]
    require(len(codex_players) == len(deepseek_players) == 6, 'Mixed game requires six seats per configuration.')
    codex = audit_trial({**trial, 'protocol': CODEX_PROTOCOL, 'players': codex_players})
    configs = {player['config']['seat']: p.PlayerConfig(**player['config']) for player in deepseek_players}
    records = []
    for player in deepseek_players:
        require(player['idle_feed_started_turns'] == 0 and not player['deliveries'], 'Unexpected stateless deliveries.')
        for record in player['decisions']:
            request = record['request']
            require(request == p.build_request(configs[record['seat']], record['observation'],
                                                record['decision'], record['notes_before'],
                                                tool_prompt_version=version), 'DeepSeek request scope changed.')
            require(record['wire_request'] == p.wire_request(configs[record['seat']], request), 'Initial DeepSeek body changed.')
            normalized = {**record, 'accepted': bool(record['committed']), 'response': record.get('action', {})}
            records.append(normalized)
    native = audit_records(configs, records) if records else {'accepted': 0, 'failed_attempts': 0}
    return {'protocol': trial['protocol'], 'test_kind': trial['test_kind'], 'players': 12,
            'accepted_actions': codex['accepted_actions']+sum('error' not in r for r in records),
            'failed_attempts': codex['failed_attempts']+native['failed_attempts'],
            'codex': codex, 'deepseek': native,
            'all_checks_passed': codex['all_checks_passed'] and not native['failed_attempts']}


def source_fingerprint():
    root = Path(__file__).resolve().parents[1]
    paths = ['werewolf/engine.py', 'werewolf/providers.py', 'werewolf/chat_stream.py', 'werewolf/strict_tools.py', 'werewolf/native_transaction.py', 'werewolf/harness.py', 'werewolf/briefing_rules.py', 'werewolf/calculations.py',
             'werewolf/codex_harness.py', 'werewolf/league.py', 'scripts/play_codex.py',
             'scripts/play_league.py', 'scripts/audit_tools.py', 'scripts/verify_codex.py',
             'werewolf/server.py', 'docs/rules-v1.md']
    digest = hashlib.sha256()
    for name in paths:
        path = root/name
        digest.update(name.encode()+b'\0'+path.read_bytes())
    return digest.hexdigest()


def create_plan(output, seed):
    if output.exists():
        raise ValueError('Plan already exists; refusing to overwrite the preregistration.')
    matches = schedule(seed, version=3)
    plan = {'protocol': PROTOCOL_V3, 'source_fingerprint': source_fingerprint(), 'matches': matches,
            'configs': {m['id']: [asdict(c) for c in configs_for(m)] for m in matches},
            'scoring': 'team-outcome-v1', 'max_batches': 300, 'workers_per_game': 2, 'codex_turn_timeout_seconds': 600, 'halt_scheduling_on_error': True,
            'deepseek_transport': {'stream': True, 'strict': True, 'attempts': 6, 'idle_seconds': 90, 'request_seconds': 900,
                                   'explicit_confirm': True, 'validation_feedback_limit': 2, 'decision_seconds': 1200, 'allow_finish_eof': True},
            'initial_gate_games': 1,
            'failure_policy': 'Retain failed games; logged transport recovery and bounded native validation feedback, no argument rewriting, default action, replacement or thread recreation.',
            'schedule_policy': 'Six paired layouts, complementary entries; fresh games and threads from the opening.',
            'entries': {SOL_V2: 'gpt-6.1-sol high, ChatGPT subscription, persistent seat Codex thread',
                        DEEPSEEK_V14: 'deepseek-flash high, native v14 SSE tools, explicit confirmation and bounded tool rejection feedback'}}
    save(output, plan)
    return plan


def verify_plan(plan, *, execution=False):
    require(plan['protocol'] in (PROTOCOL, PROTOCOL_V2, PROTOCOL_V3) and plan['scoring'] == 'team-outcome-v1', 'Unknown plan version.')
    if execution:
        require(plan['protocol'] == PROTOCOL_V3, 'Older experiments are audit-only; create a fresh v3 plan.')
        require(plan['source_fingerprint'] == source_fingerprint(), 'Code changed after preregistration; do not mix protocols.')
    validate_schedule(plan['matches'])
    require(plan['max_batches'] == 300 and plan['workers_per_game'] == (4 if plan['protocol'] == PROTOCOL else 2), 'Frozen execution limits changed.')
    require(season_entries(plan['matches']) == {PROTOCOL: (SOL, DEEPSEEK), PROTOCOL_V2: (SOL_V2, DEEPSEEK_V13), PROTOCOL_V3: (SOL_V2, DEEPSEEK_V14)}[plan['protocol']], 'Configuration version mismatch.')
    if plan['protocol'] in (PROTOCOL_V2, PROTOCOL_V3):
        require(plan.get('halt_scheduling_on_error') is True, 'Failure circuit breaker disabled.')
        expected_transport = {'stream': True, 'strict': True, 'attempts': 3, 'idle_seconds': 90, 'request_seconds': 900}
        if plan['protocol'] == PROTOCOL_V3:
            expected_transport.update(attempts=6, explicit_confirm=True, validation_feedback_limit=2, decision_seconds=1200, allow_finish_eof=True)
            require(plan['initial_gate_games'] == 1, 'Initial game gate changed.')
        require(plan['codex_turn_timeout_seconds'] == 600 and plan['deepseek_transport'] == expected_transport, 'Transport policy changed.')
    for match in plan['matches']:
        require(plan['configs'][match['id']] == [asdict(c) for c in configs_for(match)], 'Frozen configurations changed.')


def verify_trial(trial, match, plan):
    require(trial['protocol'] == plan['protocol'], 'Executed protocol differs from preregistration.')
    require(trial['source_seed'] == match['seed'], 'Wrong game seed.')
    require([p['role'] for p in sorted(trial['game']['players'], key=lambda p: p['seat'])] == match['roles'], 'Role layout changed.')
    require([p['config'] for p in sorted(trial['players'], key=lambda p: p['config']['seat'])] == plan['configs'][match['id']],
            'Game configuration differs from preregistration.')
    return audit_match(trial, audit_players=audit_players)


def run_one(match, plan, output_dir):
    verify_plan(plan, execution=True)
    stem = match['id']
    if any((output_dir/f'{stem}{suffix}').exists() for suffix in ('.json', '.private.json')):
        raise ValueError('Existing game evidence must not be overwritten.')
    with (output_dir/f'{stem}.claim.private.json').open('x') as claim:
        json.dump({'match_id': stem, 'attempt_claimed': True}, claim)
    try:
        play(match['seed'], configs=configs_for(match), roles=match['roles'], protocol=plan['protocol'],
             artifact_stem=stem, output_dir=output_dir, workers=plan['workers_per_game'],
             max_batches=plan['max_batches'], harness_factory=partial(MixedHarness, prompt_version='player-tools-v14'), audit_players=audit_players)
        trial = json.loads((output_dir/f'{stem}.private.json').read_text())
        report = verify_trial(trial, match, plan)
        report.update(match_id=stem, pair=match['pair'], model='mixed', effort='high')
    except Exception as error:
        # Keep raw evidence written by play(). Never hide or replace this attempted game.
        report = {'match_id': stem, 'pair': match['pair'], 'seed': match['seed'], 'status': 'host_or_audit_error',
                  'all_checks_passed': False, 'category': getattr(error, 'validation_details', {}).get('category', type(error).__name__)}
    save(output_dir/f'{stem}.json', report)
    return report


def scheduled_games(matches, runner, *, parallel_games=2):
    """Do not launch another game after a failure; collect all in-flight evidence."""
    pending = iter(matches)
    halted = False
    with ThreadPoolExecutor(max_workers=parallel_games) as pool:
        active = {}
        def fill():
            while not halted and len(active) < parallel_games:
                match = next(pending, None)
                if match is None:
                    break
                active[pool.submit(runner, match)] = match
        fill()
        while active:
            completed, _ = wait(active, return_when=FIRST_COMPLETED)
            results = []
            for future in completed:
                active.pop(future)
                results.append(future.result())
            halted = halted or any(not r.get('all_checks_passed') for r in results)
            for result in sorted(results, key=lambda r: r['match_id']):
                yield result, halted
            fill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path('artifacts/mixed-v3/plan.private.json'))
    parser.add_argument('--create-plan', action='store_true')
    parser.add_argument('--seed', type=int, default=14000)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--parallel-games', type=int, choices=(1, 2, 3), default=2)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--max-new-games', type=int, choices=range(1, 13), default=12,
                        help='Limit newly started games; use 1 for the preregistered first-game gate.')
    args = parser.parse_args()
    if args.create_plan:
        create_plan(args.plan, args.seed)
        print(json.dumps({'plan_created': str(args.plan), 'games': 12}))
        return
    plan = json.loads(args.plan.read_text())
    verify_plan(plan)
    if args.audit:
        trial = json.loads(args.audit.read_text())
        match = next(m for m in plan['matches'] if m['id'] == args.audit.name.removesuffix('.private.json'))
        print(json.dumps(verify_trial(trial, match, plan), ensure_ascii=False))
        return
    if not args.run:
        parser.error('Choose --create-plan, --run or --audit.')
    verify_plan(plan, execution=True)
    load_local_credentials()
    for config in configs_for(plan['matches'][0]):
        if isinstance(config, p.PlayerConfig):
            p.check_credentials(config)
    output_dir = args.plan.parent
    reports, remaining = [], []
    # Resume the season between games only: no live thread restoration or replacement attempts.
    for match in plan['matches']:
        summary = output_dir/f"{match['id']}.json"
        raw = output_dir/f"{match['id']}.private.json"
        if summary.exists():
            report = json.loads(summary.read_text())
            require(report['match_id'] == match['id'], 'Existing summary has wrong match ID.')
            if report.get('all_checks_passed'):
                require(raw.exists(), 'Completed game lacks private evidence.')
                verify_trial(json.loads(raw.read_text()), match, plan)
            reports.append(report)
        elif raw.exists() or (output_dir/f"{match['id']}.claim.private.json").exists():
            reports.append({'match_id': match['id'], 'status': 'interrupted', 'all_checks_passed': False})
        else:
            remaining.append(match)
    if not reports and args.max_new_games != 1:
        parser.error('First run must use --max-new-games 1 for the preregistered gate; resume normally after it passes.')
    remaining = remaining[:args.max_new_games]
    halted = False
    def aggregate():
        save(output_dir/'mixed-pilot-results.json', {'reports': sorted(reports, key=lambda r: r['match_id']),
            'scheduler': {'halted_on_failure': halted, 'parallel_games': args.parallel_games, 'max_new_games': args.max_new_games,
                          'unfinished_games': [m['id'] for m in plan['matches'] if m['id'] not in {r['match_id'] for r in reports}]},
            'scoreboard': scoreboard(plan['matches'], reports)})
    aggregate()
    for report, halted in scheduled_games(remaining, partial(run_one, plan=plan, output_dir=output_dir),
                                          parallel_games=args.parallel_games):
        reports.append(report)
        aggregate()
        print(json.dumps({'game_result': report, 'scheduling_halted': halted}, ensure_ascii=False), flush=True)
    if not all(r.get('all_checks_passed') for r in reports) or (len(reports) != 12 and args.max_new_games == 12):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
