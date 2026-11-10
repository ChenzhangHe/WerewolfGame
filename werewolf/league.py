"""Frozen, role-balanced two-configuration pilot; no player-visible rating data."""
from collections import Counter
from dataclasses import replace
import random

from werewolf.codex_harness import CodexPlayer
from werewolf.engine import Game
from werewolf.providers import deepseek_flash_config
from werewolf.server import NAMES, PERSONALITIES

SOL = 'sol-high-codex'
DEEPSEEK = 'deepseek-flash-high-tools'
ENTRIES = (SOL, DEEPSEEK)
ROLES = ('wolf', 'villager', 'seer', 'witch', 'hunter', 'idiot')
PROTOCOL = 'mixed-league-v1'


def schedule(seed=12000):
    """Six fresh paired layouts; complementary assignments balance every role exactly."""
    rng = random.Random(seed)
    matches = []
    for pair, count in enumerate((0, 1, 2, 2, 3, 4)):
        layout = Game(seed=seed+100+pair, names=NAMES, language='zh')
        roles = [layout.players[s]['role'] for s in range(1, 13)]
        wolves = [s for s in range(1, 13) if roles[s-1] == 'wolf']
        good = [s for s in range(1, 13) if roles[s-1] != 'wolf']
        sol_seats = set(rng.sample(wolves, count)+rng.sample(good, 6-count))
        for side in range(2):
            entries = [SOL if ((s in sol_seats) != bool(side)) else DEEPSEEK for s in range(1, 13)]
            matches.append({'id': f'pilot-{seed}-{len(matches)+1:02d}', 'pair': pair+1,
                            'seed': seed+len(matches)+1, 'roles': roles[:], 'entries': entries})
    validate_schedule(matches)
    return matches


def validate_schedule(matches):
    if len(matches) != 12 or len({m['id'] for m in matches}) != 12:
        raise ValueError('Pilot requires twelve uniquely identified games.')
    exposures = {entry: Counter() for entry in ENTRIES}
    for match in matches:
        if Counter(match['entries']) != Counter({SOL: 6, DEEPSEEK: 6}):
            raise ValueError('Every game requires six seats per entry.')
        if Counter(match['roles']) != Counter(wolf=4, villager=4, seer=1, witch=1, hunter=1, idiot=1):
            raise ValueError('Invalid role layout.')
        for entry, role in zip(match['entries'], match['roles']):
            exposures[entry][role] += 1
    expected = Counter(wolf=24, villager=24, seer=6, witch=6, hunter=6, idiot=6)
    if any(count != expected for count in exposures.values()):
        raise ValueError('Season role exposure is not balanced.')
    counts = {sum(e == SOL and r == 'wolf' for e, r in zip(m['entries'], m['roles'])) for m in matches}
    if counts != set(range(5)):
        raise ValueError('Faction composition must vary to identify entry differences.')


def configs_for(match):
    result = []
    for seat, entry in enumerate(match['entries'], 1):
        args = dict(seat=seat, name=NAMES[seat-1], personality=PERSONALITIES[seat-1], language='zh')
        if entry == SOL:
            result.append(CodexPlayer(**args, model='gpt-6.1-sol', effort='high'))
        elif entry == DEEPSEEK:
            result.append(replace(deepseek_flash_config(**args), thinking='enabled',
                                  reasoning_effort='high', temperature=None, max_tokens=32768))
        else:
            raise ValueError('Unknown entry.')
    return result


def scoreboard(matches, reports):
    """Game is the outcome unit; no Elo or spurious twelve-independent-trials claim."""
    by_id = {report['match_id']: report for report in reports}
    scores = {entry: {role: {'appearances': 0, 'wins': 0, 'points': 0} for role in ROLES} for entry in ENTRIES}
    valid = 0
    for match in matches:
        report = by_id.get(match['id'])
        if not report or not report.get('all_checks_passed') or report.get('winner') not in ('good', 'wolves'):
            continue
        valid += 1
        for entry, role in zip(match['entries'], match['roles']):
            win = (role == 'wolf') == (report['winner'] == 'wolves')
            record = scores[entry][role]
            record['appearances'] += 1
            record['wins'] += int(win)
            record['points'] += 3 if win else -3
    table = []
    for entry, roles in scores.items():
        totals = {key: sum(r[key] for r in roles.values()) for key in ('appearances', 'wins', 'points')}
        # Fixed role/faction weighting, independent of which games have finished.
        weights = dict(wolf=.5, villager=.25, seer=.0625, witch=.0625, hunter=.0625, idiot=.0625)
        balanced = (sum(weights[r]*v['wins']/v['appearances'] for r, v in roles.items())
                    if all(v['appearances'] for v in roles.values()) else None)
        table.append({'entry': entry, **totals, 'roles': roles, 'balanced_win_rate': balanced,
                      'balanced_points_per_seat': 6*balanced-3 if balanced is not None else None})
    return {'scoring_version': 'team-outcome-v1', 'scheduled_games': len(matches), 'valid_games': valid,
            'attempted_games': len(reports), 'unscored_attempts': [r['match_id'] for r in reports if not r.get('all_checks_passed')],
            'table': table, 'rating_status': 'pilot-only-no-Elo-fit',
            'notes': ['Team victory +3; defeat -3. No automatic MVP or behavior bonus.',
                      'Balanced metric weights Wolves 50%, Villagers 25%, each special role 6.25%.',
                      'Seat outcomes within a game and complementary games within a pair are correlated.',
                      'Configurations differ in both model and harness; this is not a model-only comparison.']}
