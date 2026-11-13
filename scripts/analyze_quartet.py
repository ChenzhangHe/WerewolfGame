"""Offline descriptive pilot statistics; never writes private notes or speeches."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.play_codex import save


def analyze(root):
    rows = defaultdict(lambda: {'decisions': 0, 'seconds': [], 'input_tokens': 0, 'cached_input_tokens': 0,
                               'output_tokens': 0, 'reported_reasoning_tokens': 0, 'note_tool_writes': 0,
                               'good_exile_votes': 0, 'good_exile_votes_targeting_wolves': 0,
                               'poisons_targeting_wolves': 0, 'poisons_targeting_good': 0})
    totals = Counter(); hashes = {}
    for path in sorted(root.glob('codex-quartet-18000-??.private.json')):
        raw = path.read_bytes(); t = json.loads(raw)
        if t['status'] != 'finished':
            raise ValueError('Descriptive analysis requires completed games.')
        summary = json.loads(path.with_name(path.name.replace('.private.json', '.json')).read_text())
        if not summary['all_checks_passed']:
            raise ValueError('Do not analyze unaudited outcomes as valid games.')
        hashes[path.name] = hashlib.sha256(raw).hexdigest(); totals['games'] += 1
        for key in ('exiled_wolves', 'exiled_good', 'explosions', 'explosion_decisions', 'public_speeches', 'upstream_retry_notifications'):
            totals[key] += summary.get(key, 0)
        roles = {p['seat']: p['role'] for p in t['game']['players']}
        for p in t['players']:
            c = p['config']; key = ('sol' if c['model'] == 'gpt-6.1-sol' else 'terra')+'-'+c['effort']; row = rows[key]
            for d in p['decisions']:
                if not d.get('committed'):
                    continue
                row['decisions'] += 1; row['seconds'].append(d['elapsed_seconds']); totals['decisions'] += 1
                action = d['action']; target = action.get('target')
                if d['decision']['kind'] == 'exile_vote' and roles[c['seat']] != 'wolf' and target is not None:
                    row['good_exile_votes'] += 1
                    row['good_exile_votes_targeting_wolves'] += int(roles[target] == 'wolf')
                if action['type'] == 'poison':
                    row['poisons_targeting_wolves' if roles[target] == 'wolf' else 'poisons_targeting_good'] += 1
                for hop in d.get('tool_trace', []):
                    usage = hop.get('usage', {})
                    for dest, source in (('input_tokens','inputTokens'),('cached_input_tokens','cachedInputTokens'),
                                         ('output_tokens','outputTokens'),('reported_reasoning_tokens','reasoningOutputTokens')):
                        row[dest] += usage.get(source, 0)
                    row['note_tool_writes'] += sum(call.get('name') == 'write_my_notes' for call in hop.get('calls', []))
    for row in rows.values():
        seconds = row.pop('seconds')
        row.update(median_seconds=round(statistics.median(seconds), 2), mean_seconds=round(statistics.mean(seconds), 2), max_seconds=max(seconds))
    return {'kind': 'descriptive-not-causal', 'totals': dict(totals), 'settings': dict(rows), 'source_hashes': hashes,
            'limitations': ['Six correlated team outcomes; seat decisions are not independent games.',
                           'Response timings mix roles, phases, tool hops, caching and transport delays.',
                           'Votes targeting wolves measure target alignment, not whether a vote was strategically optimal.',
                           'Thread history persists independently of the optional private-note tool.',
                           'Reported reasoning-token counts do not reveal actual internal reasoning quality.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('artifacts/codex-quartet-v1'))
    args = parser.parse_args()
    data = analyze(args.root); save(args.root/'observations.json', data)
    print(json.dumps(data, ensure_ascii=False))


if __name__ == '__main__':
    main()
