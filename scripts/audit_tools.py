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


def require_reasoning_metadata(value):
    require(isinstance(value, dict) and set(value) == {'chars', 'json_chars', 'sha256'},
            'Invalid reasoning metadata shape.')
    require(type(value['chars']) is int and value['chars'] >= 0
            and type(value['json_chars']) is int
            and value['chars'] + 2 <= value['json_chars'] <= 6 * value['chars'] + 2,
            'Invalid reasoning metadata length.')
    require(isinstance(value['sha256'], str) and len(value['sha256']) == 64
            and all(c in '0123456789abcdef' for c in value['sha256']),
            'Invalid reasoning metadata digest.')


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
        reveal_kinds = {'hunter_shot': 'hunter', 'idiot_reveal': 'idiot', 'explosion': 'wolf'}
        public_reveals = {e['seat']: reveal_kinds[e['kind']] for e in game.events
                          if e['audience'] == 'public' and e['kind'] in reveal_kinds}
        for record in by_batch.get(index, []):
            context = record['request'].get('tool_context')
            if context is not None:
                seat = record['seat']
                observation = context['observation']
                for player in observation['players']:
                    require(player.get('revealed_role') == public_reveals.get(player['seat']),
                            'A role reveal lacks a published ability event.')
                    require('role' not in player or player['seat'] == seat or player['seat'] in public_reveals or bool(observation.get('winner')),
                            'An unrevealed other-seat role reached a player observation.')
                require('wolf_teammates' not in observation or observation['role'] == 'wolf',
                        'A non-Wolf received the wolf team roster.')
                require('potions' not in observation or observation['role'] == 'witch',
                        'A non-Witch received potion resources.')
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
        record_reads = 0
        expected_reasoning = []
        thinking = config.thinking == "enabled"
        for hop_index, hop in enumerate(trace):
            hops += 1
            prompt_tokens += hop.get("usage", {}).get("prompt_tokens", 0)
            completion_tokens += hop.get("usage", {}).get("completion_tokens", 0)
            body = hop['wire_request']
            if thinking:
                require(hop.get('reasoning_passback') == expected_reasoning,
                        'Reasoning passback differs from this decision prior assistant states.')
                actual_chars = size(body) + sum(m['json_chars'] + len(', "reasoning_content": ')
                                              for m in expected_reasoning)
                require(hop.get('wire_request_chars') == actual_chars,
                        'Thinking wire size does not match its redacted metadata.')
                bodies.append(actual_chars)
            else:
                require('reasoning_passback' not in hop and 'assistant_reasoning' not in hop,
                        'Disabled thinking must not retain reasoning state.')
                bodies.append(size(body))
            # Check the ENTIRE actual body, including model, schema, settings,
            # tool_choice and absence of unexpected context-bearing fields.
            expected_body = deepcopy(expected)
            expected_body['messages'] = deepcopy(expected_messages)
            limits = p.tool_protocol_limits(request['prompt_version'])
            action_phase = limits['final_action_stage'] and (
                hop_index == limits['model_requests'] - 1 or
                (request['prompt_version'] in {'player-tools-v7', 'player-tools-v8', 'player-tools-v9', 'player-tools-v10', 'player-tools-v11'} and record_reads >= limits['read_calls']))
            if action_phase:
                # Verify the versioned action-only stage and host transition notice.
                expected_body['tools'] = [tool for tool in expected_body['tools']
                                          if tool['function']['name'].startswith('action_')]
                if request['prompt_version'] in {'player-tools-v7', 'player-tools-v8', 'player-tools-v9', 'player-tools-v10', 'player-tools-v11'}:
                    tool_names = ", ".join(tool['function']['name'] for tool in expected_body['tools'])
                    expected_body['messages'][0]['content'] += (
                        "\nACTION PHASE: Reading is now closed for this decision. "
                        "Call exactly one offered action function now: " + tool_names +
                        ". No read functions are available. Do not request another page. "
                        "Choose your action using the information already retrieved.")
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
            if thinking:
                if 'assistant_reasoning' in hop:
                    require_reasoning_metadata(hop['assistant_reasoning'])
                else:
                    require(failed_hop, 'Successful thinking response lacks state metadata.')
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
                    record_reads += 1
                    executed_reads.append((call, result))
            if executed_reads and not failed_hop:
                require(len({call['id'] for call in calls}) == len(calls), 'Native tool IDs must be unique within a hop.')
                if thinking:
                    require_reasoning_metadata(hop.get('assistant_reasoning'))
                    expected_reasoning.append({'message_index': len(expected_messages),
                                               **hop['assistant_reasoning']})
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
