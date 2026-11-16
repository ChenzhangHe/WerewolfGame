"""Recompute ratings and tournament points from portable complete gameplay."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.replays import ReplayRunner
from werewolf.ratings import fit_ratings
from werewolf.win_rates import win_rates

MODEL_FAMILIES = {'gpt-6.1-sol': 'Sol', 'gpt-6.1-terra': 'Terra'}


def replay_inputs(root, *, grouping='configuration', comparison='all', filenames=None, fixed_game_ids=None):
    if grouping not in ('configuration', 'model-family') or comparison not in ('all', 'sol-terra'):
        raise ValueError('Unknown scoring comparison or grouping.')
    matches, reports = [], []
    points = defaultdict(lambda: {'seat_appearances': 0, 'wins': 0, 'points': 0})
    exposures = defaultdict(lambda: defaultdict(int)); identities = {}
    paths = sorted(root.glob('*.json')) if filenames is None else [root/name for name in filenames]
    for path in paths:
        archive = json.loads(path.read_text())
        if comparison == 'sol-terra' and {c['entry'] for c in archive['configs']} != {'Sol','Terra'}:
            continue
        replay = ReplayRunner(archive)
        configs = archive['configs']; entries = []
        fixed = {'gpt-6.1-sol':'medium','gpt-6.1-terra':'low'}
        if fixed_game_ids is not None and all(c['model'] in fixed and c['reasoning_effort']==fixed[c['model']] for c in configs):
            fixed_game_ids.add(archive['id'])
        for c in configs:
            entry = MODEL_FAMILIES[c['model']] if grouping == 'model-family' else c['entry']
            entries.append(entry)
            identity = (c['model'], c['reasoning_effort'], c['provider'], c['interaction_mode'])
            if grouping == 'configuration' and entry in identities and identities[entry] != identity:
                raise ValueError('A configuration entry cannot mix different model/effort settings.')
            identities[entry] = identity
            exposures[entry][c['reasoning_effort']] += 1
        winner = replay.game.winner
        matches.append({'id': archive['id'], 'pair': archive['layout_group'], 'roles': archive['roles'], 'entries': entries})
        reports.append({'match_id': archive['id'], 'winner': winner, 'all_checks_passed': True})
        for entry, role in zip(entries, archive['roles']):
            win = (role == 'wolf') == (winner == 'wolves')
            row = points[entry]; row['seat_appearances'] += 1; row['wins'] += int(win); row['points'] += 3 if win else -3
    return matches, reports, dict(sorted(points.items())), {k:dict(v) for k,v in exposures.items()}


def calculate(root, *, comparison='all', grouping='configuration', filenames=None):
    fixed_ids=set()
    matches, reports, points, exposures = replay_inputs(root, comparison=comparison, grouping=grouping, filenames=filenames, fixed_game_ids=fixed_ids)
    if not matches:
        raise ValueError('No completed replay games exist yet for the selected comparison.')
    result = fit_ratings(matches, reports)
    result['win_rates']=win_rates(matches,reports)
    result['fixed_setting_win_rates']=win_rates([m for m in matches if m['id'] in fixed_ids],[r for r in reports if r['match_id'] in fixed_ids])
    result.update(tournament_points=points, entry_grouping=grouping, thinking_effort_exposure=exposures,
                  evidence_scope='Referee-validated portable gameplay; original model requests and private notes are excluded.')
    if grouping == 'model-family':
        result['interpretation'] = 'Model-level pooled historical scores; historical thinking efforts differ. Not an equal-effort comparison.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('replays'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--comparison', choices=('all','sol-terra'), default='all')
    parser.add_argument('--grouping', choices=('configuration','model-family'), default='model-family')
    args = parser.parse_args()
    result = calculate(args.directory, comparison=args.comparison, grouping=args.grouping)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'valid_games': result['valid_games'], 'entry_grouping':result['entry_grouping'],
        'ratings': [{k:r[k] for k in ('entry','rating','approx_95_interval')} for r in result['ratings']],
        'tournament_points':result['tournament_points']},ensure_ascii=False,indent=2))


if __name__ == '__main__':main()
