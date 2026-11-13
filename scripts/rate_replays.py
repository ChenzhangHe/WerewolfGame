"""Recompute Elo-style ratings and tournament points from Git-tracked gameplay."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.replays import ReplayRunner
from werewolf.ratings import fit_ratings, POLICY


def calculate(root):
    matches, reports = [], []
    points = defaultdict(lambda: {'seat_appearances': 0, 'wins': 0, 'points': 0})
    identities = {}
    for path in sorted(root.glob('*.json')):
        archive = json.loads(path.read_text()); replay = ReplayRunner(archive)
        configs = archive['configs']; entries = [c['entry'] for c in configs]
        for c in configs:
            identity = tuple(c[k] for k in ('model', 'reasoning_effort', 'provider', 'interaction_mode'))
            if c['entry'] in identities and identities[c['entry']] != identity:
                raise ValueError('One rating entry cannot combine different model/effort settings.')
            identities[c['entry']] = identity
        winner = replay.game.winner
        matches.append({'id': archive['id'], 'pair': archive['layout_group'], 'roles': archive['roles'], 'entries': entries})
        reports.append({'match_id': archive['id'], 'winner': winner, 'all_checks_passed': True})
        for entry, role in zip(entries, archive['roles']):
            win = (role == 'wolf') == (winner == 'wolves')
            row = points[entry]; row['seat_appearances'] += 1; row['wins'] += int(win); row['points'] += 3 if win else -3
    result = fit_ratings(matches, reports)
    result['tournament_points'] = dict(sorted(points.items()))
    result['evidence_scope'] = 'Referee-validated portable gameplay; original model requests and private notes are intentionally excluded.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('replays'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = calculate(args.directory)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'valid_games': result['valid_games'], 'ratings': [{k:r[k] for k in ('entry', 'rating', 'approx_95_interval')} for r in result['ratings']], 'tournament_points':result['tournament_points']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
