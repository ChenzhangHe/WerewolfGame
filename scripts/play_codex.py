"""Run fresh, fully AI-driven Codex Werewolf games with independent seat threads.

Only newly generated seat-authorized observations leave the process. There is
no input-archive option, automatic retry, default action, or model fallback.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_harness import CodexGameHarness, CodexPlayer, PROTOCOL, encoded
from werewolf.engine import Game
from werewolf.providers import ProviderError
from werewolf.server import NAMES, PERSONALITIES
from scripts.verify_codex import audit_trial, authorized_events, require

PRINT_LOCK = threading.Lock()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + '.tmp' + path.suffix)
    if path.name.endswith('.private.json'):
        temporary = path.with_name(path.stem + '.tmp.private.json')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
    temporary.replace(path)


def visibility(observation, game):
    reveals = {e['seat']: {'explosion': 'wolf', 'hunter_shot': 'hunter', 'idiot_reveal': 'idiot'}[e['kind']]
               for e in game.events if e['audience'] == 'public' and e['kind'] in ('explosion', 'hunter_shot', 'idiot_reveal')}
    for player in observation['players']:
        require(player.get('revealed_role') == reveals.get(player['seat']), 'Role reveal lacks a public skill event.')
        require('role' not in player or player['seat'] == observation['seat'] or player['seat'] in reveals,
                'Another seat hidden role entered an active player observation.')
    require('wolf_teammates' not in observation or observation['role'] == 'wolf', 'Wolf roster reached a non-Wolf.')
    require('potions' not in observation or observation['role'] == 'witch', 'Potion state reached a non-Witch.')


def canonical_game(value):
    """Normalize JSON keys and random referee routing tokens, not game facts."""
    result = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    for batch in result['submitted_batches']:
        seats = {d['id']: d['seat'] for d in batch['decisions']}
        batch['actions'] = {str(seats[key]): action for key, action in batch['actions'].items()}
        batch['decisions'] = [{k: v for k, v in task.items() if k != 'id'} for task in batch['decisions']]
    return result


def audit_match(trial, *, audit_players=audit_trial):
    require(trial['test_kind'] == 'full-live-ai-game', 'Not a live AI match.')
    players = sorted(trial['game']['players'], key=lambda p: p['seat'])
    game = Game(seed=trial['source_seed'], names=[p['name'] for p in players],
                roles=[p['role'] for p in players], language=trial['language'])
    by_seat = {p['config']['seat']: p for p in trial['players']}
    require(set(by_seat) == set(range(1, 13)), 'Missing seat.')
    notes = {seat: '' for seat in by_seat}
    records = {}
    for player in trial['players']:
        require(player['config']['name'] == players[player['config']['seat']-1]['name'], 'Player name changed.')
        for record in player['decisions']:
            records.setdefault(record['source_batch'], []).append(record)
    delivered_counts = {seat: 0 for seat in by_seat}
    histories = {seat: [] for seat in by_seat}
    submitted = trial['game']['submitted_batches']
    for index in range(len(submitted)+1):
        pending = game.pending()
        active = {s for s, p in game.players.items() if p['alive']} | {d['seat'] for d in pending}
        # No final all-role reveal is streamed to player threads after the game ends.
        if not pending:
            active = set()
        for seat in sorted(active):
            player = by_seat[seat]
            observations = game.observe(seat)
            visibility(observations, game)
            if player.get('transport', PROTOCOL) != PROTOCOL:
                require(not player['deliveries'] and not player['delivery_batches'], 'Stateless seat has thread deliveries.')
                continue
            history = authorized_events(observations)
            if delivered_counts[seat] == 0 or history != histories[seat]:
                count = delivered_counts[seat]
                if count == len(player['deliveries']):
                    # A stopped inference/delivery batch may be only partially fed.
                    require(index == len(submitted) and trial['status'] != 'finished', 'An active seat missed events.')
                    continue
                marker = player['delivery_batches'][count]
                if marker != index:
                    require(index == len(submitted) and trial['status'] != 'finished', 'Delivery used a future or incorrect batch.')
                    continue
                bundle = player['deliveries'][count]
                require(bundle['offset'] == len(histories[seat]) and bundle['events'] == history[len(histories[seat]):],
                        'Event stream differs from referee-authorized seat history.')
                delivered_counts[seat] += 1
                histories[seat] = history
        entries = records.get(index, [])
        expected = {d['seat']: d for d in pending}
        require(len({r['seat'] for r in entries}) == len(entries), 'Duplicate seat inference in a batch.')
        for record in entries:
            seat = record['seat']
            require(seat in expected and record['observation'] == game.observe(seat), 'Decision received wrong or future state.')
            require(record['decision'] == {k: expected[seat][k] for k in ('kind', 'options')}, 'Decision used stale legal options.')
            require(record['notes_before'] == notes[seat], 'Decision received another seat or uncommitted notes.')
        if index < len(submitted):
            require(set(expected) == {r['seat'] for r in entries}, 'Committed batch is incomplete.')
            require(all(r.get('committed') and 'error' not in r for r in entries), 'Failed response was committed.')
            actions = {expected[r['seat']]['id']: {k: v for k, v in r['action'].items() if k != 'notes'} for r in entries}
            game.submit(actions)
            for record in entries:
                notes[record['seat']] = record['action'].get('notes', notes[record['seat']])
    require(canonical_game(game.export()) == canonical_game(trial['game']), 'Referee replay diverged from the saved match.')
    require(not set(records)-set(range(len(submitted)+1)), 'Inference belongs to a nonexistent batch.')
    for seat, player in by_seat.items():
        require(delivered_counts[seat] == len(player['deliveries']), 'Dead seat or future history received extra deliveries.')
        require(len(player['delivery_batches']) == len(player['deliveries']), 'Delivery provenance is incomplete.')
    report = audit_players(trial)
    report.update(seed=trial['source_seed'], status=trial['status'], winner=trial['game']['winner'],
                  model=next(iter(by_seat.values()))['config']['model'],
                  effort=next(iter(by_seat.values()))['config'].get('effort', next(iter(by_seat.values()))['config'].get('reasoning_effort')), language=trial['language'],
                  day=game.day, batches=len(submitted), referee_replay_verified=True,
                  committed_actions=sum(bool(r.get('committed')) for p in trial['players'] for r in p['decisions']),
                  explosions=sum(e['kind'] == 'explosion' for e in game.events),
                  public_speeches=sum(e['kind'] in ('speech', 'campaign', 'last_words') for e in game.events),
                  compactions=sum(sum(hop.get('compactions', 0) for hop in r['tool_trace']) for p in trial['players']
                                  for r in p['decisions'] if 'error' not in r),
                  duration_seconds=trial['duration_seconds'])
    roles = {p['seat']: p['role'] for p in players}
    exile_targets = [e['seat'] for e in game.events if e['kind'] == 'exile']
    poison_targets = [e['data']['target'] for e in game.events
                      if e['kind'] == 'witch_action' and e['data']['type'] == 'poison']
    explosion_records = [r for p in trial['players'] for r in p['decisions']
                         if r['decision']['kind'] == 'explosion' and 'error' not in r]
    living = [p for p in game.players.values() if p['alive']]
    report.update(exiled_wolves=sum(roles[s] == 'wolf' for s in exile_targets),
                  exiled_good=sum(roles[s] != 'wolf' for s in exile_targets),
                  witch_poison_wolf_targets=sum(roles[s] == 'wolf' for s in poison_targets),
                  witch_poison_good_targets=sum(roles[s] != 'wolf' for s in poison_targets),
                  explosion_decisions=len(explosion_records),
                  explosion_proposals=sum(r['action']['type'] == 'explode' for r in explosion_records),
                  living_wolves=sum(p['role'] == 'wolf' for p in living),
                  living_villagers=sum(p['role'] == 'villager' for p in living),
                  living_specials=sum(p['role'] not in ('wolf', 'villager') for p in living))
    report['all_checks_passed'] = report['all_checks_passed'] and trial['status'] == 'finished' and bool(game.winner)
    return report


def play(seed, *, output_dir=Path('artifacts'), model='gpt-6.1-sol', effort='high', language='zh',
         max_batches=300, workers=2, harness_factory=CodexGameHarness, progress=True,
         configs=None, roles=None, artifact_stem=None, protocol=PROTOCOL, audit_players=audit_trial):
    stem = artifact_stem or f'codex-match-{seed}'
    if Path(stem).name != stem:
        raise ValueError('Artifact stem must be a plain filename.')
    raw_path = output_dir / f'{stem}.private.json'
    summary_path = output_dir / f'{stem}.json'
    progress_path = output_dir / f'{stem}.progress.json'
    if raw_path.exists() or summary_path.exists():
        raise ValueError('Match artifacts already exist; choose a new seed or output directory.')
    started = time.monotonic()
    game = Game(seed=seed, names=NAMES, roles=roles, language=language)
    configs = configs or [CodexPlayer(i+1, name, model=model, effort=effort, language=language,
                          personality=PERSONALITIES[i]) for i, name in enumerate(NAMES)]
    trial = {'protocol': protocol, 'test_kind': 'full-live-ai-game', 'game_scope': str(uuid.uuid4()),
             'source_seed': seed, 'language': language, 'source_archive_replay_verified': False,
             'status': 'running', 'players': [], 'duration_seconds': 0, 'game': game.export()}
    bindings, sessions = {}, {}
    notes = {seat: '' for seat in range(1, 13)}

    def checkpoint():
        trial['game'] = game.export()
        trial['duration_seconds'] = round(time.monotonic()-started, 2)
        for seat, session in sessions.items():
            bindings[seat]['deliveries'] = deepcopy(session.deliveries)
        save(raw_path, trial)

    try:
        with harness_factory(trial['game_scope']) as harness:
            for config in configs:
                session = harness.bind(config)
                sessions[config.seat] = session
                player = {'config': asdict(config), 'binding': session.binding, 'decisions': [],
                          'deliveries': [], 'delivery_batches': [], 'idle_feed_started_turns': 0,
                          'transport': getattr(session, 'transport', PROTOCOL)}
                bindings[config.seat] = player
                trial['players'].append(player)
            checkpoint()
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f'codex-match-{seed}') as pool:
                while game.pending() and len(game.export()['submitted_batches']) < max_batches:
                    index = len(game.export()['submitted_batches'])
                    pending = game.pending()
                    active = {s for s, p in game.players.items() if p['alive']} | {d['seat'] for d in pending}
                    # The referee remains unchanged until every paid response locks.
                    observations = {seat: game.observe(seat) for seat in active}
                    for seat in sorted(active):
                        visibility(observations[seat], game)
                        before = sessions[seat].generation_count
                        updates = sessions[seat].feed(observations[seat])
                        bindings[seat]['idle_feed_started_turns'] += sessions[seat].generation_count-before
                        if updates:
                            bindings[seat]['delivery_batches'].append(index)

                    def infer(task):
                        seat = task['seat']
                        record = {'seat': seat, 'source_batch': index, 'observation': deepcopy(observations[seat]),
                                  'decision': {k: deepcopy(task[k]) for k in ('kind', 'options')},
                                  'notes_before': notes[seat], 'committed': False}
                        began = time.monotonic()
                        try:
                            result = sessions[seat].decide(record['observation'], record['decision'], notes[seat])
                            record.update(action=dict(result), tool_trace=result.tool_trace)
                        except ProviderError as error:
                            record.update(error=str(error), category=getattr(error, 'validation_details', {}).get('category'),
                                          validation_details=deepcopy(getattr(error, 'validation_details', {})),
                                          tool_trace=getattr(error, 'tool_trace', []))
                        if hasattr(sessions[seat], 'last_request'):
                            record['request'] = deepcopy(sessions[seat].last_request)
                            record['wire_request'] = deepcopy(sessions[seat].last_wire_request)
                        record['elapsed_seconds'] = round(time.monotonic()-began, 2)
                        return record

                    futures = [pool.submit(infer, task) for task in pending]
                    responses = [future.result() for future in futures]
                    for record in responses:
                        bindings[record['seat']]['decisions'].append(record)
                    if any('error' in record for record in responses):
                        trial['status'] = 'error'
                        break
                    tasks = {task['seat']: task for task in pending}
                    game.submit({tasks[r['seat']]['id']: {k: v for k, v in r['action'].items() if k != 'notes'}
                                 for r in responses})
                    for record in responses:
                        record['committed'] = True
                        notes[record['seat']] = record['action'].get('notes', notes[record['seat']])
                    state = {'seed': seed, 'batch': index+1, 'day': game.day, 'phase': game.phase,
                             'winner': game.winner, 'status': 'finished' if game.winner else 'running',
                             'actions': sum(len(p['decisions']) for p in trial['players'])}
                    if progress:
                        save(progress_path, state)
                        with PRINT_LOCK:
                            print(encoded(state), flush=True)
                    if (index+1) % 5 == 0:
                        checkpoint()
                if game.winner:
                    trial['status'] = 'finished'
                elif trial['status'] != 'error':
                    trial['status'] = 'batch_limit'
            checkpoint()
    except Exception as error:
        trial['status'] = 'error'
        trial['host_error'] = {'category': getattr(error, 'validation_details', {}).get('category', type(error).__name__)}
        checkpoint()
        raise
    report = audit_match(trial, audit_players=audit_players)
    save(summary_path, report)
    if progress:
        with PRINT_LOCK:
            print(encoded({'seed': seed, 'result': report}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', default='9101,9102,9103')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--effort', choices=['low', 'medium', 'high', 'xhigh', 'max'], default='high')
    parser.add_argument('--language', choices=['en', 'zh'], default='zh')
    parser.add_argument('--parallel-games', type=int, default=3)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--max-batches', type=int, default=300)
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts'))
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    if args.audit:
        print(json.dumps(audit_match(json.loads(args.audit.read_text())), ensure_ascii=False, indent=2))
        return
    seeds = [int(v) for v in args.seeds.split(',')]
    if (not seeds or len(set(seeds)) != len(seeds) or not all(0 <= seed <= 2**53-1 for seed in seeds)
            or not 1 <= args.parallel_games <= 3 or not 1 <= args.workers <= 4 or not 1 <= args.max_batches <= 500):
        parser.error('Use unique nonnegative seeds, 1–3 parallel games, 1–4 workers, and 1–500 batches.')
    reports = []
    with ThreadPoolExecutor(max_workers=args.parallel_games) as pool:
        futures = {pool.submit(play, seed, output_dir=args.output_dir, model=args.model,
                    effort=args.effort, language=args.language, max_batches=args.max_batches, workers=args.workers): seed
                   for seed in seeds}
        for future in as_completed(futures):
            reports.append(future.result())
    save(args.output_dir / 'codex-matches.json', sorted(reports, key=lambda r: r['seed']))
    if not all(r['all_checks_passed'] for r in reports):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
