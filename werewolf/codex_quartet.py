"""Six-game Sol medium/low and Terra high/low comparison."""
from collections import Counter
import random

from werewolf.codex_league import ENTRIES as ALL_ENTRIES, configs_for
from werewolf.engine import Game
from werewolf.server import NAMES

ENTRIES = {e: ALL_ENTRIES[e] for e in ('sol-medium', 'sol-low', 'terra-high', 'terra-low')}
ROLE_COUNTS = Counter(wolf=4, villager=4, seer=1, witch=1, hunter=1, idiot=1)


def schedule(seed=18000):
    rng = random.Random(seed)
    entries = list(ENTRIES)
    matches = []
    # All three two-versus-two configuration partitions occur. Each complementary
    # pair gives every entry two Wolves, two Villagers and two special-role seats.
    # The permutations also limit each individual special role to one or two seats.
    for block, labels in enumerate(((0, 1, 2, 3), (0, 2, 1, 3), (3, 0, 1, 2)), 1):
        game = Game(seed=seed+100+block, names=NAMES, language='zh')
        roles = [game.players[s]['role'] for s in range(1, 13)]
        seats = [s for role in ROLE_COUNTS for s in range(12) if roles[s] == role]
        permutations = [labels, labels[2:]+labels[:2]]
        rng.shuffle(permutations)
        for a, b, c, d in permutations:
            template = [a, a, b, b, c, c, d, d, a, b, c, d]
            assigned = [None]*12
            for seat, label in zip(seats, template):
                assigned[seat] = entries[label]
            n = len(matches)+1
            matches.append({'id': f'codex-quartet-{seed}-{n:02d}', 'pair': block,
                            'seed': seed+n, 'roles': roles[:], 'entries': assigned})
    validate_schedule(matches)
    return matches


def validate_schedule(matches):
    if len(matches) != 6 or len({m['id'] for m in matches}) != 6:
        raise ValueError('Four-category pilot requires six unique games.')
    coalitions = set()
    for m in matches:
        if Counter(m['roles']) != ROLE_COUNTS or Counter(m['entries']) != Counter({e: 3 for e in ENTRIES}):
            raise ValueError('Each game requires three seats per category and the twelve-player rules.')
        wolves = Counter(e for e, r in zip(m['entries'], m['roles']) if r == 'wolf')
        if sorted(wolves.values()) != [2, 2]:
            raise ValueError('Wolf coalition composition changed.')
        coalitions.add(frozenset(wolves))
    if len(coalitions) != 6:
        raise ValueError('Every two-category Wolf coalition must occur once.')
    for entry in ENTRIES:
        counts = Counter(r for m in matches for e, r in zip(m['entries'], m['roles']) if e == entry)
        if counts['wolf'] != 6 or counts['villager'] != 6 or sum(counts.values()) != 18:
            raise ValueError('Faction role exposure changed.')
        if sorted(counts[r] for r in ('seer', 'witch', 'hunter', 'idiot')) != [1, 1, 2, 2]:
            raise ValueError('Special-role exposure must differ by at most one.')
    for block in (1, 2, 3):
        group = [m for m in matches if m['pair'] == block]
        if len(group) != 2 or group[0]['roles'] != group[1]['roles']:
            raise ValueError('Paired role layout changed.')
