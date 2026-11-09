"""Audit a private tool-game archive locally; print aggregate metrics only."""
import argparse
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf import providers as p
from werewolf.engine import Game
from werewolf.runner import Runner


def size(body):
    return len(json.dumps(body, ensure_ascii=False))


def require(condition, message='Archive audit failed.'):
    # Audit checks remain active even when Python is run with -O.
    if not condition:
        raise AssertionError(message)


def audit(archive):
    archive = Runner._canonical(archive)
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
                require(context['observation'] == game.observe(seat))
                require(context['private_notes'] == own_notes[str(seat)])
                decision = next(d for d in game.pending() if d['seat'] == seat)
                require(context['decision'] == {k: decision[k] for k in ('kind', 'options')})
        if index < len(batches):
            batch = batches[index]
            original = {d['seat']: d['id'] for d in batch['decisions']}
            game.submit({d['id']: batch['actions'][original[d['seat']]] for d in game.pending()})
    initial, baseline, peak, cumulative = [], [], [], []
    reads = invalid_reads = actions = hops = failures = prompt_tokens = completion_tokens = max_hops = 0
    accepted = 0
    names = {}
    for record in archive['inference']:
        request = record['request']
        if request.get('interaction_mode') != 'tools':
            continue
        accepted += bool(record['accepted'])
        config = configs[record['seat']]
        context = request['tool_context']
        fresh = p.build_request(config, context['observation'], context['decision'],
                                context['private_notes'], tool_prompt_version=request['prompt_version'])
        require(request == fresh, 'Player request differs from the frozen seat request builder.')
        h = p._seat_harness(request)
        expected = p.wire_request(config, request)
        if request.get('prompt_version') == 'player-tools-v1':
            # Historical v1 explicitly permitted auto; v2 requires native calls.
            expected['tool_choice'] = 'auto'
        require(json.loads(expected['messages'][1]['content']) == h.briefing())
        require('tool_context' not in expected)
        require('history' not in json.loads(expected['messages'][1]['content']))
        initial.append(size(expected))
        legacy = replace(config, interaction_mode='json')
        baseline.append(size(p.wire_request(legacy, p.build_request(legacy, context['observation'], context['decision'], context['private_notes']))))
        bodies = []
        expected_messages = deepcopy(expected["messages"])
        trace = record.get('tool_trace', [])
        max_hops = max(max_hops, len(trace))
        terminal_count = 0
        for hop_index, hop in enumerate(trace):
            hops += 1
            prompt_tokens += hop.get("usage", {}).get("prompt_tokens", 0)
            completion_tokens += hop.get("usage", {}).get("completion_tokens", 0)
            body = hop['wire_request']
            bodies.append(size(body))
            # Check the ENTIRE actual body, including model, schema, settings,
            # tool_choice and absence of unexpected context-bearing fields.
            expected_body = deepcopy(expected)
            expected_body['messages'] = deepcopy(expected_messages)
            if request.get('prompt_version') in {'player-tools-v4', 'player-tools-v5', 'player-tools-v6'} and hop_index == 5:
                # V4's final model request still lets the model choose, but
                # offers terminal actions only after five opportunities to read.
                expected_body['tools'] = [tool for tool in expected_body['tools']
                                          if tool['function']['name'].startswith('action_')]
            require(body == expected_body, 'Wire body differs from the seat-local request.')
            require(all('reasoning_content' not in m for m in body['messages']))
            failed_hop = bool(hop.get('error'))
            if failed_hop:
                require(bool(record.get('error')) and hop_index == len(trace)-1,
                        'Failed hop must end a failed decision attempt.')
            assistant = hop.get('assistant')
            results = hop.get('tool_results', [])
            require(isinstance(results, list))
            if assistant is None:
                require(not results and failed_hop)
                continue
            require(isinstance(assistant, dict) and 'reasoning_content' not in assistant)
            calls = assistant.get('tool_calls', [])
            require(isinstance(calls, list))
            # A failed read may stop after a prefix; successful responses cannot
            # omit, reorder, invent, or relabel any native tool execution.
            require(len(results) <= len(calls))
            require(len(results) == len(calls) or failed_hop,
                    'Tool execution list is incomplete without a failure.')
            if not results:
                require(failed_hop)
                continue
            executed_reads = []
            for result_index, (call, result) in enumerate(zip(calls, results)):
                function = call['function']
                require(call.get('type') == 'function' and isinstance(call.get('id'), str) and bool(call['id']))
                require(result['name'] == function['name'] and result['arguments'] == function['arguments'],
                        'Executed tool differs from the actual assistant call.')
                name = result['name']
                try:
                    reconstructed = h.call(name, result['arguments'])
                except ValueError:
                    require(not h.is_action(name) and failed_hop and bool(record.get('error'))
                            and record.get('validation_details', {}).get('category') == 'invalid_tool_read'
                            and result_index == len(results)-1
                            and result['result'] == {'error': 'Tool request was invalid.'},
                            'Invalid read is not recorded as an explicit safe failure.')
                    invalid_reads += 1
                    continue
                require(name in {tool['function']['name'] for tool in body['tools']},
                        'Executed tool was not offered for this model request.')
                require(reconstructed == result['result'], 'Tool result differs from its authorized seat-local data.')
                names[name] = names.get(name, 0) + 1
                if h.is_action(name):
                    require(len(calls) == len(results) == 1 and hop_index == len(trace)-1
                            and not failed_hop and not record.get('error'),
                            'A terminal action must be the sole call and end a successful attempt.')
                    actions += 1
                    terminal_count += 1
                    require(result['result'] == record['response'], 'Recorded action differs from the native call.')
                else:
                    reads += 1
                    executed_reads.append((call, result))
            if executed_reads and not failed_hop:
                require(len({call['id'] for call in calls}) == len(calls), 'Native tool IDs must be unique within a hop.')
                expected_messages.append(deepcopy(assistant))
                for call, result in executed_reads:
                    expected_messages.append({'role': 'tool', 'tool_call_id': call['id'],
                                              'content': json.dumps(result['result'], ensure_ascii=False)})
        require(terminal_count == (0 if record.get('error') else 1),
                'A successful tool attempt must have exactly one terminal action.')
        peak.append(max(bodies, default=0))
        cumulative.append(sum(bodies))
        failures += bool(record.get('error'))
    if not initial:
        raise ValueError('No tool decisions found.')
    return {'decisions': len(initial), 'accepted': accepted,
            'failed_attempts': failures, 'model_requests': hops, 'read_calls': reads, 'invalid_read_calls': invalid_reads,
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
