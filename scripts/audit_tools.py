"""Audit a private tool-game archive locally; print aggregate metrics only."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf import providers as p
from werewolf.engine import Game
from werewolf.harness import SeatToolHarness
from werewolf.runner import Runner


def size(body):
    return len(json.dumps(body, ensure_ascii=False))


def audit(archive):
    # Also verifies every historical projection against referee replay; no inference.
    Runner.from_archive(archive)
    configs = {c['seat']: p.PlayerConfig(**c) for c in archive['configs']}
    gd = archive['game']
    players = sorted(gd['players'], key=lambda item: item['seat'])
    game = Game(seed=gd['seed'], names=[v['name'] for v in players],
                roles=[v['role'] for v in players], language=archive['language'])
    by_batch = {}
    for record in archive['inference']:
        by_batch.setdefault(record['batch_index'], []).append(record)
    batches = gd['submitted_batches']
    for index in range(len(batches)+1):
        own_notes = archive['checkpoints'][index]['omniscient']['private_notes']
        for record in by_batch.get(index, []):
            context = record['request'].get('tool_context')
            if context is not None:
                seat = record['seat']
                assert context['observation'] == game.observe(seat)
                assert context['private_notes'] == own_notes[str(seat)]
                decision = next(d for d in game.pending() if d['seat'] == seat)
                assert context['decision'] == {k: decision[k] for k in ('kind', 'options')}
        if index < len(batches):
            batch = batches[index]
            original = {d['seat']: d['id'] for d in batch['decisions']}
            game.submit({d['id']: batch['actions'][original[d['seat']]] for d in game.pending()})
    initial, baseline, peak, cumulative = [], [], [], []
    reads = actions = hops = failures = prompt_tokens = completion_tokens = max_hops = 0
    names = {}
    for record in archive['inference']:
        request = record['request']
        if request.get('interaction_mode') != 'tools':
            continue
        config = configs[record['seat']]
        context = request['tool_context']
        h = SeatToolHarness(context['observation'], context['decision'], context['private_notes'], request['language'])
        expected = p.wire_request(config, request)
        assert json.loads(expected['messages'][1]['content']) == h.briefing()
        assert 'tool_context' not in expected
        assert 'history' not in json.loads(expected['messages'][1]['content'])
        initial.append(size(expected))
        legacy = replace(config, interaction_mode='json')
        baseline.append(size(p.wire_request(legacy, p.build_request(legacy, context['observation'], context['decision'], context['private_notes']))))
        bodies = []
        expected_messages = expected["messages"].copy()
        max_hops = max(max_hops, len(record.get('tool_trace', [])))
        for hop in record.get('tool_trace', []):
            hops += 1
            prompt_tokens += hop.get("usage", {}).get("prompt_tokens", 0)
            completion_tokens += hop.get("usage", {}).get("completion_tokens", 0)
            body = hop['wire_request']
            bodies.append(size(body))
            # All continuation data must be reconstructible solely from this
            # seat's frozen gateway, its own assistant calls, and prior results.
            assert body['tools'] == expected['tools']
            assert body['messages'] == expected_messages
            assert all('reasoning_content' not in m for m in body['messages'])
            if hop.get('assistant') and hop['tool_results'] and not h.is_action(hop['tool_results'][0]['name']):
                expected_messages.append(hop['assistant'])
                for call, result in zip(hop['assistant']['tool_calls'], hop['tool_results']):
                    expected_messages.append({'role': 'tool', 'tool_call_id': call['id'],
                                              'content': json.dumps(result['result'], ensure_ascii=False)})
            for result in hop['tool_results']:
                name = result['name']
                assert h.call(name, result['arguments']) == result['result']
                names[name] = names.get(name, 0) + 1
                if h.is_action(name):
                    actions += 1
                    assert result['result'] == record['response']
                else:
                    reads += 1
        if bodies:
            peak.append(max(bodies))
            cumulative.append(sum(bodies))
        failures += bool(record.get('error'))
    if not initial:
        raise ValueError('No tool decisions found.')
    return {'decisions': len(initial), 'accepted': sum(r['accepted'] for r in archive['inference']),
            'failed_attempts': failures, 'model_requests': hops, 'read_calls': reads,
            'action_calls': actions, 'calls_by_name': names,
            'mean_initial_wire_chars': round(statistics.mean(initial)),
            'max_initial_wire_chars': max(initial),
            'mean_equivalent_json_wire_chars': round(statistics.mean(baseline)),
            'initial_wire_reduction_percent': round(100*(1-sum(initial)/sum(baseline)), 1),
            'max_hop_wire_chars': max(peak), 'mean_cumulative_wire_chars': round(statistics.mean(cumulative)),
            'cumulative_wire_reduction_percent': round(100*(1-sum(cumulative)/sum(baseline)), 1),
            'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens, 'max_hops_per_decision': max_hops,
            'day': archive['game']['events'][-1]['day'], 'batches': len(archive['game']['submitted_batches']),
            'winner': archive['game']['winner']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.archive.read_text())), ensure_ascii=False, indent=2))
