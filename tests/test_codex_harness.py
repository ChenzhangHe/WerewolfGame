"""No network calls: persistent thread identity, event delivery, and tool boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import io
import json
import queue
import threading
import unittest

from werewolf.codex_harness import CodexGameHarness, CodexPlayer, CodexRPC, GATEWAY, encoded
from werewolf.providers import ProviderError


def observation(seat=1):
    return {'seat': seat, 'role': 'villager', 'language': 'en', 'day': 1,
            'phase': 'discussion', 'ruleset': 'rules-v1',
            'players': [{'seat': i, 'alive': True, 'name': str(i)} for i in range(1, 13)],
            'history': [{'kind': 'investigation', 'audience': 'private', 'day': 1,
                         'phase': 'night', 'text': f'PRIVATE_SEAT_{seat}'}]}


PASS = {'kind': 'test', 'options': [{'type': 'pass'}]}
SPEECH = {'kind': 'speech', 'options': [{'type': 'speak'}]}


class FakeRPC:
    def __init__(self, cwd):
        self.models = {'gpt-6.1-sol': {'supportedReasoningEfforts': [
            {'reasoningEffort': 'high'}, {'reasoningEffort': 'low'}]}}
        self.threads = {}
        self.mailboxes = {}
        self.plans = {}
        self.deliveries = []
        self.starts = []
        self.interrupts = []
        self.responses = []
        self.turn_counts = {}
        self.closed = False
        self._lock = threading.Lock()

    def register(self, thread):
        result = queue.Queue()
        self.mailboxes[thread] = result
        return result

    def rpc(self, method, params, **kwargs):
        with self._lock:
            if method == 'thread/start':
                thread = f'thread-{len(self.threads)+1}'
                self.threads[thread] = deepcopy(params)
                return {'model': params['model'], 'modelProvider': 'openai',
                        'approvalPolicy': 'never',
                        'instructionSources': [], 'runtimeWorkspaceRoots': [],
                        'sandbox': {'type': 'readOnly', 'networkAccess': False}, 'thread': {'id': thread}}
            thread = params['threadId']
            if method == 'thread/inject_items':
                self.deliveries.append(deepcopy(params))
                return {}
            if method == 'turn/interrupt':
                self.interrupts.append(deepcopy(params))
                return {}
            if method == 'turn/start':
                self.starts.append(deepcopy(params))
                self.turn_counts[thread] = self.turn_counts.get(thread, 0) + 1
                turn = f'turn-{len(self.starts)}'
                plan = self.plans.get(thread, [[('action_pass', {})]]).pop(0)
                target = self.mailboxes[thread]
                for index, item in enumerate(plan):
                    if isinstance(item, dict):
                        target.put(item)
                    else:
                        name, args = item
                        target.put({'id': f'call-{turn}-{index}', 'method': 'item/tool/call', 'params': {
                            'threadId': thread, 'turnId': turn, 'callId': f'{turn}-{index}',
                            'namespace': None, 'tool': 'game_tool',
                            'arguments': {'name': name, 'arguments_json': encoded(args)}}})
                target.put({'method': 'thread/tokenUsage/updated', 'params': {
                    'threadId': thread, 'turnId': turn, 'tokenUsage': {
                        'last': {'inputTokens': 2, 'reasoningOutputTokens': 0},
                        'total': {'inputTokens': 20*self.turn_counts[thread], 'reasoningOutputTokens': 5*self.turn_counts[thread]}}}})
                target.put({'method': 'turn/completed', 'params': {
                    'threadId': thread, 'turn': {'id': turn, 'status': 'completed'}}})
                return {'turn': {'id': turn}}
            raise AssertionError(method)

    def send(self, value):
        with self._lock:
            self.responses.append(deepcopy(value))

    def close(self):
        self.closed = True


class CodexHarnessTests(unittest.TestCase):
    def game(self, name='game-a'):
        game = CodexGameHarness(name, rpc_factory=FakeRPC)
        self.addCleanup(game.close)
        return game

    def player(self, seat=1):
        return CodexPlayer(seat, f'Player {seat}', language='en')

    def test_fixed_thread_for_multiple_turns_and_new_game_has_new_scope(self):
        game = self.game()
        config = self.player()
        first = game.bind(config)
        self.assertIs(first, game.bind(config))
        game.rpc.plans[first.thread_id] = [[('action_pass', {})], [('action_pass', {})]]
        one = first.decide(observation(), PASS)
        two = first.decide(observation(), PASS)
        self.assertEqual(1, len(game.rpc.threads))
        self.assertEqual([first.thread_id]*2, [s['threadId'] for s in game.rpc.starts])
        self.assertEqual([0, 1], [r.tool_trace[0]['turn_index'] for r in (one, two)])
        self.assertEqual(one.tool_trace[0]['binding'], two.tool_trace[0]['binding'])
        self.assertEqual([5, 5], [r.usage['reasoningOutputTokens'] for r in (one, two)])
        other = self.game('game-b').bind(config)
        self.assertNotEqual(first.binding, other.binding)
        with self.assertRaisesRegex(ProviderError, 'fixed'):
            game.bind(replace(config, effort='low'))

    def test_idle_incremental_delivery_is_deduplicated_and_never_starts_a_turn(self):
        game = self.game()
        player = game.bind(self.player())
        obs = observation()
        player.feed(obs)
        player.feed(obs)
        obs['history'].append({'kind': 'speech', 'audience': 'public', 'text': 'new event'})
        delivered = player.feed(obs)
        self.assertEqual([], game.rpc.starts)
        self.assertEqual(2, len(game.rpc.deliveries))
        self.assertEqual(1, delivered[0]['offset'])
        self.assertEqual(1, len(delivered[0]['events']))
        self.assertNotIn('own_identity', delivered[0])
        with self.assertRaisesRegex(ProviderError, 'backward'):
            player.feed(observation())
        changed = deepcopy(obs)
        changed['history'][0]['text'] = 'edited'
        with self.assertRaisesRegex(ProviderError, 'backward'):
            player.feed(changed)
        changed = deepcopy(obs)
        changed['role'] = 'seer'
        with self.assertRaisesRegex(ProviderError, 'identity changed'):
            player.feed(changed)

    def test_concurrent_seats_get_only_own_private_deliveries_and_results(self):
        game = self.game()
        players = [game.bind(self.player(i)) for i in (1, 2)]
        for player in players:
            game.rpc.plans[player.thread_id] = [[('read_my_results', {}), ('action_pass', {})]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p: p.decide(observation(p.config.seat), PASS), players))
        for seat, result in enumerate(results, 1):
            serialized = encoded(result.tool_trace)
            self.assertIn(f'PRIVATE_SEAT_{seat}', serialized)
            self.assertNotIn(f'PRIVATE_SEAT_{3-seat}', serialized)
            thread = players[seat-1].thread_id
            delivered = encoded([d for d in game.rpc.deliveries if d['threadId'] == thread])
            self.assertNotIn(f'PRIVATE_SEAT_{3-seat}', delivered)
        self.assertEqual(2, len({p.thread_id for p in players}))

    def test_current_catalog_rejects_stale_actions_cross_seat_reads_and_wolf_data(self):
        for name, args in [('action_attack', {'target': 2}), ('read_my_notes', {'seat': 2}), ('read_wolf_chat', {})]:
            with self.subTest(name=name):
                game = self.game(name)
                player = game.bind(self.player())
                game.rpc.plans[player.thread_id] = [[(name, args)]]
                with self.assertRaises(ProviderError):
                    player.decide(observation(), PASS)
                self.assertEqual(1, len(game.rpc.starts))
                with self.assertRaisesRegex(ProviderError, 'explicit recovery'):
                    player.decide(observation(), PASS)
        player = self.game('wolf-leak').bind(self.player())
        obs = observation()
        obs['history'].append({'kind': 'wolf_discussion', 'audience': 'private', 'text': 'SECRET_WOLF_CHAT'})
        with self.assertRaises(ProviderError):
            player.feed(obs)
        self.assertEqual([], player.owner.rpc.deliveries)

    def test_private_notes_stage_and_invalid_speech_never_returns_an_action(self):
        game = self.game()
        player = game.bind(self.player())
        game.rpc.plans[player.thread_id] = [[('write_my_notes', {'notes': 'PRIVATE_PLAN'}),
            ('action_speak', {'text': 'Hello </text><parameter name="notes">PRIVATE_PLAN'})]]
        with self.assertRaises(ProviderError) as caught:
            player.decide(observation(), SPEECH, 'OLD_PLAN')
        self.assertEqual('codex_invalid_tool', caught.exception.validation_details['category'])
        self.assertEqual(0, player.turns)
        self.assertEqual(1, len(game.rpc.interrupts))
        self.assertEqual('Invalid game tool arguments.', caught.exception.tool_trace[0]['calls'][-1]['error'])

    def test_valid_notes_followed_by_speech_and_speech_is_not_private_notes(self):
        game = self.game()
        player = game.bind(self.player())
        game.rpc.plans[player.thread_id] = [[('write_my_notes', {'notes': 'PRIVATE_PLAN'}),
                                            ('action_speak', {'text': 'My public statement.'})]]
        result = player.decide(observation(), SPEECH)
        self.assertEqual('PRIVATE_PLAN', result['notes'])
        self.assertEqual('My public statement.', result['text'])
        self.assertEqual(5, result.usage['reasoningOutputTokens'])

    def test_missing_action_post_action_reads_and_budget_excess_fail_without_repair(self):
        for plan in [[], [('action_pass', {}), ('read_my_notes', {})], [('read_my_notes', {})]*13]:
            game = self.game()
            player = game.bind(self.player())
            game.rpc.plans[player.thread_id] = [plan]
            with self.assertRaises(ProviderError):
                player.decide(observation(), PASS)
            self.assertEqual(1, len(game.rpc.starts))
            self.assertEqual(0, player.turns)

    def test_external_or_wrong_turn_requests_fail_closed(self):
        for params in [
            {'threadId': 'thread-1', 'turnId': 'turn-1', 'tool': 'exec_command', 'callId': 'bad'},
            {'threadId': 'thread-1', 'turnId': 'OTHER_TURN', 'tool': 'game_tool', 'callId': 'bad'},
        ]:
            game = self.game()
            player = game.bind(self.player())
            game.rpc.plans[player.thread_id] = [[{'id': 'bad', 'method': 'item/tool/call', 'params': params}]]
            with self.assertRaises(ProviderError):
                player.decide(observation(), PASS)

    def test_thread_has_no_environment_or_loaded_instructions_and_only_game_gateway(self):
        game = self.game()
        player = game.bind(self.player())
        params = game.rpc.threads[player.thread_id]
        self.assertEqual([], params['environments'])
        self.assertEqual([], params['runtimeWorkspaceRoots'])
        self.assertTrue(params['ephemeral'])
        self.assertFalse(params['allowProviderModelFallback'])
        self.assertEqual([GATEWAY], params['dynamicTools'])
        game.close()
        with self.assertRaises(ProviderError):
            game.bind(self.player())
        with self.assertRaises(ProviderError):
            player.feed(observation())

    def test_lost_delivery_acknowledgment_does_not_duplicate_or_reset_thread(self):
        game = self.game()
        player = game.bind(self.player())
        original = game.rpc.rpc
        def lost_ack(method, params, **kwargs):
            if method == 'thread/inject_items':
                original(method, params, **kwargs)
                raise ProviderError('Simulated lost acknowledgment.')
            return original(method, params, **kwargs)
        game.rpc.rpc = lost_ack
        with self.assertRaises(ProviderError):
            player.feed(observation())
        with self.assertRaisesRegex(ProviderError, 'explicit recovery'):
            player.feed(observation())
        self.assertEqual(1, len(game.rpc.threads))
        self.assertEqual(1, len(game.rpc.deliveries))
        self.assertEqual([], game.rpc.starts)

    def test_reader_discards_reasoning_and_plain_assistant_streams(self):
        rpc = CodexRPC.__new__(CodexRPC)
        rpc._lock = threading.Lock()
        rpc._pending = {}
        target = queue.Queue()
        rpc._seats = {'t': target}
        values = [
            {'method': 'item/reasoning/textDelta', 'params': {'threadId': 't', 'delta': 'PRIVATE_REASONING'}},
            {'method': 'item/completed', 'params': {'threadId': 't', 'item': {'type': 'reasoning', 'content': 'PRIVATE_REASONING'}}},
            {'method': 'item/agentMessage/delta', 'params': {'threadId': 't', 'delta': 'NOT_PUBLIC_SPEECH'}},
            {'method': 'turn/completed', 'params': {'threadId': 't', 'turn': {'id': 'turn-1', 'status': 'completed'}}},
        ]
        rpc.process = type('P', (), {'stdout': io.StringIO(''.join(encoded(v)+'\n' for v in values))})()
        rpc._pump()
        result = []
        while not target.empty():
            result.append(target.get())
        self.assertEqual([values[-1], None], result)
        self.assertNotIn('PRIVATE_REASONING', encoded(result))
