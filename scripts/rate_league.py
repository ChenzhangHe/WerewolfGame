"""Calculate exploratory Elo-scale ratings offline; performs no model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.ratings import fit_ratings, POLICY
from scripts.play_codex import save
from scripts.play_league import verify_plan, verify_trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path('artifacts/mixed-v3/plan.private.json'))
    parser.add_argument('--results', type=Path, default=Path('artifacts/mixed-v3/mixed-pilot-results.json'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/mixed-v3/mixed-pilot-ratings.json'))
    parser.add_argument('--freeze-policy', type=Path)
    parser.add_argument('--policy', type=Path, default=Path('artifacts/mixed-pilot-rating-policy.json'))
    args = parser.parse_args()
    if args.freeze_policy:
        # Refuse to replace the declared policy after seeing outcomes.
        with args.freeze_policy.open('x') as stream:
            json.dump(POLICY, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'policy_frozen': str(args.freeze_policy)}))
        return
    if json.loads(args.policy.read_text()) != POLICY:
        raise ValueError('Rating policy changed; preserve the old result and declare a new version.')
    plan = json.loads(args.plan.read_text())
    results = json.loads(args.results.read_text())
    verify_plan(plan)
    matches = {m['id']: m for m in plan['matches']}
    for report in results['reports']:
        if report.get('all_checks_passed'):
            match = matches[report['match_id']]
            raw = args.plan.parent / f"{match['id']}.private.json"
            audited = verify_trial(json.loads(raw.read_text()), match, plan)
            if not audited['all_checks_passed'] or audited['winner'] != report['winner']:
                raise ValueError('Rating input disagrees with independently audited game evidence.')
    rating = fit_ratings(plan['matches'], results['reports'])
    save(args.output, rating)
    print(json.dumps({'valid_games': rating['valid_games'], 'ratings': [
        {k: row[k] for k in ('entry', 'rating', 'approx_95_interval')} for row in rating['ratings']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
