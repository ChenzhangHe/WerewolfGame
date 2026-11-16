"""Descriptive faction-win rates by model, numbered seat and role."""
ROLES = ('wolf','villager','seer','witch','hunter','idiot')


def row():
    return {'wins':0,'losses':0,'appearances':0,'win_rate':None}


def win_rates(matches, reports):
    by_id={m['id']:m for m in matches}
    if len(by_id)!=len(matches) or len({r['match_id'] for r in reports})!=len(reports):
        raise ValueError('Duplicate game IDs would count outcomes twice.')
    if any(r['match_id'] not in by_id for r in reports):
        raise ValueError('Unknown game result.')
    models=sorted({entry for m in matches for entry in m['entries']})
    overall={m:row() for m in models}
    seats={str(s):{m:row() for m in models} for s in range(1,13)}
    roles={r:{m:row() for m in models} for r in ROLES}
    cells={str(s):{r:{m:row() for m in models} for r in ROLES} for s in range(1,13)}
    valid=0
    for report in reports:
        if not report.get('all_checks_passed'):continue
        if report.get('winner') not in ('good','wolves'):raise ValueError('An audited outcome must identify a winning faction.')
        match=by_id[report['match_id']]
        if len(match['roles'])!=12 or len(match['entries'])!=12 or set(match['roles'])-set(ROLES):
            raise ValueError('Seat statistics require the twelve-seat rules.')
        valid+=1
        for seat,(model,role) in enumerate(zip(match['entries'],match['roles']),1):
            won=(role=='wolf')==(report['winner']=='wolves')
            for target in (overall[model],seats[str(seat)][model],roles[role][model],cells[str(seat)][role][model]):
                target['appearances']+=1;target['wins']+=int(won);target['losses']+=int(not won)
    def rates(value):
        if 'appearances' in value:
            value['win_rate']=round(value['wins']/value['appearances'],6) if value['appearances'] else None
        else:
            for child in value.values():rates(child)
    for value in (overall,seats,roles,cells):rates(value)
    return {'valid_games':valid,'models':models,'overall':overall,'by_seat':seats,'by_role':roles,'by_seat_and_role':cells,
            'definition':'Win means the seat faction won; counts are seat appearances, not independent games.',
            'limitations':['Seat, role, fixed personality and same-game teammates may be associated; these are not causal seat effects.',
                           'Always show wins and appearances. A cell without observations has null win rate.',
                           'Historical thinking efforts differ in the pooled model-family view.']}
