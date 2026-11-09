"""Mechanical checks cannot consult hidden roles or unpublished votes."""
import copy
import unittest

from werewolf.calculations import exile_votes, win_hypothesis, ROLE_COUNTS
from werewolf.harness import SeatToolHarness
from werewolf import providers as p


ROLES = {1: 'hunter', 2: 'villager', 3: 'idiot', 4: 'wolf', 5: 'villager', 6: 'villager',
         7: 'wolf', 8: 'wolf', 9: 'villager', 10: 'wolf', 11: 'witch', 12: 'seer'}


def players():
    return [{'seat': s, 'alive': s in (1, 3, 5, 7, 9), 'revealed_role': 'wolf' if s in (4, 8, 10) else None,
             'sheriff': False} for s in range(1, 13)]


def assignments():
    return [{'seat': s, 'role': role} for s, role in ROLES.items()]


class CalculationTests(unittest.TestCase):
    def test_self_claimed_idiot_still_votes_and_actual_reveal_removes_rights(self):
        roster = players()
        ballots = [{'seat': s, 'target': 7 if s != 7 else 9} for s in (1, 3, 5, 7, 9)]
        result = exile_votes(roster, ballots)
        self.assertEqual({'7': 4, '9': 1}, result['tally'])
        self.assertEqual([7], result['leaders'])
        self.assertTrue(result['all_ordinary_voters_supplied'])
        roster[2]['revealed_role'] = 'idiot'
        with self.assertRaises(ValueError):
            exile_votes(roster, ballots)

    def test_sheriff_weight_ties_abstentions_and_missing_ballots(self):
        roster = players()
        roster[0]['sheriff'] = True
        result = exile_votes(roster, [{'seat': 1, 'target': 7}, {'seat': 3, 'target': 9}, {'seat': 5, 'target': None}])
        self.assertEqual({'7': 1.5, '9': 1}, result['tally'])
        self.assertEqual([7, 9], result['unspecified_voters'])
        tied = exile_votes(players(), [{'seat': 1, 'target': 7}, {'seat': 3, 'target': 9}])
        self.assertEqual([7, 9], tied['leaders'])
        self.assertEqual([], exile_votes(players(), [{'seat': 1, 'target': None}])['leaders'])

    def test_illegal_or_duplicate_proposed_ballots_are_not_tallied(self):
        for ballots in ([{'seat': True, 'target': 7}], [{'seat': 2, 'target': 7}],
                        [{'seat': 1, 'target': 2}], [{'seat': 1, 'target': 7}] * 2):
            with self.subTest(ballots=ballots), self.assertRaises(ValueError):
                exile_votes(players(), ballots)

    def test_living_idiot_prevents_false_all_specials_dead_prediction(self):
        result = win_hypothesis(players(), 7, 'wolf', [4, 7, 8, 10], assignments(), [1])
        self.assertTrue(result['valid_hypothesis'])
        self.assertEqual([3], result['living_specials_under_assumptions'])
        self.assertIsNone(result['winner_under_assumptions'])
        result = win_hypothesis(players(), 7, 'wolf', [4, 7, 8, 10], assignments(), [1, 3])
        self.assertEqual('wolves', result['winner_under_assumptions'])
        result = win_hypothesis(players(), 7, 'wolf', [4, 7, 8, 10], assignments(), [7, 5, 9])
        self.assertEqual('good', result['winner_under_assumptions'])

    def test_known_team_conflicts_return_feedback_not_secret_identity(self):
        assumptions = assignments()
        assumptions[6]['role'], assumptions[4]['role'] = assumptions[4]['role'], assumptions[6]['role']
        result = win_hypothesis(players(), 7, 'wolf', [4, 7, 8, 10], assumptions, [])
        self.assertFalse(result['valid_hypothesis'])
        self.assertIn('conflicts', result)
        self.assertNotIn('winner_under_assumptions', result)

    def test_unrevealed_other_role_changes_do_not_change_calculator_output(self):
        first = players()
        second = copy.deepcopy(first)
        first[10]['role'], first[11]['role'] = 'witch', 'seer'
        second[10]['role'], second[11]['role'] = 'seer', 'witch'
        self.assertEqual(win_hypothesis(first, 7, 'wolf', [4, 7, 8, 10], assignments(), []),
                         win_hypothesis(second, 7, 'wolf', [4, 7, 8, 10], assignments(), []))

    def test_harness_tools_and_upfront_notes_are_versioned(self):
        config = p.deepseek_flash_config(7, 'Echo')
        observation = {'seat': 7, 'role': 'wolf', 'language': 'zh', 'day': 4, 'phase': 'discussion',
                       'players': players(), 'history': [], 'wolf_teammates': [4, 7, 8, 10],
                       'role_counts': ROLE_COUNTS}
        decision = {'kind': 'explosion', 'options': [{'type': 'pass'}, {'type': 'explode'}]}
        old = p._build_tools_request(config, observation, decision, 'MY_DAY_PLAN', 'zh', version='player-tools-v10')
        new = p._build_tools_request(config, observation, decision, 'MY_DAY_PLAN', 'zh', version='player-tools-v11')
        self.assertNotIn('prior_private_notes', old['input'])
        self.assertEqual('MY_DAY_PLAN', new['input']['prior_private_notes'])
        self.assertEqual('daytime_continuation', new['input']['current_task'])
        self.assertTrue(new['input']['core_public_rules'])
        h = p._seat_harness(new)
        self.assertTrue({'action_pass', 'action_explode'}.issubset(t['function']['name'] for t in h.tools()))
        self.assertEqual({'type': 'explode'}, h.call('action_explode', {}))
        result = h.call('check_win_hypothesis', {'assignments': assignments(), 'additional_deaths': [1]})
        self.assertIsNone(result['winner_under_assumptions'])
        with self.assertRaises(ValueError):
            p._seat_harness(old).call('check_win_hypothesis', {'assignments': assignments(), 'additional_deaths': []})

    def test_new_briefing_and_helpers_keep_hidden_state_noninterference(self):
        from werewolf.engine import Game, ROLES as INITIAL_ROLES
        original = list(INITIAL_ROLES)
        swapped = original.copy()
        swapped[8], swapped[9] = swapped[9], swapped[8]
        config = p.deepseek_flash_config(5, 'Observer')
        decision = {'kind': 'speech', 'options': [{'type': 'speak'}]}
        bodies = [p.wire_request(config, p.build_request(config, Game(roles=roles).observe(5), decision, 'OWN_NOTES'))
                  for roles in (original, swapped)]
        self.assertEqual(bodies[0], bodies[1])


if __name__ == '__main__':
    unittest.main()
