"""Explicit paid/subscription smoke test of persistent Codex seat threads.

Replays authorized recorded snapshots; model proposals do not advance that game.
Raw records go only to *.private.json. No retries, model fallback, or token copying.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict
import argparse
import json
import statistics
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_harness import (CodexGameHarness, CodexPlayer, PROTOCOL, MAX_UTILITIES,
                                   digest, encoded, seat_harness)
from werewolf.providers import ProviderError, validate_action
from werewolf.runner import Runner
from werewolf.engine import Game


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def authorized_events(observation):
    return [{k: deepcopy(event[k]) for k in ('kind', 'day', 'phase', 'text', 'seat', 'data', 'audience') if k in event}
            for event in observation.get('history', [])]


def synthetic_source(decisions, seats):
    """New fictional game data only; never open an existing private archive."""
    game = Game(seed=7319, names=[f'TestPlayer{i}' for i in range(1, 13)], language='zh')
    records = []
    counts = {seat: 0 for seat in seats}
    for batch in range(160):
        if all(count >= decisions for count in counts.values()):
            break
        pending = game.pending()
        if not pending:
            raise ValueError('Synthetic timeline ended before the requested coverage.')
        actions = {}
        for task in pending:
            seat = task['seat']
            observation = game.observe(seat)
            if seat in counts and counts[seat] < decisions:
                records.append({'seat': seat, 'batch_index': batch, 'accepted': True,
                    'request': {'tool_context': {'observation': observation,
                        'decision': {k: task[k] for k in ('kind', 'options')}}}})
                counts[seat] += 1
            options = task['options']
            action = deepcopy(next((o for o in options if o['type'] == 'pass'), options[0]))
            if task['kind'] == 'wolf_attack':
                action = deepcopy(next(o for o in options if o.get('target', 'absent') is None))
            if action['type'] in ('speak', 'discuss'):
                action['text'] = f'{seat}号的合成测试发言：仅按已公开信息判断，身份自称不等于法官确认。'
            actions[task['id']] = action
        game.submit(actions)
    else:
        raise ValueError('Synthetic coverage limit exceeded.')
    return {'inference': records, 'game': {'seed': 7319}, 'language': 'zh',
            'configs': [{'seat': i, 'name': f'TestPlayer{i}', 'personality': 'Analytical and concise.'}
                        for i in range(1, 13)]}


def audit_trial(trial):
    """Reconstruct every delivery, per-turn catalog, tool result, and action."""
    require(trial['protocol'] == PROTOCOL, 'Unknown Codex trial protocol.')
    bindings = set()
    calls = {}
    usage = {}
    accepted = 0
    reused = 0
    errors = []
    event_count = 0
    elapsed = []
    for player in trial['players']:
        config = CodexPlayer(**player['config'])
        require(player['binding'] not in bindings, 'Two players share a thread binding.')
        bindings.add(player['binding'])
        require(player['idle_feed_started_turns'] == 0, 'Idle event injection triggered a generation.')
        deliveries = player['deliveries']
        prefixes = [[]]
        for index, bundle in enumerate(deliveries):
            require(bundle['offset'] == len(prefixes[-1]), 'Duplicated or missing event delivery.')
            require(bundle['delivery'] == 'authorized_events' and bundle['no_action_requested'] is True,
                    'An event delivery is mislabeled.')
            require(('own_identity' in bundle) == (index == 0), 'Identity was redelivered or omitted.')
            require(bundle.get('own_identity', {}).get('seat', config.seat) == config.seat,
                    'Another seat identity was delivered.')
            prefixes.append(prefixes[-1] + bundle['events'])
        event_count += len(prefixes[-1])
        for index, record in enumerate(player['decisions']):
            failed = 'error' in record
            if failed:
                errors.append({'seat': config.seat, 'batch': record['source_batch'], 'category': record.get('category')})
            require(record['seat'] == config.seat and record['observation']['seat'] == config.seat,
                    'A record belongs to another seat.')
            require(len(record['tool_trace']) == 1, 'Unexpected Codex trace shape.')
            entry = record['tool_trace'][0]
            require(entry['transport'] == PROTOCOL and entry['binding'] == player['binding']
                    and entry['seat'] == config.seat and entry['turn_index'] == index,
                    'A decision was routed to the wrong conversation.')
            history = authorized_events(record['observation'])
            require(entry['history_digest'] == digest(history) and entry['history_count'] == len(history),
                    'Decision history differs from its seat observation.')
            require(1 <= entry['delivery_count'] < len(prefixes)
                    and prefixes[entry['delivery_count']] == history,
                    'Conversation contains missing, other-seat, or future events.')
            expected_identity = {k: record['observation'][k] for k in
                                 ('seat', 'role', 'ruleset', 'role_counts', 'wolf_teammates') if k in record['observation']}
            require(deliveries[0]['own_identity'] == expected_identity, 'Seat identity changed or leaked.')
            harness = seat_harness(record['observation'], record['decision'], record['notes_before'])
            require(entry['input'] == {'task': 'act_now', 'briefing': harness.briefing(), 'tool_catalog': harness.tools()},
                    'Actual turn input differs from authorized seat data.')
            require(entry['model'] == config.model and entry['effort'] == config.effort,
                    'Fixed model configuration changed.')
            require(set(entry) <= {'transport', 'binding', 'seat', 'turn_index', 'history_count', 'history_digest',
                                   'delivery_count', 'deliveries', 'input', 'calls', 'usage', 'compactions', 'model', 'effort', 'provider_errors'} | ({'error'} if failed else set()),
                    'Unexpected fields in successful Codex trace.')
            from werewolf.codex_harness import _ERROR_CODES, _HTTP_ERRORS
            for diagnostic in entry.get('provider_errors', []):
                require(set(diagnostic) <= {'code', 'http_status', 'will_retry'} and diagnostic.get('code') in _ERROR_CODES | _HTTP_ERRORS
                        and type(diagnostic.get('will_retry')) is bool, 'Unsafe provider diagnostic.')
                require('http_status' not in diagnostic or type(diagnostic['http_status']) is int and 100 <= diagnostic['http_status'] <= 599, 'Invalid provider status.')
            terminal = None
            utilities = 0
            for call_index, call in enumerate(entry['calls']):
                if failed and 'result' not in call:
                    require(call_index == len(entry['calls'])-1, 'Unexecuted tool is not the final failed call.')
                    break
                require(terminal is None, 'Another call followed a terminal action.')
                expected = harness.call(call['name'], call['arguments'])
                require(call['result'] == expected, 'Tool returned data outside its seat snapshot.')
                calls[call['name']] = calls.get(call['name'], 0) + 1
                if harness.is_action(call['name']):
                    terminal = expected
                else:
                    utilities += 1
            require(utilities <= MAX_UTILITIES, 'Utility budget exceeded.')
            if not failed:
                require(terminal == record['action'], 'Missing or mismatched terminal action.')
                validate_action(terminal, record['decision'])
            require(record['notes_before'] == ('' if index == 0 else
                    player['decisions'][index-1]['action'].get('notes', player['decisions'][index-1]['notes_before'])),
                    'Private notes did not come from this same player.')
            for key, value in entry['usage'].items():
                require(type(value) is int and value >= 0, 'Non-numeric usage or reasoning content in metadata.')
                usage[key] = usage.get(key, 0) + value
            accepted += not failed
            if not failed and 'elapsed_seconds' in record:
                elapsed.append(record['elapsed_seconds'])
        reused += len(player['decisions']) >= 2 and not any('error' in r for r in player['decisions'])
    return {'protocol': PROTOCOL, 'test_kind': trial.get('test_kind', 'recorded-seat-snapshots-not-a-new-game'),
            'players': len(trial['players']), 'unique_thread_bindings': len(bindings),
            'players_with_successful_thread_reuse': reused, 'accepted_actions': accepted,
            'failed_attempts': len(errors), 'errors': errors, 'calls_by_name': calls,
            'delivered_seat_events': event_count, 'idle_feed_started_turns': 0,
            'usage': usage, 'source_archive_replay_verified': trial['source_archive_replay_verified'],
            'synthetic_source_engine_generated': trial.get('test_kind') == 'synthetic-seat-snapshots-not-a-full-AI-game',
            'action_seconds': ({'mean': round(statistics.mean(elapsed), 2), 'median': round(statistics.median(elapsed), 2),
                                'max': max(elapsed)} if elapsed else {}),
            'all_checks_passed': not errors,
            'restart_recovery_tested': False, 'context_compaction_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, nargs='?')
    parser.add_argument('--synthetic', action='store_true', help='Use a new fictional game; read no existing private archive.')
    parser.add_argument('--seats', default=','.join(map(str, range(1, 13))))
    parser.add_argument('--decisions', type=int, default=3)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--effort', choices=['low', 'medium', 'high', 'xhigh', 'max'], default='high')
    parser.add_argument('--exercise-tools', action='store_true', help='Explicit capability-test instruction to exercise private reads and note writes.')
    parser.add_argument('--output', type=Path, default=Path('artifacts/codex-thread-validation.private.json'))
    parser.add_argument('--summary', type=Path, default=Path('artifacts/codex-thread-validation.json'))
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    if args.audit_only:
        if args.archive is None:
            parser.error('Audit-only requires a saved trial.')
        print(json.dumps(audit_trial(json.loads(args.archive.read_text())), ensure_ascii=False, indent=2))
        return
    if not args.output.name.endswith('.private.json'):
        parser.error('Raw output must end with .private.json.')
    seats = [int(v) for v in args.seats.split(',')]
    if not 1 <= args.decisions <= 10 or len(set(seats)) != len(seats) or not seats or not set(seats) <= set(range(1, 13)):
        parser.error('Use unique seats 1–12 and 1–10 decisions.')
    if args.synthetic:
        if args.archive is not None:
            parser.error('Synthetic validation never takes an existing archive.')
        source = synthetic_source(args.decisions, seats)
    else:
        if args.archive is None:
            parser.error('Choose --synthetic or an explicitly authorized source archive.')
        source = json.loads(args.archive.read_text())
        Runner.from_archive(source)  # Reconstruct all historical seat views, no inference.
    selected = {seat: [r for r in source['inference'] if r['seat'] == seat and r['accepted']][:args.decisions]
                for seat in seats}
    if any(len(records) < args.decisions for records in selected.values()):
        parser.error('Some seats have fewer accepted source decisions than requested.')
    configs = {c['seat']: c for c in source['configs']}
    trial = {'protocol': PROTOCOL, 'game_scope': str(uuid.uuid4()), 'source_seed': source['game']['seed'],
             'test_kind': ('synthetic-seat-snapshots-not-a-full-AI-game' if args.synthetic
                           else 'recorded-seat-snapshots-not-a-new-game'),
             'source_archive_replay_verified': not args.synthetic,
             'exercise_tools_requested': args.exercise_tools, 'players': []}

    with CodexGameHarness(trial['game_scope']) as game:
        def run(seat):
            original = configs[seat]
            personality = original['personality'] + (
                ' This is a recorded-state capability test: proposals do not advance the recorded timeline; referee event deliveries do.')
            if args.exercise_tools:
                personality += (' Capability-test requirement: before each action, call read_my_notes and read_my_results once, '
                                'and if you are a Wolf also read_wolf_chat once. Then write a concise private plan '
                                'with write_my_notes before submitting the terminal action. This intentionally exercises tool round trips.')
            config = CodexPlayer(seat, original['name'], model=args.model, effort=args.effort,
                language=source['language'], personality=personality)
            session = game.bind(config)
            output = {'config': asdict(config), 'binding': session.binding, 'decisions': [],
                      'deliveries': [], 'idle_feed_started_turns': 0}
            notes = ''
            for reference in selected[seat]:
                context = reference['request']['tool_context']
                record = {'seat': seat, 'source_batch': reference['batch_index'],
                          'observation': deepcopy(context['observation']), 'decision': deepcopy(context['decision']),
                          'notes_before': notes}
                started = time.monotonic()
                try:
                    before = game.rpc.generation_starts[session.thread_id]
                    session.feed(record['observation'])
                    session.feed(record['observation'])  # Identical delivery is a no-op.
                    after = game.rpc.generation_starts[session.thread_id]
                    output['idle_feed_started_turns'] += after-before
                    result = session.decide(record['observation'], record['decision'], notes)
                    record.update(action=dict(result), tool_trace=result.tool_trace)
                    notes = result.get('notes', notes)
                    status = 'ok'
                except ProviderError as error:
                    record.update(error=str(error), category=getattr(error, 'validation_details', {}).get('category'),
                                  tool_trace=getattr(error, 'tool_trace', []))
                    status = record['category']
                record['elapsed_seconds'] = round(time.monotonic()-started, 2)
                output['decisions'].append(record)
                print(encoded({'seat': seat, 'batch': record['source_batch'], 'status': status,
                               'seconds': record['elapsed_seconds']}), flush=True)
                if 'error' in record:
                    break
            output['deliveries'] = deepcopy(session.deliveries)
            return output

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='codex-validation') as pool:
            futures = {pool.submit(run, seat): seat for seat in seats}
            for future in as_completed(futures):
                try:
                    trial['players'].append(future.result())
                finally:
                    # Save completed players even if another seat exposes a runtime defect.
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(trial, ensure_ascii=False, indent=2))
    trial['players'].sort(key=lambda p: p['config']['seat'])
    args.output.write_text(json.dumps(trial, ensure_ascii=False, indent=2))
    summary = audit_trial(trial)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary['all_checks_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
