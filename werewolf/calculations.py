"""Pure arithmetic over public facts and explicitly supplied role hypotheses.

No engine, archive, pending ballot, provider, or hidden-role assignment is read.
"""
from collections import Counter

ROLE_COUNTS = {'wolf': 4, 'villager': 4, 'seer': 1, 'witch': 1, 'hunter': 1, 'idiot': 1}


def exile_votes(players, ballots):
    if not isinstance(ballots, list) or len(ballots) > 12:
        raise ValueError('Supply at most twelve proposed ballots.')
    eligible = {p['seat']: p for p in players if p['alive'] and p.get('revealed_role') != 'idiot'}
    seen, tally = set(), Counter()
    for ballot in ballots:
        if not isinstance(ballot, dict) or set(ballot) != {'seat', 'target'}:
            raise ValueError('Each proposed ballot needs seat and target.')
        seat, target = ballot['seat'], ballot['target']
        if type(seat) is not int or seat not in eligible or seat in seen:
            raise ValueError('Voter must be a unique, living ordinary voter.')
        if target is not None and (type(target) is not int or target not in eligible):
            raise ValueError('Target must be a living eligible seat, or null to abstain.')
        seen.add(seat)
        if target is not None:
            tally[target] += 1.5 if eligible[seat].get('sheriff') else 1
    maximum = max(tally.values(), default=0)
    return {'basis': 'User-proposed ordinary exile ballots, not unpublished actual votes. Runoff exclusions are not applied.',
            'tally': {str(s): tally[s] for s in sorted(tally)},
            'leaders': sorted(s for s, count in tally.items() if count == maximum),
            'unspecified_voters': sorted(set(eligible) - seen),
            'all_ordinary_voters_supplied': set(eligible) == seen}


def win_hypothesis(players, own_seat, own_role, wolf_teammates, assignments, additional_deaths, role_counts=None):
    basis = 'Hypothetical roles supplied by you, not confirmation of other hidden roles. No night abilities or death sequence are simulated.'
    counts = role_counts or ROLE_COUNTS
    if not isinstance(assignments, list) or not isinstance(additional_deaths, list):
        raise ValueError('Supply role assignments and additional deaths as lists.')
    assumed = {}
    for item in assignments:
        if not isinstance(item, dict) or set(item) != {'seat', 'role'}:
            raise ValueError('Each role assumption needs seat and role.')
        seat, role = item['seat'], item['role']
        if type(seat) is not int or seat not in range(1, 13) or seat in assumed or not isinstance(role, str) or role not in ROLE_COUNTS:
            raise ValueError('Use each seat once with a supported role.')
        assumed[seat] = role
    if (len(additional_deaths) > 12
            or any(type(s) is not int or s not in range(1, 13) for s in additional_deaths)
            or len(set(additional_deaths)) != len(additional_deaths)):
        raise ValueError('Additional deaths must be unique seats.')
    known = {p['seat']: p['revealed_role'] for p in players if p.get('revealed_role')}
    known[own_seat] = own_role
    if own_role == 'wolf':
        known.update({s: 'wolf' for s in wolf_teammates})
    conflicts = []
    if set(assumed) != set(range(1, 13)):
        conflicts.append('Supply assumptions for all twelve seats.')
    if Counter(assumed.values()) != Counter(counts):
        conflicts.append('Role counts do not match the public lineup.')
    for seat, role in known.items():
        if assumed.get(seat) != role:
            conflicts.append(f'Seat {seat} conflicts with information already known to you.')
    if own_role == 'wolf' and {s for s, role in assumed.items() if role == 'wolf'} != set(wolf_teammates):
        conflicts.append('Assumed Wolves conflict with your known team roster.')
    if conflicts:
        return {'basis': basis, 'valid_hypothesis': False, 'conflicts': conflicts}
    living = [p['seat'] for p in players if p['alive'] and p['seat'] not in additional_deaths]
    wolves = [s for s in living if assumed[s] == 'wolf']
    villagers = [s for s in living if assumed[s] == 'villager']
    specials = [s for s in living if assumed[s] not in ('wolf', 'villager')]
    winner = 'good' if not wolves else 'wolves' if not villagers or not specials else None
    return {'basis': basis, 'valid_hypothesis': True,
            'unverified_role_seats': sorted(set(assumed) - set(known)),
            'living_wolves_under_assumptions': wolves,
            'living_villagers_under_assumptions': villagers,
            'living_specials_under_assumptions': specials,
            'winner_under_assumptions': winner}
