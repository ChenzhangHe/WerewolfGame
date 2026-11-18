"""Balanced six-game schedules for three Codex configurations."""
from collections import Counter
from dataclasses import replace
import random

from werewolf.codex_league import ENTRIES as ALL_ENTRIES, configs_for as league_configs_for
from werewolf.engine import Game
from werewolf.server import NAMES

ENTRIES = {e: ALL_ENTRIES[e] for e in ('sol-medium', 'terra-low', 'luna-medium')}
VERSION_ENTRIES = {
    "Sol-6.1": ("gpt-6.1-sol", "medium"),
    "Sol-6.2": ("gpt-6.2-sol", "medium"),
    "Terra": ("gpt-6.1-terra", "low"),
}
PROFILES = {"legacy": ENTRIES, "sol-versions": VERSION_ENTRIES}
ROLE_COUNTS = Counter(wolf=4, villager=4, seer=1, witch=1, hunter=1, idiot=1)


def schedule(seed=17000, profile="legacy"):
    rng = random.Random(seed)
    entries = list(PROFILES[profile])
    # Four seats per entry, with 3/1/0 and 2/1/1 Wolf compositions.
    # Every label occupies every seat once per three-game rotation block.
    templates = ([0, 0, 0, 1, 1, 1, 2, 2, 0, 1, 2, 2],
                 [0, 0, 1, 2, 1, 1, 2, 0, 0, 1, 2, 2])
    matches = []
    for block, template in enumerate(templates, 1):
        game = Game(seed=seed+100+block, names=NAMES, language='zh')
        roles = [game.players[s]['role'] for s in range(1, 13)]
        seats = [s for role in ROLE_COUNTS for s in range(12) if roles[s] == role]
        labels = [None]*12
        for seat, label in zip(seats, template):
            labels[seat] = label
        rotations = list(range(3)); rng.shuffle(rotations)
        for rotation in rotations:
            n = len(matches)+1
            matches.append({'id': f'codex-trio-{seed}-{n:02d}', 'pair': block,
                            'seed': seed+n, 'roles': roles[:],
                            'entries': [entries[(label+rotation)%3] for label in labels]})
    validate_schedule(matches, profile)
    return matches


def validate_schedule(matches, profile="legacy"):
    entries = PROFILES[profile]
    if len(matches) != 6 or len({m['id'] for m in matches}) != 6:
        raise ValueError('Trio pilot requires six unique games.')
    for m in matches:
        if Counter(m['roles']) != ROLE_COUNTS or Counter(m['entries']) != Counter({e: 4 for e in entries}):
            raise ValueError('Trio game requires the twelve-player rules and four seats per entry.')
    for entry in entries:
        roles = Counter(r for m in matches for e, r in zip(m['entries'], m['roles']) if e == entry)
        if roles != Counter(wolf=8, villager=8, seer=2, witch=2, hunter=2, idiot=2):
            raise ValueError('Trio role exposure changed.')
        positions = Counter(s for m in matches for s, e in enumerate(m['entries'], 1) if e == entry)
        if positions != Counter({s: 2 for s in range(1, 13)}):
            raise ValueError('Seat and personality exposure changed.')
    for block in (1, 2):
        group = [m for m in matches if m['pair'] == block]
        if len(group) != 3 or any(m['roles'] != group[0]['roles'] for m in group):
            raise ValueError('Rotation role layout changed.')


def configs_for(match):
    if set(match['entries']) == set(VERSION_ENTRIES):
        # The original factory supplies the canonical seat names and personalities.
        template = league_configs_for({**match, 'entries': ['sol-medium'] * 12})
        return [
            replace(config, model=VERSION_ENTRIES[entry][0], effort=VERSION_ENTRIES[entry][1])
            for config, entry in zip(template, match['entries'])
        ]
    return league_configs_for(match)
