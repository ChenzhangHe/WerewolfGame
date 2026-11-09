"""Explicit paid, seat-scoped single-decision probes; never advance a game.

Modes use identical initial requests within the chosen JSON or native-tools protocol.
Only the selected actor's already-authorized observation and notes are sent.
Provider reasoning is neither requested for display nor retained in the results.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf import providers as p
from werewolf.credentials import load_local_credentials


def selected_records(archive):
    records = [r for r in archive['inference'] if r.get('accepted') and r['kind'] == 'explosion']
    neutral = next(r for r in records if r['seat'] == 8 and r['request']['tool_context']['observation']['day'] == 1)
    first = next(r for r in records if r.get('response', {}).get('type') == 'explode' and r['seat'] == 8)
    pressured = next(r for r in records if r.get('response', {}).get('type') == 'explode' and r['seat'] == 10)
    def last_wolf(record):
        observation = record['request']['tool_context']['observation']
        living = {v['seat'] for v in observation['players'] if v['alive']}
        return len(living.intersection(observation.get('wolf_teammates', []))) == 1
    last = next(r for r in records if last_wolf(r))
    return [('neutral', neutral), ('first_explosion', first), ('pressured', pressured), ('last_wolf', last)]


def prepare(config, record, mode, interaction_mode="json"):
    config = replace(config, interaction_mode=interaction_mode, temperature=None, max_tokens=32768,
                     thinking='enabled' if mode == 'high' else 'disabled',
                     reasoning_effort='high' if mode == 'high' else None)
    context = record['request']['tool_context']
    assembled = p.build_request(config, context['observation'], context['decision'], context['private_notes'])
    return config, assembled, p.wire_request(config, assembled)


def run_one(job):
    name, record, config, mode, repetition, *extra = job
    interaction_mode = extra[0] if extra else "json"
    config, assembled, body = prepare(config, record, mode, interaction_mode)
    result = {'case': name, 'seat': record['seat'], 'source_batch': record['batch_index'],
              'mode': mode, 'repetition': repetition, 'config': asdict(config), 'wire_request': body}
    started = time.monotonic()
    try:
        if interaction_mode == 'tools':
            answer = p.decide(config, assembled)
            result.update(action=dict(answer), action_content=answer.raw_text, model=answer.reported_model,
                          usage=answer.usage, tool_trace=answer.tool_trace)
            result['elapsed_seconds'] = round(time.monotonic() - started, 2)
            return result
        response = p._send_http(config, body, attempts=1)
        result['model'] = response.get('model')
        result['usage'] = response.get('usage', {})
        choice = response['choices'][0]
        result['finish_reason'] = choice.get('finish_reason')
        result['action_content'] = choice['message'].get('content')
        if choice.get('finish_reason') != 'stop':
            raise ValueError('The provider did not complete an action.')
        action = json.loads(result['action_content'])
        p.validate_action(action, assembled['input']['decision'])
        result['action'] = action
    except (p.ProviderError, ValueError, KeyError, TypeError, IndexError) as exc:
        result['error'] = str(exc) if isinstance(exc, (p.ProviderError, ValueError)) else type(exc).__name__
        if hasattr(exc, 'tool_trace'):
            result['tool_trace'] = exc.tool_trace
        if hasattr(exc, 'validation_details'):
            result['validation_details'] = exc.validation_details
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='Trusted local private v9 game archive.')
    parser.add_argument('--interaction-mode', choices=('json', 'tools'), default='json')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--output', type=Path, default=Path('artifacts/strategy-probe.private.json'))
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5 or not args.output.name.endswith('.private.json'):
        parser.error('Use 1–5 repeats and a .private.json output.')
    archive = json.loads(args.archive.read_text())
    load_local_credentials()
    configs = {c['seat']: p.PlayerConfig(**c) for c in archive['configs']}
    jobs = [(name, record, configs[record['seat']], mode, repetition, args.interaction_mode)
            for name, record in selected_records(archive)
            for repetition in range(args.repeats) for mode in ('off', 'high')]
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(run_one, jobs):
            results.append(result)
            args.output.write_text(json.dumps({'profile': 'strategy-probe-v2-native' if args.interaction_mode == 'tools' else 'strategy-probe-v1-json', 'results': results}, ensure_ascii=False))
            print(json.dumps({k: result.get(k) for k in ('case', 'mode', 'repetition', 'elapsed_seconds', 'error')}
                             | {'action': result.get('action', {}).get('type')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
