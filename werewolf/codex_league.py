"""Fixed Codex configurations and preregistered role-balanced comparisons."""
from collections import Counter
import random

from werewolf.codex_harness import CodexPlayer
from werewolf.engine import Game
from werewolf.server import NAMES, PERSONALITIES

ENTRIES = {
    **{f'sol-{e}': ('gpt-6.1-sol', e) for e in ('high', 'medium', 'low')},
    **{f'terra-{e}': ('gpt-6.1-terra', e) for e in ('high', 'low')},
    **{f'luna-{e}': ('gpt-6-luna', e) for e in ('high', 'medium')},
}
ROLE_COUNTS = Counter(wolf=4, villager=4, seer=1, witch=1, hunter=1, idiot=1)


def selected_entries(profile):
    if profile == "pair":
        return {e: ENTRIES[e] for e in ("sol-medium", "terra-low")}
    if profile == "seven":
        return dict(ENTRIES)
    raise ValueError("Unknown comparison profile.")


def schedule(seed=16000, *, games=6, profile="pair"):
    """Six-game exploratory rotation, or two complete rotations for exact balance."""
    if profile == "pair":
        if games != 6:
            raise ValueError("The initial pair pilot has six games.")
        rng = random.Random(seed)
        matches = []
        a, b = selected_entries(profile)
        for pair, wolf_count in enumerate((0, 1, 2), 1):
            game = Game(seed=seed+100+pair, names=NAMES, language="zh")
            roles = [game.players[s]["role"] for s in range(1, 13)]
            wolves = [s for s in range(12) if roles[s] == "wolf"]
            good = [s for s in range(12) if roles[s] != "wolf"]
            seats = set(rng.sample(wolves, wolf_count)+rng.sample(good, 6-wolf_count))
            for side in range(2):
                n = len(matches)+1
                matches.append({"id": f"codex-pair-{seed}-{n:02d}", "pair": pair, "seed": seed+n,
                                "roles": roles[:], "entries": [a if ((s in seats) != bool(side)) else b for s in range(12)]})
        validate_schedule(matches)
        return matches
    selected_entries(profile)
    if games not in (6, 14):
        raise ValueError("Choose six or fourteen games.")
    rng = random.Random(seed)
    entries = list(ENTRIES)
    matches = []
    # Unequal faction composition within each game identifies configuration effects.
    # Rotating the labels balances exposures without changing roles within a block.
    templates = ([0, 0, 1, 2, 3, 3, 4, 5, 1, 2, 4, 6],
                 [0, 1, 1, 3, 2, 4, 5, 5, 0, 2, 3, 6])
    if games == 6:
        templates = ([0, 1, 2, 3, 3, 4, 5, 6, 0, 1, 2, 4],)
    for block, template in enumerate(templates, 1):
        game = Game(seed=seed+100+block, names=NAMES, language='zh')
        roles = [game.players[s]['role'] for s in range(1, 13)]
        seats = [s for role in ROLE_COUNTS for s in range(12) if roles[s] == role]
        labels = [None]*12
        for seat, label in zip(seats, template):
            labels[seat] = label
        rotations = list(range(7))
        rng.shuffle(rotations)
        for rotation in rotations[:6] if games == 6 else rotations:
            n = len(matches)+1
            matches.append({'id': f'codex-seven-{seed}-{n:02d}', 'pair': block,
                            'seed': seed+n, 'roles': roles[:],
                            'entries': [entries[(label+rotation)%7] for label in labels]})
    validate_schedule(matches)
    return matches


def validate_schedule(matches):
    if len(matches) not in (6, 14) or len({m['id'] for m in matches}) != len(matches):
        raise ValueError('Expected six or fourteen unique games.')
    if {e for m in matches for e in m['entries']} == set(selected_entries('pair')):
        if len(matches) != 6:
            raise ValueError('Pair pilot requires six games.')
        a, b = selected_entries('pair')
        for m in matches:
            if Counter(m['entries']) != Counter({a: 6, b: 6}) or Counter(m['roles']) != ROLE_COUNTS:
                raise ValueError('Pair game composition changed.')
        for pair in (1, 2, 3):
            group = [m for m in matches if m['pair'] == pair]
            if len(group) != 2 or group[0]['roles'] != group[1]['roles'] or any(x == y for x, y in zip(group[0]['entries'], group[1]['entries'])):
                raise ValueError('Pair assignments must be complementary.')
        for e in (a, b):
            counts = Counter(r for m in matches for entry, r in zip(m['entries'], m['roles']) if entry == e)
            if counts != Counter(wolf=12, villager=12, seer=3, witch=3, hunter=3, idiot=3):
                raise ValueError('Pair role balance changed.')
        if {sum(e == a and r == 'wolf' for e, r in zip(m['entries'], m['roles'])) for m in matches} != set(range(5)):
            raise ValueError('Faction composition must vary.')
        return
    exposures = {e: Counter() for e in ENTRIES}
    positions = {e: Counter() for e in ENTRIES}
    for match in matches:
        if len(match['entries']) != 12 or set(match['entries']) != set(ENTRIES):
            raise ValueError('Every game must include all seven entries.')
        if Counter(match['roles']) != ROLE_COUNTS:
            raise ValueError('Invalid role layout.')
        if sorted(Counter(match['entries']).values()) != [1, 1, 2, 2, 2, 2, 2]:
            raise ValueError('Each entry must have one or two seats per game.')
        for seat, (entry, role) in enumerate(zip(match['entries'], match['roles']), 1):
            exposures[entry][role] += 1
            positions[entry][seat] += 1
    if len(matches) == 6:
        if sorted(sum(c.values()) for c in exposures.values()) != [10, 10, 10, 10, 10, 11, 11]:
            raise ValueError("Six-game seat exposure must differ by at most one.")
        for c in exposures.values():
            if any(c[r] not in (3, 4) for r in ("wolf", "villager")) or any(c[r] not in (0, 1) for r in ("seer", "witch", "hunter", "idiot")):
                raise ValueError("Six-game role exposure changed.")
        if any(max(c.values()) > 1 for c in positions.values()):
            raise ValueError("Six-game entries must rotate seats and personalities.")
        if any(m["pair"] != 1 or m["roles"] != matches[0]["roles"] for m in matches):
            raise ValueError("Six-game shared layout changed.")
        return
    expected = Counter(wolf=8, villager=8, seer=2, witch=2, hunter=2, idiot=2)
    if any(c != expected for c in exposures.values()):
        raise ValueError('Role exposure is not balanced.')
    if any(c != Counter({s: 2 for s in range(1, 13)}) for c in positions.values()):
        raise ValueError('Seat and personality exposure is not balanced.')
    for block in (1, 2):
        group = [m for m in matches if m['pair'] == block]
        if len(group) != 7 or any(m['roles'] != group[0]['roles'] for m in group):
            raise ValueError('Rotation block changed role layouts.')


def configs_for(match):
    return [CodexPlayer(s, NAMES[s-1], model=ENTRIES[e][0], effort=ENTRIES[e][1],
                        language='zh', personality=PERSONALITIES[s-1])
            for s, e in enumerate(match['entries'], 1)]
