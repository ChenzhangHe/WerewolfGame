"""Export complete, independently replayed gameplay without inference internals."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.replays import ReplayRunner, FORMAT
from scripts.play_codex import audit_match, canonical_game


def export(source, output):
    raw = source.read_bytes(); trial = json.loads(raw)
    audit = audit_match(trial)
    if not audit['all_checks_passed']:
        raise ValueError('Only fully audited, completed games may be published.')
    configs = []
    for p in sorted(trial['players'], key=lambda p: p['config']['seat']):
        c = p['config']; family = c['model'].removeprefix('gpt-6.1-').removeprefix('gpt-6-')
        configs.append({'seat': c['seat'], 'name': c['name'], 'provider': 'codex', 'model': c['model'],
                        'reasoning_effort': c['effort'], 'personality': c['personality'], 'language': c['language'],
                        'interaction_mode': 'tools', 'entry': family+'-'+c['effort']})
    batches = []
    for batch in trial['game']['submitted_batches']:
        batches.append([{'seat': d['seat'], 'kind': d['kind'],
                         'action': {k: v for k, v in batch['actions'][d['id']].items() if k in {'type','target','value','text'}}}
                        for d in batch['decisions']])
    stem = source.name.removesuffix('.private.json'); parts = stem.rsplit('-', 2); number = int(parts[-1]); cohort = parts[-2]
    archive = {'format': FORMAT, 'ruleset': 'rules-v1', 'id': stem, 'title': f'四配置测试 · {cohort} · 第{number}局',
               'language': trial['language'], 'seed': trial['source_seed'],
               'roles': [p['role'] for p in sorted(trial['game']['players'], key=lambda p:p['seat'])],
               'configs': configs, 'batches': batches, 'layout_group': f'{cohort}:{(number-1)//2+1}',
               'source_digest': hashlib.sha256(raw).hexdigest()}
    replay = ReplayRunner(archive)
    if canonical_game(replay.game.export()) != canonical_game(trial['game']):
        raise ValueError('Published replay differs from the audited referee history.')
    output.mkdir(parents=True, exist_ok=True); target = output/f'{stem}.json'
    if target.exists():
        raise ValueError('Do not overwrite a published replay.')
    target.write_text(json.dumps(archive, ensure_ascii=False, separators=(',', ':'))+'\n')
    print(json.dumps({'id':stem, 'checkpoints':replay.max_step, 'winner': replay.game.winner}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, default=Path('replays'))
    args = parser.parse_args()
    for source in args.sources:
        export(source, args.output)


if __name__ == '__main__':
    main()
