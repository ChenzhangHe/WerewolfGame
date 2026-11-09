import copy
import json
import unittest

from werewolf.engine import Game, ROLE_COUNTS

ROLES = ['wolf'] * 4 + ['villager'] * 4 + ['seer', 'witch', 'hunter', 'idiot']


def default_action(decision):
    action = copy.deepcopy(decision['options'][0])
    if action['type'] in ('speak', 'discuss'):
        action['text'] = 'I am considering the public evidence.'
    return action


def submit(game, choose=None):
    actions = {}
    for d in game.pending():
        action = choose(d) if choose else None
        actions[d['id']] = default_action(d) if action is None else action
    game.submit(actions)


def reach(game, kind, limit=300):
    for _ in range(limit):
        if any(d['kind'] == kind for d in game.pending()):
            return
        if not game.pending():
            raise AssertionError(f'Game ended before {kind}')
        submit(game)
    raise AssertionError(f'Did not reach {kind}')


def night(game, attack=None, potion=None, investigate=1):
    reach(game, 'wolf_attack')
    submit(game, lambda d: {'type': 'attack', 'target': attack})
    if any(d['kind'] == 'witch' for d in game.pending()):
        submit(game, lambda d: potion or {'type': 'pass'})
    if any(d['kind'] == 'seer' for d in game.pending()):
        submit(game, lambda d: {'type': 'investigate', 'target': investigate})


class EngineTests(unittest.TestCase):
    def game(self, **kwargs):
        return Game(roles=ROLES, **kwargs)

    def test_standard_lineup_and_private_initial_view(self):
        game = self.game()
        self.assertEqual(len(game.players), 12)
        self.assertEqual(game.observe(5)['role_counts'], ROLE_COUNTS)
        self.assertEqual([p['seat'] for p in game.observe(5)['players'] if 'role' in p], [5])
        self.assertEqual(game.observe(1)['wolf_teammates'], [1, 2, 3, 4])
        self.assertNotIn('wolf_teammates', game.observe(5))
        self.assertNotIn('seed', json.dumps(game.observe(5)))

    def test_invalid_lineup_and_language(self):
        with self.assertRaises(ValueError):
            Game(roles=['wolf'] * 12)
        with self.assertRaises(ValueError):
            Game(language='fr')

    def test_all_projections_and_pending_are_detached(self):
        game = self.game()
        observation = game.observe(5)
        observation['players'][0]['name'] = 'corrupt'
        observation['history'][0]['data']['role_counts']['wolf'] = 99
        game.pending()[0]['options'].clear()
        game.view('omniscient')['players'][0]['role'] = 'villager'
        game.export()['players'][0]['alive'] = False
        self.assertEqual(game.players[1]['role'], 'wolf')
        self.assertTrue(game.players[1]['alive'])
        self.assertEqual(game.observe(5)['role_counts']['wolf'], 4)
        self.assertTrue(game.pending()[0]['options'])

    def test_atomic_validation_and_duplicate_rejection(self):
        game = self.game()
        before = game.export()
        pending = game.pending()
        actions = {d['id']: default_action(d) for d in pending}
        actions[pending[-1]['id']] = {'type': 'explode'}
        with self.assertRaises(ValueError):
            game.submit(actions)
        self.assertEqual(game.export(), before)
        self.assertEqual(game.pending(), pending)
        submit(game)
        with self.assertRaises(ValueError):
            game.submit({d['id']: default_action(d) for d in pending})

    def test_private_wolf_chat_never_reaches_good_or_public(self):
        game = self.game()
        submit(game, lambda d: {'type': 'discuss', 'text': 'SECRET_WOLF_PLAN'})
        self.assertIn('SECRET_WOLF_PLAN', json.dumps(game.observe(2)))
        self.assertNotIn('SECRET_WOLF_PLAN', json.dumps(game.observe(5)))
        self.assertNotIn('SECRET_WOLF_PLAN', json.dumps(game.view()))
        self.assertIn('SECRET_WOLF_PLAN', json.dumps(game.view('omniscient')))

    def test_hidden_assignment_swap_does_not_change_uninformed_view(self):
        roles = list(ROLES)
        roles[7], roles[9] = roles[9], roles[7]
        a, b = self.game(), Game(roles=roles)
        self.assertEqual(a.observe(5), b.observe(5))
        night(a, attack=6)
        night(b, attack=6)
        self.assertEqual(a.observe(5), b.observe(5))
        self.assertEqual(a.pending()[0]['kind'], 'nominate')

    def test_seer_result_only_changes_its_recipient(self):
        roles = list(ROLES)
        roles[0], roles[7] = roles[7], roles[0]
        a, b = self.game(), Game(roles=roles)
        night(a, investigate=1)
        night(b, investigate=1)
        self.assertEqual(a.observe(5), b.observe(5))
        self.assertNotEqual(a.observe(9), b.observe(9))
        self.assertEqual([e for e in a.observe(9)['history'] if e['kind'] == 'investigation'][-1]['data']['result'], 'wolf')
        self.assertEqual([e for e in b.observe(9)['history'] if e['kind'] == 'investigation'][-1]['data']['result'], 'good')

    def test_pending_death_hidden_through_election(self):
        a, b = self.game(), self.game()
        night(a, attack=5)
        night(b, attack=6)
        self.assertEqual(a.observe(7), b.observe(7))
        self.assertEqual([d['seat'] for d in a.pending()], list(range(1, 13)))
        self.assertTrue(all(p['alive'] for p in a.observe(5)['players']))
        self.assertNotIn('dawn', [e['kind'] for e in a.view()['events']])
        # Nomination victims can speak and vote before the announcement.
        submit(a, lambda d: {'type': 'run'} if d['seat'] == 5 else {'type': 'stay'})
        reach(a, 'campaign')
        self.assertEqual(a.pending()[0]['seat'], 5)

    def test_witch_save_consumed_and_future_attack_hidden(self):
        game = self.game()
        night(game, attack=5, potion={'type': 'save'})
        self.assertFalse(game.antidote)
        self.assertTrue(game.players[5]['alive'])
        # Finish first day with no attack/exile using default abstentions.
        reach(game, 'wolf_discussion')
        reach(game, 'wolf_attack')
        submit(game, lambda d: {'type': 'attack', 'target': 6})
        self.assertEqual(game.pending()[0]['kind'], 'witch')
        self.assertNotIn({'type': 'save'}, game.pending()[0]['options'])
        targets = [e for e in game.observe(10)['history'] if e['kind'] == 'witch_target']
        self.assertEqual(len(targets), 1)

    def test_witch_cannot_self_save_or_use_two_potions(self):
        game = self.game()
        reach(game, 'wolf_attack')
        submit(game, lambda d: {'type': 'attack', 'target': 10})
        self.assertNotIn({'type': 'save'}, game.pending()[0]['options'])
        decision = game.pending()[0]
        for action in ({'type': 'save'}, {'type': 'poison', 'target': 5, 'save': True}):
            with self.assertRaises(ValueError):
                game.submit({decision['id']: action})

    def test_attack_and_poison_hunter_prevents_shot_and_reveal(self):
        game = self.game()
        night(game, attack=11, potion={'type': 'poison', 'target': 11})
        reach(game, 'last_words')
        self.assertEqual(game.pending()[0]['seat'], 11)
        self.assertFalse(game.players[11]['alive'])
        self.assertIsNone(game.players[11]['revealed_role'])
        self.assertNotIn('hunter_shot', [e['kind'] for e in game.events])
        dawn = [e for e in game.events if e['kind'] == 'dawn'][-1]
        self.assertEqual(dawn['data']['deaths'], [11])

    def test_hunter_can_shoot_and_idiot_has_no_protection_from_shot(self):
        game = self.game()
        night(game, attack=11)
        reach(game, 'hunter')
        submit(game, lambda d: {'type': 'shoot', 'target': 12})
        self.assertFalse(game.players[12]['alive'])
        self.assertEqual(game.players[11]['revealed_role'], 'hunter')
        self.assertIsNone(game.players[12]['revealed_role'])

    def test_hunter_decline_does_not_reveal_role(self):
        game = self.game()
        night(game, attack=11)
        reach(game, 'hunter')
        submit(game, lambda d: {'type': 'shoot', 'target': None})
        self.assertIsNone(game.players[11]['revealed_role'])
        self.assertNotIn('hunter_declined', [e['kind'] for e in game.view()['events']])

    def test_idiot_exile_survives_and_loses_ballot_rights(self):
        game = self.game()
        reach(game, 'exile_vote')
        submit(game, lambda d: {'type': 'vote', 'target': 12})
        self.assertTrue(game.players[12]['alive'])
        self.assertEqual(game.players[12]['revealed_role'], 'idiot')
        reach(game, 'exile_vote')
        self.assertNotIn(12, [d['seat'] for d in game.pending()])
        self.assertNotIn({'type': 'vote', 'target': 12}, game.pending()[0]['options'])

    def test_exile_tie_runoff_and_second_tie_no_exile(self):
        game = self.game()
        reach(game, 'exile_vote')
        submit(game, lambda d: {'type': 'vote', 'target': 5 if d['seat'] % 2 else 6})
        self.assertEqual(game.pending()[0]['kind'], 'tie_speech')
        reach(game, 'exile_vote')
        self.assertEqual(len(game.pending()), 10)
        submit(game, lambda d: {'type': 'vote', 'target': 5 if d['seat'] % 2 else 6})
        self.assertTrue(all(p['alive'] for p in game.players.values()))
        self.assertIn('no_exile', [e['kind'] for e in game.events])

    def test_sheriff_weight_and_final_speaking_position(self):
        game = self.game()
        reach(game, 'nominate')
        submit(game, lambda d: {'type': 'run'} if d['seat'] == 9 else {'type': 'stay'})
        reach(game, 'direction')
        self.assertEqual(game.sheriff, 9)
        submit(game)
        order = [e['data']['order'] for e in game.events if e['kind'] == 'speaking_order'][-1]
        self.assertEqual(order[-1], 9)
        reach(game, 'exile_vote')
        # Five votes + Sheriff beat six ordinary votes.
        left = {1, 2, 3, 4, 5, 9}
        submit(game, lambda d: {'type': 'vote', 'target': 6 if d['seat'] in left else 7})
        self.assertFalse(game.players[6]['alive'])
        tally = [e['data']['tally'] for e in game.events if e['kind'] == 'exile_ballots'][-1]
        self.assertEqual(tally['6'], 6.5)

    def test_withdrawing_candidates_do_not_get_election_votes(self):
        game = self.game()
        reach(game, 'nominate')
        submit(game, lambda d: {'type': 'run'} if d['seat'] in (1, 2, 9) else {'type': 'stay'})
        reach(game, 'withdraw')
        submit(game, lambda d: {'type': 'withdraw'} if d['seat'] == 1 else {'type': 'remain'})
        reach(game, 'sheriff_vote')
        self.assertEqual([d['seat'] for d in game.pending()], [3, 4, 5, 6, 7, 8, 10, 11, 12])

    def test_double_explosion_interrupts_election_without_new_campaign(self):
        game = self.game()
        reach(game, 'nominate')
        submit(game, lambda d: {'type': 'run'} if d['seat'] in (9, 10) else {'type': 'stay'})
        self.assertEqual(game.pending()[0]['kind'], 'explosion')
        submit(game, lambda d: {'type': 'explode'} if d['seat'] == 1 else {'type': 'pass'})
        self.assertFalse(game.players[1]['alive'])
        self.assertEqual(game.day, 2)
        reach(game, 'withdraw')
        submit(game)
        self.assertEqual(game.pending()[0]['kind'], 'explosion')
        submit(game, lambda d: {'type': 'explode'} if d['seat'] == 2 else {'type': 'pass'})
        self.assertTrue(game._election_done)
        self.assertIsNone(game.sheriff)
        self.assertEqual(game.day, 3)
        self.assertNotIn('campaign', [e['kind'] for e in game.events])

    def test_wolf_attack_first_ends_before_poison_and_hunter(self):
        game = self.game()
        reach(game, 'witch')  # default no attack; reset in next night for controlled ending
        submit(game)
        reach(game, 'wolf_attack')
        # Make this a one-wolf, one-villager endgame while retaining special roles.
        for s in (2, 3, 4, 5, 6, 7):
            game.players[s]['alive'] = False
        submit(game, lambda d: {'type': 'attack', 'target': 8})
        submit(game, lambda d: {'type': 'poison', 'target': 1})
        if game.pending() and game.pending()[0]['kind'] == 'seer':
            submit(game)
        self.assertEqual(game.winner, 'wolves')
        self.assertTrue(game.players[1]['alive'])
        self.assertFalse(game.players[8]['alive'])
        self.assertFalse(game.pending())
        dawn = [e for e in game.events if e['kind'] == 'dawn'][-1]
        self.assertEqual(dawn['data']['deaths'], [8])

    def test_last_wolf_self_attack_ends_before_election(self):
        game = self.game()
        reach(game, 'wolf_attack')
        for seat in (2, 3, 4):
            game.players[seat]['alive'] = False
        submit(game, lambda d: {'type': 'attack', 'target': 1})
        submit(game)
        submit(game)
        self.assertEqual(game.winner, 'good')
        self.assertFalse(game.pending())
        self.assertNotIn('election', [e['kind'] for e in game.events])

    def test_parity_does_not_end_game(self):
        game = self.game()
        for s in (5, 6, 9, 10):
            game.players[s]['alive'] = False
        self.assertIsNone(game._winner_for())

    def test_language_localizes_referee_not_player_speech(self):
        game = self.game(language='zh')
        self.assertEqual(game.observe(5)['language'], 'zh')
        self.assertIn('天黑', game.view()['events'][-1]['text'])
        submit(game, lambda d: {'type': 'discuss', 'text': '玩家原话'})
        self.assertEqual(game.observe(1)['history'][-1]['text'], '玩家原话')

    def test_only_valid_numeric_seats_and_bounded_speech(self):
        game = self.game()
        d = game.pending()[0]
        bad = {x['id']: default_action(x) for x in game.pending()}
        bad[d['id']]['text'] = 'x' * 1201
        with self.assertRaises(ValueError):
            game.submit(bad)
        reach(game, 'wolf_attack')
        bad = {x['id']: {'type': 'attack', 'target': 1.0} for x in game.pending()}
        with self.assertRaises(ValueError):
            game.submit(bad)

    def test_many_complete_scripted_games_no_role_reveal_before_end(self):
        for seed in range(4):
            game = Game(seed=seed)
            for _ in range(1500):
                if not game.pending():
                    break
                def choose(d):
                    if d['kind'] == 'wolf_attack':
                        targets = [o for o in d['options'] if o['target'] is not None and game.players[o['target']]['role'] != 'wolf']
                        return targets[0] if targets else d['options'][0]
                    if d['kind'] == 'exile_vote':
                        return next((o for o in d['options'] if o['target'] is not None), d['options'][0])
                    return None
                submit(game, choose)
            self.assertIn(game.winner, ('wolves', 'good'))
            self.assertFalse(game.pending())
            self.assertTrue(all('role' in p for p in game.view()['players']))


if __name__ == '__main__':
    unittest.main()
